#!/usr/bin/env python3
"""Run and measure ONE TPC-H query, append the result, exit.

Designed for a long campaign where a single configuration can run for hours and
an all-or-nothing script is a liability. Each invocation:

  * measures one query for one DBMS and one schema configuration,
  * appends a row to the results CSV immediately, so nothing is lost if a later
    query hangs or the machine reboots,
  * enforces a server-side statement timeout, so a pathological query is
    recorded as a timeout instead of taking the campaign with it,
  * prints each repetition as it completes.

Usage:
    python3 run_query.py --query 10 --dbms postgresql --schema indexed \
        --repetitions 9 --timeout 3600 --out results/corrected/pg_indexed.csv

    # skip if this configuration is already recorded
    python3 run_query.py --query 10 ... --resume
"""

import argparse, csv, os, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django

django.setup()
from django.db import connections

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DSN = os.environ.get(
    "SA_DSN", "postgresql+psycopg2://postgres:bench@127.0.0.1:55432/tpch"
)

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")
)
import results_paths  # noqa: E402

# Raises if TPCH_SF is unset rather than assuming 10, which would write SF1
# measurements into the completed SF10 campaign's files.
SCALE_FACTOR = results_paths.scale_factor()

BANDS = {
    **{q: "Simple" for q in (6, 14, 19)},
    **{q: "Medium" for q in (1, 3, 4, 11, 12, 16)},
    **{q: "Complex" for q in (2, 5, 7, 10, 13, 15, 17, 18, 20)},
    **{q: "Very Complex" for q in (8, 9, 21, 22)},
}

FIELDS = [
    "benchmark",
    "query_id",
    "band",
    "dbms",
    "schema_config",
    "framework",
    "path",
    "median_s",
    "min_s",
    "max_s",
    "cv_pct",
    "rows_returned",
    "repetitions_measured",
    "status",
    "note",
    "scale_factor",
]

# scale_factor is last so that appending to a file written before it existed
# keeps every earlier column in its original position. It is written because a
# measurement row's key - (dbms, schema_config, query_id, framework, path) -
# does not contain the scale factor, so a row is not self-describing without
# it: an SF1 row and an SF10 row for the same cell are indistinguishable once
# separated from their directory. The SF10 files predate this column, which is
# why scripts/utils/results_paths.py separates the campaigns by path as well.


def already_done(path, qid, dbms, schema):
    if not os.path.exists(path):
        return False
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if (
                row["query_id"] == qid
                and row["dbms"] == dbms
                and row["schema_config"] == schema
            ):
                return True
    return False


