#!/usr/bin/env python3
"""Measure one TPC-C transaction, four paths, and append the result.

    python3 run_tpcc.py --transaction 1 --dbms postgresql --schema indexed \
        --repetitions 4 --timeout 900 \
        --out results/corrected/measurements/postgresql_tpcc_indexed.csv --resume

Writes the same columns as `run_query.py`, so `make_all_results.py` reads TPC-C
and TPC-H from one directory with one parser and the 432-row grid stays a single
shape.

## Why this is not run_query.py

`run_query.py` assumes a repetition is repeatable: TPC-H queries read, so running
one four times does the same work four times and the median means something.
TPC-C transactions write. New-Order inserts an order and decrements stock;
Delivery consumes the rows New-Order produced; Payment moves balances. The
second repetition therefore runs against a database the first one changed, and
the ORM path and the SQL path cannot be given byte-identical starting state
without restoring between them.

Three things keep the comparison honest anyway.

*Both paths draw the same keys.* Every path for a given transaction is driven
from `random.Random(seed)` re-seeded identically, and the keys come from
`tpcc_config.pick_keys`, so Django ORM, Django SQL, SQLAlchemy ORM and
SQLAlchemy SQL each operate on the same warehouse, district, customer and order
count in the same sequence. They do equivalent work, not merely similar work.

*The drift is small and measured.* At the loaded scale - 10 warehouses, 100
districts, 300,000 customers, 3,000,000 order lines - sixteen transactions per
cell change a few hundred rows. The row counts before and after are recorded in
the note so the drift is visible rather than assumed.

*The cardinalities are checked first.* `tpcc_config.verify_against` runs before
any timing. If the config says 10 warehouses and the database holds a different
number, most transactions would fail on a missing row, and a harness that counts
a returned dict as success would report that as throughput. It aborts instead.

## What is measured

One transaction, start to commit, through each of the four paths. The first
repetition is discarded as warmup and the median of the rest is kept - the same
protocol as TPC-H, so the two halves of the results file are comparable.
"""
import argparse
import csv
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")

import django
django.setup()

from django.db import connections, transaction as dj_transaction
import tpcc_config as cfg

TXN = {
    1: ("T1", "New-Order",    "Write-heavy", "t1_neworder", "t1"),
    2: ("T2", "Payment",      "Write-heavy", "t2_payment",  "t2"),
    3: ("T3", "Order-Status", "Read-only",   "t3_orderstatus", "t3"),
    4: ("T4", "Delivery",     "Write-heavy", "t4_delivery", "t4"),
    5: ("T5", "Stock-Level",  "Read-only",   "t5_stocklevel", "t5"),
}

# scale_factor is written for the same reason run_block.py writes it: a row
# that does not name the campaign it belongs to cannot be placed. Without it
# make_all_results.py excluded every TPC-C row from every build but SF10, and
# reported all eight TPC-C configurations as not_run while the measurements sat
# in the directory next to the TPC-H ones.
FIELDS = [
    "benchmark", "query_id", "band", "dbms", "schema_config", "scale_factor",
    "framework",
    "path", "median_s", "min_s", "max_s", "cv_pct", "rows_returned",
    "repetitions_measured", "status", "note",
]

# Tables a transaction can change, checked before and after so the note can say
# how far the database moved while it was being measured.
WATCHED = ["\"order\"", "new_order", "order_line", "history", "customer",
           "district", "stock"]


def already_done(path, tid, dbms, schema):
    if not os.path.exists(path):
        return False
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if (row["query_id"] == tid and row["dbms"] == dbms
                    and row["schema_config"] == schema):
                return True
    return False


