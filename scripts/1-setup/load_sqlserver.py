#!/usr/bin/env python3
"""Stream TPC-H tables from DuckDB into SQL Server.

Same shape as load_pg.py and load_mysql.py: takes a table list, because a query
only needs the tables it references, and a targeted reload costs minutes rather
than the hours a full SF10 load takes.

The two scripts already in the repository for this vendor cannot do it.
load_sqlserver_data.sql runs BULK INSERT against /tpch-data/*.tbl.clean, and
setup_sqlserver_data.py reads the same .tbl files with the csv module; data/tpch-raw
is empty and gitignored, because the pipeline moved to generating the dataset
with DuckDB's tpch extension and streaming it in without an intermediate copy.
Writing the .tbl files back out to satisfy BULK INSERT would cost about 10 GB of
scratch and a second full pass over the data.

So this uses pyodbc executemany with fast_executemany, which turns N round trips
into one parameter-array call and is the difference between a load that finishes
and one that does not. Measured against this server, inserting SUPPLIER rows:

    fast_executemany = False     1,076 rows/s
    fast_executemany = True     21,116 rows/s

which is the difference between LINEITEM taking sixteen hours and taking about
three quarters of one.

    python3 load_sqlserver.py --tables partsupp,supplier,nation
    python3 load_sqlserver.py                       # all eight
"""

import argparse, os, sys, time

import duckdb
import pyodbc

# Derived from this file's own location so the script runs from a clone at any
# path, matching load_pg.py and load_mysql.py.
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


def odbc_driver():
    """The newest installed SQL Server ODBC driver, or an explicit override.

    Same discovery as settings_sqlserver.py, and for the same reason: this file
    would otherwise name a driver version the machine may not have, and the
    resulting error names a driver rather than a database, which is easy to
    misread as the server being down.
    """
    override = os.getenv("SQLSERVER_ODBC_DRIVER")
    if override:
        return override
    found = [d for d in pyodbc.drivers() if "SQL Server" in d]
    if not found:
        raise RuntimeError("no SQL Server ODBC driver installed")
    return max(found, key=lambda n: int("".join(c for c in n if c.isdigit()) or 0))


def connect():
    conn = pyodbc.connect(
        "DRIVER={%s};SERVER=%s,%s;DATABASE=%s;UID=%s;PWD=%s;TrustServerCertificate=yes"
        % (
            odbc_driver(),
            os.getenv("SQLSERVER_HOST", "127.0.0.1"),
            os.getenv("SQLSERVER_PORT", "1433"),
            os.getenv("SQLSERVER_DB", "tpch"),
            os.getenv("SQLSERVER_USER", "sa"),
            os.getenv("SQLSERVER_SA_PASSWORD", "YourStrong!Passw0rd"),
        ),
        autocommit=False,
    )
    return conn


def load(duck, cn, table, batch):
    cur = duck.execute("SELECT * FROM %s" % table)
    ins = cn.cursor()
    # Without this every row in the batch is a separate round trip and LINEITEM
    # alone would take most of a day. See the module docstring for the measured
    # difference.
    ins.fast_executemany = True
    stmt = "INSERT INTO %s VALUES (%s)" % (table, ",".join(["?"] * NCOLS[table]))
    n, t0, last = 0, time.perf_counter(), time.perf_counter()
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        # fast_executemany binds each parameter at the widest value it sees in
        # the batch, so it needs real sequences rather than DuckDB's row tuples
        # subclass; list() is enough and costs nothing next to the round trip.
        ins.executemany(stmt, [list(r) for r in rows])
        cn.commit()
        n += len(rows)
        if time.perf_counter() - last > 60:
            print(
                "    %s: %s rows  %.0f/s"
                % (table, format(n, ","), n / (time.perf_counter() - t0)),
                flush=True,
            )
            last = time.perf_counter()
    ins.close()
    print(
        "  %s: %s rows in %.0fs" % (table, format(n, ","), time.perf_counter() - t0),
        flush=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default=DEFAULT_DUCKDB)
    ap.add_argument("--tables", default="")
    ap.add_argument("--batch", type=int, default=20000)
    args = ap.parse_args()

    want = [t.strip() for t in args.tables.split(",")] if args.tables else ORDER
    duck = duckdb.connect(args.duckdb, read_only=True)
    cn = connect()
    for t in ORDER:
        if t in want:
            load(duck, cn, t, args.batch)

    # Statistics. PostgreSQL's ANALYZE and MySQL's ANALYZE TABLE are one call
    # that leaves the optimiser with a description of every column; SQL Server
    # needs two, and the obvious one on its own does nothing.
    #
    # UPDATE STATISTICS refreshes the statistics objects that already exist. A
    # table's objects come from its indexes, so LINEITEM - a heap with no index
    # in the non-indexed configuration - has none, and `UPDATE STATISTICS
    # lineitem WITH FULLSCAN` returned in under a second having refreshed
    # nothing. Verified directly rather than inferred: sys.stats reported
    # stats_objects = 0 for lineitem after the first version of this script ran,
    # against 6 for orders.
    #
    # That is the worst table in the benchmark to leave undescribed. Seventeen of
    # the twenty-two queries read LINEITEM, AUTO_CREATE_STATISTICS is ON, and the
    # optimiser would therefore have built *sampled* statistics for each column
    # during the first query that filtered on it - inside a timed repetition, and
    # for a different set of columns each time.
    #
    # sp_createstats creates a single-column statistics object on every column
    # that lacks one, which is the analogue of what ANALYZE gives PostgreSQL.
    # FULLSCAN on both calls because sampling at SF10 gives the date histograms
    # the TPC-H predicates depend on too coarsely.
    cur = cn.cursor()
    t0 = time.perf_counter()
    cur.execute("EXEC sp_createstats @fullscan = 'fullscan'")
    while cur.nextset():
        pass
    cn.commit()
    print("  sp_createstats: %.0fs" % (time.perf_counter() - t0), flush=True)
    for t in ORDER:
        if t in want:
            t0 = time.perf_counter()
            cur.execute("UPDATE STATISTICS %s WITH FULLSCAN" % t)
            cn.commit()
            print("  stats %s: %.0fs" % (t, time.perf_counter() - t0), flush=True)
    cur.close()

    # Prove it worked. The failure this replaces was silent and fast, which is
    # exactly the shape of thing this repository keeps finding too late.
    cur = cn.cursor()
    cur.execute("""SELECT t.name, COUNT(s.stats_id)
                     FROM sys.tables t
                     LEFT JOIN sys.stats s ON s.object_id = t.object_id
                    GROUP BY t.name ORDER BY t.name""")
    for name, k in cur.fetchall():
        if name in want and k == 0:
            raise RuntimeError("no statistics on %s after load" % name)
        print("  sys.stats %-9s %d objects" % (name, k), flush=True)
    cur.close()
    cn.close()
    duck.close()
    print("loaded:", ", ".join(t for t in ORDER if t in want))
    return 0


if __name__ == "__main__":
    sys.exit(main())
