#!/usr/bin/env python3
"""Stream TPC-H tables from DuckDB into MySQL.

Same shape as load_pg.py: takes a table list, because a query only needs the
tables it references, and a targeted reload costs minutes rather than an hour.

MySQL has no COPY, and LOAD DATA LOCAL INFILE needs a file on disk — 7.5 GB of
scratch for LINEITEM alone, which this sandbox does not have spare. So this uses
batched executemany with autocommit off, which on this dataset runs at roughly
the same rate as the Oracle loader.

    python3 load_mysql.py --tables partsupp,supplier,nation
    python3 load_mysql.py                       # all eight
"""

import argparse, os, sys, time

# MySQLdb MUST be imported before duckdb, and the order is load-bearing.
# duckdb's C++ runtime claims the static TLS block first, and libmysqlclient
# then cannot allocate any:
#     ImportError: /lib/x86_64-linux-gnu/libstdc++.so.6:
#     cannot allocate memory in static TLS block
# Measured: "import MySQLdb, duckdb" works, "import duckdb, MySQLdb" does not.
# LD_PRELOAD of libmysqlclient also fixes it, but that has to be remembered at
# every call site and this does not. Only this loader imports both; the timed
# paths never import duckdb.
import MySQLdb  # mysqlclient; one MySQL driver everywhere (C31)
import duckdb

# Derived from this file's own location so the script runs from a clone at any
# path; the default was a retired sandbox dataset, the sandbox path.
DEFAULT_DUCKDB = os.path.join(
    os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    ),
    "tpch10.duckdb",
)

ORDER = [
    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
]
NCOLS = {
    "region": 3,
    "nation": 4,
    "supplier": 7,
    "customer": 8,
    "part": 9,
    "partsupp": 5,
    "orders": 9,
    "lineitem": 16,
}


def connect():
    """Connection parameters from the environment, defaulting to the same
    values sqlalchemy_app/database.py uses.

    These were hardcoded to 127.0.0.1:33306 as root/bench, which was the
    container rig's mapping and nothing else's. load_pg.py has always taken
    PG_DSN; this one could not be pointed at a different server without
    editing it, which is how it came to disagree with the rest of the harness
    when MySQL moved to a native install on the standard port."""
    return MySQLdb.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "benchmark"),
        password=os.environ.get("MYSQL_PASSWORD", "benchmark_pass"),
        database=os.environ.get("MYSQL_DB", "tpch"),
        autocommit=False,
        local_infile=True,
    )


def load(duck, my, table, batch):
    cur = duck.execute("SELECT * FROM %s" % table)
    ins = my.cursor()
    stmt = "INSERT INTO %s VALUES (%s)" % (table, ",".join(["%s"] * NCOLS[table]))
    n, t0, last = 0, time.perf_counter(), time.perf_counter()
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        ins.executemany(stmt, rows)
        my.commit()
        n += len(rows)
        if time.perf_counter() - last > 60:
            print(
                "    %s: %s rows  %.0f/s"
                % (table, format(n, ","), n / (time.perf_counter() - t0))
            )
            last = time.perf_counter()
    ins.close()
    print("  %s: %s rows in %.0fs" % (table, format(n, ","), time.perf_counter() - t0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default=DEFAULT_DUCKDB)
    ap.add_argument("--tables", default="")
    ap.add_argument("--batch", type=int, default=20000)
    args = ap.parse_args()

    want = [t.strip() for t in args.tables.split(",")] if args.tables else ORDER
    duck = duckdb.connect(args.duckdb, read_only=True)
    my = connect()
    # The load is the only writer and the database is rebuilt from scratch if it
    # fails, so durability per batch buys nothing and costs a great deal.
    with my.cursor() as c:
        c.execute("SET SESSION unique_checks = 0")
        c.execute("SET SESSION foreign_key_checks = 0")
        c.execute("SET SESSION sql_log_bin = 0")
    for t in ORDER:
        if t in want:
            load(duck, my, t, args.batch)
    with my.cursor() as c:
        for t in ORDER:
            if t in want:
                c.execute("ANALYZE TABLE %s" % t)
    my.commit()
    my.close()
    duck.close()
    print("loaded:", ", ".join(t for t in ORDER if t in want))
    return 0


if __name__ == "__main__":
    sys.exit(main())