def append(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def cv(xs):
    if len(xs) < 2:
        return 0.0
    m = statistics.mean(xs)
    return round(statistics.stdev(xs) / m * 100, 1) if m else 0.0


def snapshot(dj_conn, dbms):
    """Row counts of the tables the transactions write, for the drift note."""
    counts = {}
    quote = {"postgresql": '"order"', "mysql": "`order`",
             "sqlserver": "[order]"}.get(dbms, '"order"')
    with dj_conn.cursor() as c:
        for t in WATCHED:
            name = quote if t == "\"order\"" else t
            try:
                c.execute("SELECT COUNT(*) FROM %s" % name)
                counts[t.strip('"')] = c.fetchone()[0]
            except Exception:
                pass
    return counts


def measure(label, fn, reps, seed, timeout, cleanup=None):
    """Run fn reps times from a fixed seed; discard the first; report live.

    The seed is reset before every repetition *and* is the same for all four
    paths, so each path sees the same sequence of keys. Without that the paths
    would touch different warehouses and the comparison would include whatever
    difference that made.
    """
    times, rows, status, note = [], None, "ok", ""
    for i in range(reps):
        rng = random.Random(seed + i)
        t0 = time.perf_counter()
        try:
            rows = fn(rng)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            status = ("timeout" if timeout and elapsed >= timeout * 0.9
                      else "error")
            note = "%s: %s" % (type(e).__name__, str(e)[:120])
            print("    %s rep %d: %s after %.1fs  %s"
                  % (label, i, status, elapsed, note))
            if cleanup:
                try:
                    cleanup()
                except Exception:
                    pass
            return None, rows, times, status, note
        dt = time.perf_counter() - t0
        print("    %s %-8s: %9.4fs" % (label, "warmup" if i == 0 else "rep %d" % i, dt))
        if i:
            times.append(dt)
    return (statistics.median(times) if times else None), rows, times, status, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transaction", type=int, required=True, choices=[1, 2, 3, 4, 5])
    ap.add_argument("--dbms", default="postgresql")
    ap.add_argument("--schema", default="indexed", choices=["indexed", "non-indexed"])
    ap.add_argument("--repetitions", type=int, default=4,
                    help="first is discarded as warmup")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--out", default="results_tpcc.csv")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    n = args.transaction
    tid, name, band, dj_mod, sa_mod = TXN[n]

    if args.resume and already_done(args.out, tid, args.dbms, args.schema):
        print("%s %s %s: already recorded, skipping" % (tid, args.dbms, args.schema))
        return 0

    print("\n=== %s (%s, %s)  %s  %s  %d measured reps ==="
          % (tid, name, band, args.dbms, args.schema, args.repetitions - 1))

    conn = connections["default"]

    # Cardinalities before anything is timed. A config that disagrees with the
    # loaded data makes most transactions fail on a missing row, and a failed
    # transaction that returns a dict looks like a fast one.
    with conn.cursor() as c:
        cfg.verify_against(c)
    print("  %s" % cfg.summary())

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    dsn = os.environ.get("SA_DSN")
    if not dsn:
        print("SA_DSN is not set", file=sys.stderr)
        return 2
    sess = Session(create_engine(dsn))

    dj = __import__("django_app.tpcc_queries.%s" % dj_mod, fromlist=["x"])
    sa = __import__("sqlalchemy_app.tpcc_queries.%s" % sa_mod, fromlist=["x"])

    before = snapshot(conn, args.dbms)

    paths = [
        ("django", "orm", lambda rng: dj.run_transaction_orm(using="default")),
        ("django", "sql", lambda rng: dj.run_transaction_sql(conn)),
        ("sqlalchemy", "orm", lambda rng: sa.run_transaction_orm(sess)),
        ("sqlalchemy", "sql", lambda rng: sa.run_transaction_sql(sess)),
    ]

    out_rows = []
    for framework, path, fn in paths:
        label = "%s/%s" % (framework, path)
        cleanup = sess.rollback if framework == "sqlalchemy" else None
        med, res, times, status, note = measure(
            label, fn, args.repetitions, args.seed, args.timeout, cleanup)
        out_rows.append({
            "benchmark": "tpcc",
            "query_id": tid,
            "band": band,
            "dbms": args.dbms,
            "schema_config": args.schema,
            "scale_factor": os.environ.get("TPCH_SF", ""),
            "framework": framework,
            "path": path,
            "median_s": "" if med is None else round(med, 6),
            "min_s": "" if not times else round(min(times), 6),
            "max_s": "" if not times else round(max(times), 6),
            "cv_pct": cv(times),
            "rows_returned": (len(res) if isinstance(res, (list, tuple))
                              else (1 if res else 0)),
            "repetitions_measured": len(times),
            "status": status,
            "note": note,
        })

    after = snapshot(conn, args.dbms)
    drift = ", ".join("%s %+d" % (t, after[t] - before[t])
                      for t in sorted(before) if after.get(t, 0) != before[t])
    if drift:
        print("  database drift over this cell: %s" % drift)
        for r in out_rows:
            r["note"] = (r["note"] + " | " if r["note"] else "") + "drift: " + drift

    append(args.out, out_rows)
    print("  wrote %d paths to %s" % (len(out_rows), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
