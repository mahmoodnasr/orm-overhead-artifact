#!/usr/bin/env python3
"""Oracle working-set driver: hold only the tables a query group needs.

Oracle Free caps user data at 12 GB. TPC-H SF10 loads to 10.81 GB, so the
dataset fits and its indexes do not — not the secondary indexes of the indexed
configuration, and not even the primary keys the non-indexed configuration needs
for parity with PostgreSQL.

Most TPC-H queries read a fraction of the schema, so the way through is to hold
only the tables a query references and index those exactly as the PostgreSQL
configuration indexes them. A table that is absent is absent only because the
query never references it, so the comparison stays like for like.

The groups below are ordered so the resident table set only ever grows.
LINEITEM takes thirteen minutes to load and seventeen of the twenty-two queries
need it; ordering this way loads it once instead of seventeen times.

Usage:
    python3 oracle_groups.py --list
    python3 oracle_groups.py --group B --schema indexed
    python3 oracle_groups.py --group B --schema indexed --report-only
"""
import argparse, os, re, sys, time

import duckdb
import oracledb

# Derived from this file's own location so the script runs from a clone at any
# path; the default was /home/claude/bench/tpch10.duckdb, the sandbox path.
DEFAULT_DUCKDB = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")),
    "tpch10.duckdb")

DSN = os.environ.get("ORA_DSN", "127.0.0.1:41521/FREEPDB1")
USER = os.environ.get("ORA_USER", "tpch")
PASS = os.environ.get("ORA_PASS", "bench")
CAP_GB = 12.0

NCOLS = {"region": 3, "nation": 4, "supplier": 7, "customer": 8,
         "part": 9, "partsupp": 5, "orders": 9, "lineitem": 16}

# Loaded smallest first so a failure surfaces early and cheaply.
LOAD_ORDER = ["region", "nation", "supplier", "customer", "part",
              "partsupp", "orders", "lineitem"]

PK = {
    "region": "r_regionkey", "nation": "n_nationkey", "supplier": "s_suppkey",
    "customer": "c_custkey", "part": "p_partkey",
    "partsupp": "ps_partkey, ps_suppkey", "orders": "o_orderkey",
    "lineitem": "l_orderkey, l_linenumber",
}

# Exactly the secondary indexes in scripts/1-setup/postgres_indexes.sql.
SECONDARY = {
    "lineitem": [
        ("idx_lineitem_shipdate", "l_shipdate"),
        ("idx_lineitem_orderkey", "l_orderkey"),
        ("idx_lineitem_partkey", "l_partkey"),
        ("idx_lineitem_suppkey", "l_suppkey"),
        ("idx_lineitem_shipdate_discount_qty", "l_shipdate, l_discount, l_quantity"),
        ("idx_lineitem_shipmode_receiptdate",
         "l_shipmode, l_receiptdate, l_commitdate, l_shipdate"),
    ],
    "orders": [
        ("idx_orders_custkey", "o_custkey"),
        ("idx_orders_orderdate", "o_orderdate"),
        ("idx_orders_orderdate_custkey", "o_orderdate, o_custkey"),
    ],
    "partsupp": [
        ("idx_partsupp_partkey", "ps_partkey"),
        ("idx_partsupp_suppkey", "ps_suppkey"),
    ],
    "customer": [
        ("idx_customer_nationkey", "c_nationkey"),
        ("idx_customer_mktsegment", "c_mktsegment"),
    ],
    "supplier": [("idx_supplier_nationkey", "s_nationkey")],
    "nation": [("idx_nation_regionkey", "n_regionkey")],
}

TINY = ["region", "nation", "supplier"]      # under 20 MB together, always resident

# (name, tables, queries). Table sets grow monotonically from B onward.
GROUPS = [
    ("A", TINY + ["part", "partsupp", "customer", "orders"],
     [2, 11, 13, 16, 22]),
    ("B", TINY + ["lineitem"], [1, 6, 15]),
    ("C", TINY + ["lineitem", "part"], [14, 17, 19]),
    ("D", TINY + ["lineitem", "orders"], [4, 12]),
    ("E", TINY + ["lineitem", "orders", "customer"], [3, 10, 18]),
    ("F", TINY + ["lineitem", "orders", "customer", "part"], [5, 7, 8, 21]),
    ("G", TINY + ["lineitem", "orders", "customer", "part", "partsupp"], [9, 20]),
]


