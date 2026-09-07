#!/usr/bin/env python3
"""Stream selected TPC-H tables from DuckDB into PostgreSQL with COPY.

Takes a table list, because a query only needs the tables it references. Q11
reads PARTSUPP, SUPPLIER and NATION and nothing else, so re-measuring it costs
about two minutes of loading rather than the hour a full SF10 load takes. The
plan PostgreSQL produces for Q11 is identical either way — the other five tables
are never named in the statement.

    python3 load_pg.py --tables partsupp,supplier,nation
    python3 load_pg.py                       # all eight
"""
import argparse, io, os, sys, time

import duckdb
import psycopg2

# Derived from this file's own location so the script runs from a clone at any
# path; the default was /home/claude/bench/tpch10.duckdb, the sandbox path.
DEFAULT_DUCKDB = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")),
    "tpch10.duckdb")

DSN = os.environ.get("PG_DSN",
                     "host=127.0.0.1 port=55432 dbname=tpch user=postgres password=bench")

ORDER = ["region", "nation", "supplier", "customer", "part",
         "partsupp", "orders", "lineitem"]


def copy_table(duck, pg, table, batch=200_000):
    cur = duck.execute("SELECT * FROM %s" % table)
    n, t0 = 0, time.perf_counter()
    with pg.cursor() as c:
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            buf = io.StringIO()
            for r in rows:
                buf.write("\t".join("\\N" if v is None else str(v) for v in r))
                buf.write("\n")
            buf.seek(0)
            c.copy_expert("COPY %s FROM STDIN WITH (FORMAT text)" % table, buf)
            n += len(rows)
    pg.commit()
    print("  %s: %s rows in %.0fs"
          % (table, format(n, ","), time.perf_counter() - t0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default=DEFAULT_DUCKDB)
    ap.add_argument("--tables", default="")
    args = ap.parse_args()

    want = ([t.strip() for t in args.tables.split(",")] if args.tables else ORDER)
    duck = duckdb.connect(args.duckdb, read_only=True)
    pg = psycopg2.connect(DSN)
    for t in ORDER:
        if t in want:
            copy_table(duck, pg, t)
    with pg.cursor() as c:
        c.execute("ANALYZE")
    pg.commit()
    pg.close()
    duck.close()
    print("loaded:", ", ".join(t for t in ORDER if t in want))
    return 0


if __name__ == "__main__":
    sys.exit(main())
