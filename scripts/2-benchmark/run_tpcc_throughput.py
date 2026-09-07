#!/usr/bin/env python3
"""TPC-C throughput: transactions per minute at a given concurrency.

    python3 run_tpcc_throughput.py --dbms postgresql --schema indexed \
        --concurrency 50 --duration 60 --out results/corrected/measurements/tpcc_throughput.csv

Complements `run_tpcc.py` rather than replacing it. That one measures a single
transaction's latency with nothing else running, which isolates what the ORM
costs per call. This one measures how many transactions complete per minute with
N clients competing, which is what TPC-C is actually specified to report and what
the paper states its TPC-C results in. They answer different questions and the
numbers are not interchangeable: a framework can be slower per transaction and
still finish more of them per minute, or the reverse.

## Why a separate script from the earlier concurrency harness

The earlier harness measured throughput at concurrency levels already, and for TPC-C it
calls `run_transaction_orm` and nothing else - there is no `run_transaction_sql`
call anywhere in it. So it can compare Django's ORM against SQLAlchemy's ORM,
which is what the paper's QPM figures do, but it cannot produce the
ORM-versus-SQL comparison this study is about. This script runs all four paths.

## What is counted

A transaction counts when it commits. Transactions that abort are counted
separately and reported, never silently dropped: TPC-C under concurrency
produces real deadlocks and serialisation failures, and a harness that swallows
them reports a framework that fails often as a framework that is fast. If the
abort rate is high the throughput figure beside it is not comparable, so both
travel together in the output.

Each worker gets its own connection, its own SQLAlchemy Session - Session is not
thread-safe - and its own seeded RNG, offset by worker index so the workers do
not all contend for the same district. Warmup runs first and is not counted.
"""
import argparse
import csv
import os
import random
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")

import django
django.setup()

from django.db import connections
import tpcc_config as cfg

TXN = {
    1: ("T1", "New-Order", "t1_neworder", "t1"),
    2: ("T2", "Payment", "t2_payment", "t2"),
    3: ("T3", "Order-Status", "t3_orderstatus", "t3"),
    4: ("T4", "Delivery", "t4_delivery", "t4"),
    5: ("T5", "Stock-Level", "t5_stocklevel", "t5"),
}

FIELDS = ["benchmark", "dbms", "schema_config", "transaction_id", "name",
          "framework", "path", "concurrency", "duration_s", "committed",
          "aborted", "abort_pct", "qpm", "qps", "p50_ms", "p95_ms", "note"]