def connect():
    return oracledb.connect(user=USER, password=PASS, dsn=DSN)


def drop_index(ora, iname):
    """Drop one secondary index if it exists. True if it was there."""
    cur = ora.cursor()
    try:
        cur.execute("SELECT 1 FROM user_indexes WHERE index_name = :n",
                    {"n": iname.upper()})
        if cur.fetchone() is None:
            return False
        cur.execute("DROP INDEX %s" % iname)
        return True
    except Exception:
        return False
    finally:
        cur.close()


def resident(ora):
    with ora.cursor() as c:
        c.execute("SELECT table_name FROM user_tables")
        return {r[0].lower() for r in c}


def segments_gb(ora):
    with ora.cursor() as c:
        c.execute("SELECT NVL(SUM(bytes),0)/1024/1024/1024 FROM user_segments")
        return float(c.fetchone()[0])


def ddl_for(table):
    """The CREATE TABLE for one table, primary key stripped off."""
    sql = re.sub(r"^--.*$", "", open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "schema_oracle.sql")).read(), flags=re.M)
    for stmt in (s.strip() for s in sql.split(";") if s.strip()):
        if re.search(r"CREATE TABLE %s\b" % table, stmt, re.I):
            return re.sub(r",\s*CONSTRAINT pk_\w+ PRIMARY KEY \([^)]*\)", "", stmt)
    raise KeyError(table)


def drop(ora, table):
    with ora.cursor() as c:
        c.execute("DROP TABLE %s CASCADE CONSTRAINTS PURGE" % table)
    print(f"  dropped {table}")


# Set ORA_COMPRESS to a comma-separated table list to create those tables with
# ROW STORE COMPRESS ADVANCED. It exists for exactly one case: Q09 and Q20 need
# LINEITEM, ORDERS, CUSTOMER, PART and PARTSUPP resident together, which reaches
# 12.37 GB of data and raises ORA-12954 on the PARTSUPP primary key at 12.44 GB.
# There are no secondary indexes in the non-indexed configuration to trade away,
# so the only remaining lever is the table data itself.
#
# It must be ADVANCED, not BASIC. Basic compression applies only to direct-path
# inserts, and this loader uses the conventional path on purpose (batched
# APPEND_VALUES measured at 870 bytes per PARTSUPP row against a real width near
# 145). A table created COMPRESS BASIC and loaded conventionally is simply
# uncompressed, silently. Measured here on 50,000 identical rows: BASIC 3.00 MB,
# ADVANCED 0.69 MB.
#
# Compressed blocks change I/O volume and therefore plan costing, so a cell
# measured this way is not like-for-like with the rest of Oracle. Both the ORM
# and SQL arms of that cell read the same blocks, so the overhead ratio within
# it still holds.
COMPRESSED = {t.strip().lower() for t in os.environ.get("ORA_COMPRESS", "").split(",") if t.strip()}


def load(ora, duck, table, batch=50000):
    ddl = ddl_for(table)
    if table.lower() in COMPRESSED:
        ddl += " ROW STORE COMPRESS ADVANCED"
        print(f"  {table}: ROW STORE COMPRESS ADVANCED")
    with ora.cursor() as c:
        c.execute(ddl)
        c.execute("ALTER TABLE %s NOLOGGING" % table)
    cur = duck.execute("SELECT * FROM %s" % table)
    ins = ora.cursor()
    ins.prepare("INSERT INTO %s VALUES (%s)"
                % (table, ",".join(":%d" % (i + 1) for i in range(NCOLS[table]))))
    n, t0 = 0, time.perf_counter()
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        ins.executemany(None, rows)
        ora.commit()
        n += len(rows)
    ins.close()
    print(f"  loaded {table}: {n:,} rows in {time.perf_counter()-t0:.0f}s")


def build_index(ora, name, table, cols):
    """Return (ok, seconds, note). ORA-12954 is a cap failure, not an error."""
    t0 = time.perf_counter()
    try:
        with ora.cursor() as c:
            c.execute("CREATE INDEX %s ON %s (%s) NOLOGGING" % (name, table, cols))
        return True, time.perf_counter() - t0, ""
    except oracledb.DatabaseError as e:
        msg = str(e)
        if "ORA-00955" in msg:               # already there
            return True, 0.0, "exists"
        return False, time.perf_counter() - t0, msg.split("\n")[0][:110]


