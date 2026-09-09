#!/usr/bin/env python3
"""Load TPC-H SF10 into Oracle, streaming from DuckDB.

No intermediate CSV files. DuckDB's tpch extension generates the dataset into a
single compressed database file; each table is then read out in batches and fed
straight to Oracle with executemany. On a fixed disk allowance this matters: the
CSV route needs about 10 GB of scratch on top of both databases, and the
lineitem file alone is 7.5 GB.

Primary keys are added after the data is in place, so each index is built once
by a bulk sort rather than maintained row by row through 60 million inserts.

Usage:
    python3 load_oracle.py                   # tpch10.duckdb at the repository root
    python3 load_oracle.py --duckdb /path/to/tpch10.duckdb
    python3 load_oracle.py --tables lineitem --skip-constraints
"""

import argparse, os, sys, time

import duckdb
import oracledb

# Derived from this file's own location so the script runs from a clone at any
# path; the default was a retired sandbox dataset, the sandbox path.
DEFAULT_DUCKDB = os.path.join(
    os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    ),
    "tpch10.duckdb",
)

DSN = os.environ.get("ORA_DSN", "127.0.0.1:41521/FREEPDB1")
USER = os.environ.get("ORA_USER", "tpch")
PASS = os.environ.get("ORA_PASS", "bench")

# child tables first would break nothing here (no foreign keys are declared),
# but load small to large so a failure surfaces early and cheaply
TABLES = [
    ("region", 3),
    ("nation", 4),
    ("supplier", 7),
    ("customer", 8),
    ("part", 9),
    ("partsupp", 5),
    ("orders", 9),
    ("lineitem", 16),
]

PK = {
    "region": "r_regionkey",
    "nation": "n_nationkey",
    "supplier": "s_suppkey",
    "customer": "c_custkey",
    "part": "p_partkey",
    "partsupp": "ps_partkey, ps_suppkey",
    "orders": "o_orderkey",
    "lineitem": "l_orderkey, l_linenumber",
}


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def generate(path, sf):
    """Generate the dataset once, into a single DuckDB file."""
    if os.path.exists(path):
        print(f"reusing {path} ({human(os.path.getsize(path))})")
        return
    print(f"generating TPC-H SF{sf} into {path} ...")
    t0 = time.perf_counter()
    con = duckdb.connect(path)
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"CALL dbgen(sf={sf})")
    con.close()
    print(f"  done in {time.perf_counter() - t0:.0f}s, {human(os.path.getsize(path))}")


def load_table(duck, ora, table, ncols, batch):
    cur = duck.execute(f"SELECT * FROM {table}")
    ins = ora.cursor()
    # Conventional path, deliberately. The obvious optimisation here is
    # INSERT /*+ APPEND_VALUES */, and it is a trap when the data arrives in
    # batches: every executemany becomes its own direct-path load writing above
    # the segment high-water mark, so each batch leaves a partly filled tail and
    # claims fresh extents. Measured on this dataset it cost 870 bytes per
    # PARTSUPP row against a real row width near 145 - roughly six times the
    # space - and hit Oracle Free's 12 GB ceiling before LINEITEM had started.
    # Conventional inserts refill blocks and land in the expected footprint.
    ins.prepare(
        f"INSERT INTO {table} VALUES ("
        + ",".join(f":{i + 1}" for i in range(ncols))
        + ")"
    )
    total, t0, last = 0, time.perf_counter(), time.perf_counter()
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        ins.executemany(None, rows)
        ora.commit()
        total += len(rows)
        if time.perf_counter() - last > 30:
            rate = total / (time.perf_counter() - t0)
            print(f"    {table}: {total:,} rows  {rate:,.0f}/s")
            last = time.perf_counter()
    ins.close()
    print(f"  {table}: {total:,} rows in {time.perf_counter() - t0:.0f}s")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default=DEFAULT_DUCKDB)
    ap.add_argument("--sf", type=int, default=10)
    ap.add_argument("--batch", type=int, default=50000)
    ap.add_argument("--tables", default="", help="comma-separated subset")
    ap.add_argument("--skip-constraints", action="store_true")
    ap.add_argument("--constraints-only", action="store_true")
    args = ap.parse_args()

    want = (
        [t.strip() for t in args.tables.split(",")]
        if args.tables
        else [t for t, _ in TABLES]
    )

    generate(args.duckdb, args.sf)

    duck = duckdb.connect(args.duckdb, read_only=True)
    ora = oracledb.connect(user=USER, password=PASS, dsn=DSN)
    print(f"connected to {DSN} as {USER}")

    if not args.constraints_only:
        for table, ncols in TABLES:
            if table not in want:
                continue
            load_table(duck, ora, table, ncols, args.batch)

    if not args.skip_constraints:
        for table, _ in TABLES:
            if table not in want:
                continue
            cols = PK[table]
            t0 = time.perf_counter()
            try:
                with ora.cursor() as c:
                    c.execute(
                        f"ALTER TABLE {table} ADD CONSTRAINT pk_{table} "
                        f"PRIMARY KEY ({cols})"
                    )
                print(f"  pk_{table} built in {time.perf_counter() - t0:.0f}s")
            except oracledb.DatabaseError as e:
                print(f"  pk_{table}: {str(e)[:120]}")

    # ------------------------------------------------- what did it actually cost
    with ora.cursor() as c:
        c.execute("""SELECT segment_type, ROUND(SUM(bytes)/1024/1024/1024, 2)
                     FROM user_segments GROUP BY segment_type ORDER BY 2 DESC""")
        print("\nsegment sizes:")
        total = 0.0
        for stype, gb in c:
            print(f"  {stype:<16s} {gb:>6.2f} GB")
            total += gb
        print(
            f"  {'TOTAL':<16s} {total:>6.2f} GB   (Oracle Free caps user data at 12 GB)"
        )

        c.execute("SELECT COUNT(*) FROM lineitem")
        print(f"\nlineitem rows: {c.fetchone()[0]:,}")

    ora.close()
    duck.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