def append_rows(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            w.writeheader()
        w.writerows(rows)


def worker(fn, stop, seed, committed, aborted, latencies, lock, errors):
    rng = random.Random(seed)
    local_ok, local_bad, local_lat = 0, 0, []
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            fn(rng)
            local_lat.append((time.perf_counter() - t0) * 1000.0)
            local_ok += 1
        except Exception as e:
            local_bad += 1
            if len(errors) < 5:
                with lock:
                    errors.append("%s: %s" % (type(e).__name__, str(e)[:80]))
    # Django's `connections` is thread-local: this thread opened its own on
    # first use, and nothing else can close it. run_path() spawns 50 fresh
    # threads for every path, so without this the run leaks 50 server sessions
    # per path and roughly 1000 across a campaign.
    #
    # It survived three systems because their connection limits are generous
    # enough to absorb it. Oracle Free's processes=200 is not: Django's paths
    # began failing with DPY-6005 "cannot connect to database" while
    # SQLAlchemy's, which share one bounded pool built once for the whole run,
    # kept going. Measured on the Oracle indexed campaign, abort rate by path -
    # django/sql T2 11.46%, T3 9.17%, T5 17.79%, T4 61.01%, against
    # sqlalchemy/sql T2 0.22% and 0% everywhere else.
    #
    # A leaked connection is not a property of Django. It is a property of a
    # harness that opens one per thread and never closes it, and it was being
    # charged to Django as a lower QPM.
    try:
        from django.db import connections as _dj_conns
        _dj_conns.close_all()
    except Exception:
        pass

    # The same obligation on the SQLAlchemy side, and for the same reason: one
    # Session per worker per path, 500 of them per (system, schema) against a
    # pool of 65. Returning it to the pool here is what stops the last path to
    # run - sqlalchemy/sql, which meets a pool the sqlalchemy/orm run has already
    # drawn on - from queueing until the checkout times out. C25.
    _sess = getattr(fn, "_session", None)
    if _sess is not None:
        try:
            _sess.close()
        except Exception:
            pass

    with lock:
        committed.append(local_ok)
        aborted.append(local_bad)
        latencies.extend(local_lat)


# Delivery consumes new_order rows. Every other transaction either inserts
# (New-Order, Payment) or only reads (Order-Status, Stock-Level), so Delivery is
# the one that can run out of work.
#
# This is not hypothetical. Measured on PostgreSQL non-indexed at concurrency 50:
# new_order held 105,020 rows when T4 began, and T4's django/sql path performed
# 36,244 deliveries x 10 districts, draining it to 2,439. Everything after that
# was Delivery finding nothing to deliver and returning immediately, so the
# 36,216 QPM recorded for that path - and the 30,275 QPM for the path after it -
# measured an empty table at speed. Fast, plausible, and not Delivery.
#
# Real TPC-C never hits this because it runs a *mix*: 45% New-Order against 4%
# Delivery, so inserts outpace consumption. Measuring one transaction type at a
# time at full rate removes that balance, which is a property of the isolation
# this study needs rather than a fault in the workload.
#
# So the table is refilled before each Delivery path, identically, and the run
# is checked afterwards for having starved anyway.
CONSUMES_ROWS = {"T4"}


def replenish(dj_conn, dbms):
    """Refill new_order so every order without one is undeliverable again."""
    # ORDER is reserved in all four dialects, so it is always quoted - and a
    # quoted identifier is case-sensitive. load_tpcc.py creates Oracle's as
    # "ORDER", so the lowercase default that serves the other three raises
    # ORA-00942 here. Same table, same quoting rule, opposite folding.
    q = {"postgresql": '"order"', "mysql": "`order`",
         "sqlserver": "[order]", "oracle": '"ORDER"'}.get(dbms, '"order"')
    with dj_conn.cursor() as c:
        c.execute("""INSERT INTO new_order (no_o_id, no_d_id, no_w_id)
                     SELECT o_id, o_d_id, o_w_id FROM %s o
                      WHERE NOT EXISTS (SELECT 1 FROM new_order n
                                        WHERE n.no_w_id = o.o_w_id
                                          AND n.no_d_id = o.o_d_id
                                          AND n.no_o_id = o.o_id)""" % q)
        c.execute("SELECT COUNT(*) FROM new_order")
        return c.fetchone()[0]


def new_order_count(dj_conn):
    with dj_conn.cursor() as c:
        c.execute("SELECT COUNT(*) FROM new_order")
        return c.fetchone()[0]


def run_path(make_fn, concurrency, duration, warmup, seed_base):
    """Spawn `concurrency` workers, warm up, then count commits for `duration`."""
    committed, aborted, latencies, errors = [], [], [], []
    lock = threading.Lock()
    stop = threading.Event()

    threads = []
    for i in range(concurrency):
        fn = make_fn(i)
        t = threading.Thread(
            target=worker,
            args=(fn, stop, seed_base + i * 7919, committed, aborted,
                  latencies, lock, errors),
            daemon=True)
        threads.append(t)

    # Warmup is inside the same worker loop; discard whatever accumulated.
    for t in threads:
        t.start()
    time.sleep(warmup)
    with lock:
        committed.clear()
        aborted.clear()
        latencies.clear()

    t0 = time.perf_counter()
    time.sleep(duration)
    stop.set()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.perf_counter() - t0

    ok, bad = sum(committed), sum(aborted)
    lat = sorted(latencies)
    return {
        "committed": ok,
        "aborted": bad,
        "abort_pct": round(100.0 * bad / (ok + bad), 2) if (ok + bad) else 0.0,
        "qps": round(ok / elapsed, 2) if elapsed else 0.0,
        "qpm": round(ok / elapsed * 60.0, 1) if elapsed else 0.0,
        "p50_ms": round(statistics.median(lat), 3) if lat else "",
        "p95_ms": round(lat[int(len(lat) * 0.95)], 3) if len(lat) > 20 else "",
        "note": "; ".join(errors[:3]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbms", default="postgresql")
    ap.add_argument("--schema", default="indexed", choices=["indexed", "non-indexed"])
    ap.add_argument("--transactions", default="1,2,3,4,5")
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    conn = connections["default"]
    with conn.cursor() as c:
        cfg.verify_against(c)
    print("TPC-C throughput  %s %s  concurrency=%d  duration=%ds (+%ds warmup)"
          % (args.dbms, args.schema, args.concurrency, args.duration, args.warmup))
    print("  %s\n" % cfg.summary())

    dsn = os.environ.get("SA_DSN")
    if not dsn:
        print("SA_DSN is not set", file=sys.stderr)
        return 2
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    # The pool must be able to give every worker its own connection, or workers
    # queue on the pool and the number measured is the pool size, not the
    # database's throughput.
    engine = create_engine(dsn, pool_size=args.concurrency + 5,
                           max_overflow=10, pool_pre_ping=True)

    rows = []
    for n in [int(x) for x in args.transactions.split(",")]:
        tid, name, dj_mod, sa_mod = TXN[n]
        dj = __import__("django_app.tpcc_queries.%s" % dj_mod, fromlist=["x"])
        sa = __import__("sqlalchemy_app.tpcc_queries.%s" % sa_mod, fromlist=["x"])

        # Django's `connections` is thread-local, so each worker opens its own
        # connection on first use and must close it or the pool leaks.
        def dj_orm(i):
            def f(rng):
                try:
                    return dj.run_transaction_orm(using="default")
                finally:
                    pass
            return f

        def dj_sql(i):
            def f(rng):
                return dj.run_transaction_sql(connections["default"])
            return f

        # `f._session` is how worker() finds the Session to close when the thread
        # ends. Nothing closed it before: C21 fixed the Django half of this leak
        # and recorded that SQLAlchemy was "structurally immune ... bounded by
        # construction". The bound is on connections, not sessions, and bounding
        # the connections is exactly what turns an unbounded leak into a queue
        # with a timeout - so the leak presented as 70 aborted transactions on
        # seven of the eight sqlalchemy/sql T2 rows, identical on systems whose
        # throughput differs by a factor of 3.4. Defect C25.
        def sa_orm(i):
            sess = Session(engine)
            def f(rng):
                try:
                    return sa.run_transaction_orm(sess)
                except Exception:
                    sess.rollback()
                    raise
            f._session = sess
            return f

        def sa_sql(i):
            sess = Session(engine)
            def f(rng):
                try:
                    return sa.run_transaction_sql(sess)
                except Exception:
                    sess.rollback()
                    raise
            f._session = sess
            return f

        for framework, path, mk in (("django", "orm", dj_orm),
                                    ("django", "sql", dj_sql),
                                    ("sqlalchemy", "orm", sa_orm),
                                    ("sqlalchemy", "sql", sa_sql)):
            print("  %s %s/%s ..." % (tid, framework, path), end="", flush=True)
            before_no = None
            if tid in CONSUMES_ROWS:
                before_no = replenish(conn, args.dbms)
            r = run_path(mk, args.concurrency, args.duration, args.warmup,
                         args.seed + n * 101)
            if tid in CONSUMES_ROWS:
                after_no = new_order_count(conn)
                r["note"] = ((r["note"] + " | " if r["note"] else "")
                             + "new_order %d -> %d" % (before_no, after_no))
                # Below ~1 row per (warehouse, district) there is nothing left to
                # deliver and the rest of the window measured an empty table.
                if after_no < cfg.WAREHOUSES * cfg.DISTRICTS_PER_WAREHOUSE:
                    r["note"] += " | INVALID: starved, ran out of new_order rows"
                    print("  STARVED", end="")
            print("  %8.1f QPM   %d committed, %d aborted (%.1f%%)"
                  % (r["qpm"], r["committed"], r["aborted"], r["abort_pct"]))
            if r["note"]:
                # "note", not "first errors". The note field carries the
                # new_order row-count drift that Delivery necessarily causes,
                # and printing that under an errors heading makes every healthy
                # run look like it failed - 120 rows of "first errors:
                # new_order 452849 -> 445899" on a curve with zero aborts.
                print("      note: %s" % r["note"])
            row = {
                "benchmark": "tpcc", "dbms": args.dbms,
                "schema_config": args.schema, "transaction_id": tid,
                "name": name, "framework": framework, "path": path,
                "concurrency": args.concurrency, "duration_s": args.duration,
                **r,
            }
            rows.append(row)
            # Appended now rather than at the end of the run. A path costs 70
            # seconds and a full run twenty of them; buffering the lot in memory
            # and writing once meant that interrupting the run - which is what
            # you do the moment you notice something is wrong with it - threw
            # away every completed measurement. Twelve valid paths were lost
            # that way before this line existed.
            append_rows(args.out, [row])

    print("\n  wrote %d rows to %s" % (len(rows), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
