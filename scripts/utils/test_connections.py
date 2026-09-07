#!/usr/bin/env python3
"""Check that both frameworks can reach the database under test.

This file exists because it was missing. `scripts/utils/test_connections.py` was
committed as a symbolic link to `utilities/test_connections.py`, a path that has
never existed in any commit in this repository. Three of the top-level entry
points call it:

    run_reproducibility.sh     gates the whole run on it and exits 1 on failure
    setup_reproducibility.sh   runs it as the final setup verification
    validate_reproducibility.sh  runs it if the file is present

so `./run_reproducibility.sh` has always stopped at "Database connection failed"
regardless of whether the databases were up.

What it checks:

  1. Django's `default` connection answers a trivial query. That is the
     connection `run_query.py` and `validate_queries.py` measure through — they
     use `connections["default"]`, not an alias named after the vendor — so it is
     the one that has to work.
  2. The SQLAlchemy engine built from SA_DSN answers the same query.
  3. Both point at the same host, port and database name.

The third check is the one worth having. Nothing else in the harness can detect
the two frameworks connecting to different databases: each would report perfectly
consistent timings, the validation harness compares results between them and
would report a mismatch as a wrong answer rather than a wrong target, and the
overhead column would be the difference between two machines. It is a
configuration mistake that looks like a finding.

Usage:
    python3 scripts/utils/test_connections.py
    python3 scripts/utils/test_connections.py --counts   # also report row counts

Environment: DJANGO_SETTINGS_MODULE, SA_DSN. Exits non-zero if any check fails.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")

TABLES = ["region", "nation", "supplier", "customer",
          "part", "partsupp", "orders", "lineitem"]

# TPC-H cardinalities are a fixed multiple of the scale factor, except nation and
# region which are constant. Used only when --counts is given.
PER_SF = {"supplier": 10_000, "customer": 150_000, "part": 200_000,
          "partsupp": 800_000, "orders": 1_500_000, "lineitem": 6_001_215}
CONSTANT = {"nation": 25, "region": 5}


def probe_sql(vendor):
    """The most trivial statement each vendor accepts."""
    return "SELECT 1 FROM DUAL" if vendor == "oracle" else "SELECT 1"


def check_django():
    import django
    django.setup()
    from django.db import connections

    conn = connections["default"]
    with conn.cursor() as cur:
        cur.execute(probe_sql(conn.vendor))
        cur.fetchone()
    d = conn.settings_dict
    where = (d.get("HOST") or "localhost", str(d.get("PORT") or ""), d.get("NAME") or "")
    print(f"  django      ok   {conn.vendor:<10s} {where[0]}:{where[1]}/{where[2]}")
    return conn, where


def check_sqlalchemy():
    from sqlalchemy import create_engine, text

    dsn = os.environ.get("SA_DSN")
    if not dsn:
        print("  sqlalchemy  SKIP SA_DSN is not set")
        return None, None
    engine = create_engine(dsn, future=True)
    with engine.connect() as c:
        c.execute(text(probe_sql(engine.dialect.name)))
    u = engine.url
    where = (u.host or "localhost", str(u.port or ""), u.database or "")
    print(f"  sqlalchemy  ok   {engine.dialect.name:<10s} {where[0]}:{where[1]}/{where[2]}")
    return engine, where


def same_target(a, b):
    """Compare host/port/database, tolerating localhost spellings.

    Oracle carries its target in the service name rather than the database slot,
    so the database component is compared only when both sides supply one.
    """
    loopback = {"localhost", "127.0.0.1", ""}
    host_ok = a[0] == b[0] or (a[0] in loopback and b[0] in loopback)
    port_ok = a[1] == b[1]
    name_ok = (not a[2]) or (not b[2]) or a[2] == b[2]
    return host_ok and port_ok and name_ok


def report_counts(conn):
    sf = float(os.environ.get("TPCH_SF", "0") or 0)
    print("\n  table       rows" + ("        expected at SF%g" % sf if sf else ""))
    ok = True
    with conn.cursor() as cur:
        for t in TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                n = cur.fetchone()[0]
            except Exception as e:
                print(f"  {t:<11s} -            {type(e).__name__}")
                ok = False
                continue
            note = ""
            if sf:
                want = CONSTANT.get(t) or int(PER_SF[t] * sf)
                # lineitem is the one table whose cardinality is not exact - the
                # specification allows 1 to 7 line items per order.
                exact = t != "lineitem"
                if (exact and n != want) or (not exact and abs(n - want) > want * 0.02):
                    note = f"  MISMATCH, expected {want:,}"
                    ok = False
                else:
                    note = f"  {want:,}"
            print(f"  {t:<11s} {n:<12,}{note}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", action="store_true",
                    help="also report row counts, checked against TPCH_SF if set")
    args = ap.parse_args()

    print(f"settings: {os.environ['DJANGO_SETTINGS_MODULE']}")

    try:
        conn, dj_where = check_django()
    except Exception as e:
        print(f"  django      FAIL {type(e).__name__}: {str(e)[:150]}")
        return 1

    try:
        _, sa_where = check_sqlalchemy()
    except Exception as e:
        print(f"  sqlalchemy  FAIL {type(e).__name__}: {str(e)[:150]}")
        return 1

    if sa_where and not same_target(dj_where, sa_where):
        print("\n  FAIL the two frameworks are pointed at different databases:")
        print(f"       django     {dj_where[0]}:{dj_where[1]}/{dj_where[2]}")
        print(f"       sqlalchemy {sa_where[0]}:{sa_where[1]}/{sa_where[2]}")
        print("       Every measurement taken like this compares two databases,"
              " not two frameworks.")
        return 1

    if args.counts and not report_counts(conn):
        return 1

    print("\nok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