def append(path, rows):
    """Append rows, honouring the header the file already has.

    A file written before a column existed keeps its own header: writing FIELDS
    into it would put every value one position left of its heading from that
    row on, which reads as data rather than as corruption. Columns that the
    existing header cannot hold are reported rather than dropped in silence.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header, write_header = FIELDS, True
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, newline="") as fh:
            existing = next(csv.reader(fh), None)
        if existing:
            header, write_header = existing, False
            dropped = [
                c
                for c in FIELDS
                if c not in header and any(str(r.get(c, "")) != "" for r in rows)
            ]
            if dropped:
                print(
                    f"  note: {os.path.basename(path)} predates "
                    f"{', '.join(dropped)}; those values are not recorded in "
                    f"it. A new file gets the full header."
                )
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerows(rows)


def set_timeouts(seconds, dj_conn, sa_session, dbms):
    """Ask the server to abort a statement that exceeds the budget."""
    if not seconds:
        return
    ms = int(seconds * 1000)

    if dbms == "oracle":
        # Django connects lazily. In a fresh process dj_conn.connection is still
        # None here, so the deadline silently landed on nothing and the Django
        # paths ran unbounded - Q17 overran a 900 s ceiling by 20 minutes before
        # this showed up. Force the connection open first.
        dj_conn.ensure_connection()
        # Oracle's server-side equivalent is a Resource Manager plan, which
        # needs DBA rights the benchmark user does not have. python-oracledb
        # exposes a round-trip deadline on the connection instead, which is
        # enough to stop one pathological query taking the campaign with it.
        for raw in (
            getattr(dj_conn, "connection", None),
            sa_session.connection().connection.dbapi_connection,
        ):
            try:
                raw.call_timeout = ms
            except Exception:
                pass
        return

    if dbms in ("mssql", "sqlserver"):
        # SQL Server has no session-level statement timeout to SET; the ceiling
        # is a client-side one on the ODBC connection. This branch used to be
        # `None` with a comment saying so and nothing that acted on it, which
        # left the two frameworks bounded differently: Django picks up
        # OPTIONS["query_timeout"] from settings_sqlserver.py, SQLAlchemy is
        # built from SA_DSN and picked up nothing, so the ORM path under
        # comparison could run unbounded while its own SQL baseline was cut off
        # at the budget. Set it on both raw connections, as the Oracle branch
        # above does, so the ceiling is a property of the campaign rather than
        # of which framework happens to be running.
        dj_conn.ensure_connection()
        for raw in (
            getattr(dj_conn, "connection", None),
            sa_session.connection().connection.dbapi_connection,
        ):
            try:
                raw.timeout = int(seconds)  # pyodbc, whole seconds
            except Exception:
                pass
        return

    stmt = {
        "postgresql": f"SET statement_timeout = {ms}",
        "mysql": f"SET SESSION max_execution_time = {ms}",
    }.get(dbms)
    if not stmt:
        return
    with dj_conn.cursor() as c:
        c.execute(stmt)
    from sqlalchemy import text

    sa_session.execute(text(stmt))


def measure(label, fn, reps, timeout, cleanup=None, **kw):
    """Run fn reps times; discard the first; report live.

    On failure the caller-supplied `cleanup` rolls the connection back. Without
    it a failed statement leaves the session in an aborted transaction and every
    subsequent path reports 'current transaction is aborted', which is a
    contaminated measurement rather than a real one.
    """
    times, rows, status, note = [], None, "ok", ""
    for i in range(reps):
        t0 = time.perf_counter()
        try:
            rows = fn(**kw)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            status, note = (
                "timeout" if timeout and elapsed >= timeout * 0.9 else "error",
                f"{type(e).__name__}: {str(e)[:120]}",
            )
            print(f"    {label} rep {i}: {status} after {elapsed:.1f}s  {note}")
            if cleanup:
                try:
                    cleanup()
                except Exception:
                    pass
            return None, rows, times, status, note
        dt = time.perf_counter() - t0
        kind = "warmup " if i == 0 else f"rep {i}  "
        print(f"    {label} {kind}: {dt:9.3f}s")
        if i:
            times.append(dt)
    return statistics.median(times) if times else None, rows, times, status, note


def cv(xs):
    if len(xs) < 2:
        return 0.0
    m = statistics.mean(xs)
    return round(statistics.stdev(xs) / m * 100, 1) if m else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", type=int, required=True)
    ap.add_argument("--dbms", default="postgresql")
    ap.add_argument("--schema", default="indexed", choices=["indexed", "non-indexed"])
    ap.add_argument(
        "--repetitions",
        type=int,
        default=9,
        help="total runs; the first is a discarded warmup",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=0,
        help="server-side statement timeout in seconds, 0 to disable",
    )
    ap.add_argument(
        "--out",
        default="",
        help="measurement CSV to append to. Default: the "
        "measurements directory for this TPCH_SF, named "
        "<dbms>_<schema>.csv — results/corrected/measurements "
        "at SF10, results/sf<N>/measurements otherwise. The "
        "old default was a bare results_by_query.csv in the "
        "working directory, which put a campaign's output "
        "wherever it happened to be launched from.",
    )
    ap.add_argument(
        "--only",
        default="",
        help="measure only these paths, comma-separated as "
        "framework/path (django/sql, django/orm, sqlalchemy/sql, "
        "sqlalchemy/orm). Default: all four. For resuming a run "
        "that lost some paths to something external - a stopped "
        "container, a killed session - without paying for the "
        "paths that already completed. The protocol is unchanged: "
        "the same repetitions, the same warmup discard, the same "
        "timeout, in the same order. A partial run's rows are "
        "appended like any other, so the measurement file can end "
        "up holding two runs of one cell; the later rows win when "
        "make_all_results.py reads them, and both stay visible.",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="exit immediately if this configuration is already in --out",
    )
    args = ap.parse_args()

    if not args.out:
        args.out = os.path.join(
            results_paths.measurements_dir(SCALE_FACTOR),
            f"{args.dbms}_{args.schema.replace('-', '_')}.csv",
        )

    n, qid = args.query, f"Q{args.query:02d}"
    if args.resume and already_done(args.out, qid, args.dbms, args.schema):
        print(f"{qid} {args.dbms} {args.schema}: already recorded, skipping")
        return 0

    print(
        f"\n=== {qid} ({BANDS[n]})  {args.dbms}  {args.schema}  "
        f"{args.repetitions - 1} measured reps ==="
    )

    from django_app.queries import get_query_module_for_db

    dj = get_query_module_for_db(n, args.dbms)
    sa = __import__(f"sqlalchemy_app.queries.q{n:02d}", fromlist=["x"])

    conn = connections["default"]
    engine = create_engine(DSN, future=True)
    sess = sessionmaker(bind=engine, future=True)()

    out = []
    try:
        set_timeouts(args.timeout, conn, sess, args.dbms)

        specs = [
            ("django", "sql", dj.run_query_sql, {"connection": conn}),
            ("django", "orm", dj.run_query_orm, {"using": "default"}),
            ("sqlalchemy", "sql", sa.run_query_sql, {"session": sess}),
            ("sqlalchemy", "orm", sa.run_query_orm, {"session": sess}),
        ]
        if args.only:
            want = {s.strip() for s in args.only.split(",") if s.strip()}
            unknown = want - {f"{f}/{p}" for f, p, _fn, _kw in specs}
            if unknown:
                print(f"unknown path(s): {', '.join(sorted(unknown))}", file=sys.stderr)
                return 2
            specs = [s for s in specs if f"{s[0]}/{s[1]}" in want]
            print(
                f"  measuring only: {', '.join(f'{f}/{p}' for f, p, _fn, _kw in specs)}"
            )

        for fw, path, fn, kw in specs:
            key = list(kw)[0]
            call = (
                (lambda _f=fn, _k=key, _v=list(kw.values())[0]: _f(**{_k: _v}))
                if key != "connection"
                else (lambda _f=fn, _v=conn: _f(_v))
            )

            def _cleanup(_fw=fw):
                if _fw == "sqlalchemy":
                    sess.rollback()
                else:
                    conn.rollback()
                # a rollback drops the session-level statement_timeout
                set_timeouts(args.timeout, conn, sess, args.dbms)

            med, rows, times, status, note = measure(
                f"{fw}/{path}",
                lambda **_: call(),
                args.repetitions,
                args.timeout,
                cleanup=_cleanup,
            )
            out.append(
                {
                    "benchmark": "tpch",
                    "query_id": qid,
                    "band": BANDS[n],
                    "dbms": args.dbms,
                    "schema_config": args.schema,
                    "framework": fw,
                    "path": path,
                    "scale_factor": SCALE_FACTOR,
                    "median_s": round(med, 4) if med is not None else "",
                    "min_s": round(min(times), 4) if times else "",
                    "max_s": round(max(times), 4) if times else "",
                    "cv_pct": cv(times),
                    "rows_returned": len(rows)
                    if isinstance(rows, list)
                    else ("" if rows is None else 1),
                    "repetitions_measured": len(times),
                    "status": status,
                    "note": note,
                }
            )
            # A failure in one path says nothing about the other three. The
            # earlier version broke out here, which meant a single Django SQL
            # timeout discarded both SQLAlchemy measurements for that query and
            # left holes in the design grid.
            if status != "ok":
                continue
    finally:
        sess.close()

    append(args.out, out)

    by = {(r["framework"], r["path"]): r for r in out}
    for fw in ("django", "sqlalchemy"):
        s, o = by.get((fw, "sql")), by.get((fw, "orm"))
        if s and o and s["median_s"] != "" and o["median_s"] != "":
            oh = (o["median_s"] - s["median_s"]) / s["median_s"] * 100
            print(
                f"  {fw:11s} sql {s['median_s']:8.3f}s  orm {o['median_s']:8.3f}s  "
                f"overhead {oh:+7.1f}%  rows {o['rows_returned']}"
            )
    print(f"  appended {len(out)} rows to {args.out}")
    return 0 if all(r["status"] == "ok" for r in out) else 1


if __name__ == "__main__":
    sys.exit(main())