def build_pk(ora, table):
    t0 = time.perf_counter()
    try:
        with ora.cursor() as c:
            c.execute("ALTER TABLE %s ADD CONSTRAINT pk_%s PRIMARY KEY (%s)"
                      % (table, table, PK[table]))
        return True, time.perf_counter() - t0, ""
    except oracledb.DatabaseError as e:
        msg = str(e)
        if "ORA-02260" in msg or "ORA-00955" in msg:
            return True, 0.0, "exists"
        return False, time.perf_counter() - t0, msg.split("\n")[0][:110]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", help="group name, or 'all'")
    ap.add_argument("--schema", default="indexed",
                    choices=["indexed", "non-indexed"])
    ap.add_argument("--duckdb", default=DEFAULT_DUCKDB)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report-only", action="store_true",
                    help="print the resident set and size, change nothing")
    args = ap.parse_args()

    if args.list:
        for name, tables, queries in GROUPS:
            print(f"{name}  tables={','.join(tables):<60s} "
                  f"queries={','.join('Q%02d' % q for q in queries)}")
        return 0

    ora = connect()
    if args.report_only:
        print("resident:", ", ".join(sorted(resident(ora))))
        print("segments: %.2f GB of %.0f GB" % (segments_gb(ora), CAP_GB))
        return 0

    spec = next((g for g in GROUPS if g[0] == args.group.upper()), None)
    if spec is None:
        print(f"unknown group {args.group}", file=sys.stderr)
        return 2
    name, want, queries = spec
    want = set(want)

    print(f"=== group {name}  schema={args.schema} ===")
    print(f"  wants: {', '.join(sorted(want))}")

    have = resident(ora)
    for t in sorted(have - want):
        drop(ora, t)

    duck = duckdb.connect(args.duckdb, read_only=True)
    for t in LOAD_ORDER:
        if t in want and t not in have:
            load(ora, duck, t)
    duck.close()

    print(f"  data resident: {segments_gb(ora):.2f} GB")

    # Primary keys first: both configurations have them, and PostgreSQL's
    # non-indexed configuration is primary keys only.
    failures = []
    for t in LOAD_ORDER:
        if t not in want:
            continue
        ok, secs, note = build_pk(ora, t)
        if ok:
            if note != "exists":
                print(f"  pk_{t:<9s} built in {secs:.0f}s")
        else:
            failures.append(("pk_%s" % t, note))
            print(f"  pk_{t:<9s} FAILED  {note}")

    if args.schema == "indexed":
        for t in LOAD_ORDER:
            if t not in want:
                continue
            for iname, cols in SECONDARY.get(t, []):
                ok, secs, note = build_index(ora, iname, t, cols)
                if ok:
                    if note != "exists":
                        print(f"  {iname:<36s} built in {secs:.0f}s")
                else:
                    failures.append((iname, note))
                    print(f"  {iname:<36s} FAILED  {note}")
    else:
        # Drop them, rather than assume they were never built.
        #
        # This driver reuses whatever is already resident - that is the whole
        # point of the group ordering, so LINEITEM loads once instead of
        # seventeen times - so running `--schema indexed` and then
        # `--schema non-indexed` left all nine secondary indexes in place and
        # reported a total identical to the indexed one. Measured: 5.43 GB for
        # both configurations, and user_indexes still listing IDX_ORDERS_CUSTKEY
        # and the rest. Every "non-indexed" timing taken after an indexed run
        # would have been a second measurement of the indexed schema under the
        # wrong label.
        #
        # Nothing would have caught it downstream. The five validation checks
        # compare results, and an index changes how fast a query answers, not
        # what it answers.
        dropped = 0
        for t in LOAD_ORDER:
            if t not in want:
                continue
            for iname, _cols in SECONDARY.get(t, []):
                if drop_index(ora, iname):
                    dropped += 1
        print(f"  secondary indexes dropped: {dropped}")

    total = segments_gb(ora)
    print(f"  total resident: {total:.2f} GB of {CAP_GB:.0f} GB "
          f"({CAP_GB - total:+.2f} GB headroom)")

    if failures:
        print(f"  {len(failures)} structure(s) could not be built:")
        for n2, note in failures:
            print(f"    {n2}: {note}")
        print("  -> queries in this group are not comparable to the other systems")
        print("     and must be recorded as not_run with this shortfall.")

    print("  queries: " + ",".join("Q%02d" % q for q in queries))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
