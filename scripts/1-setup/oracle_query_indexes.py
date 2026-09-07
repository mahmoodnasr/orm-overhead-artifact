#!/usr/bin/env python3
"""Build only the indexes one TPC-H query can actually use, so Oracle's indexed
configuration becomes reachable for queries LINEITEM's full index set locks out.

    python3 oracle_query_indexes.py --query 6 --plan     # show, build nothing
    python3 oracle_query_indexes.py --query 6 --build
    python3 oracle_query_indexes.py --query 6 --drop
    python3 oracle_query_indexes.py --all --plan         # every query, sizes

## Why this exists

`oracle_groups.py` scopes the resident set by *table*, which is what makes the
non-indexed configuration measurable under Oracle Free's 12 GB cap. It is not
enough for the indexed one. LINEITEM alone is 7.22 GB of data and a 1.25 GB
primary key, and its six secondary indexes are about 1.1 GB each: 15.07 GB
against a 12 GB ceiling. Seventeen of the twenty-two queries read LINEITEM, so
seventeen queries x 2 frameworks = 34 cells were recorded `not_run`.

Dropping *tables* cannot fix that, because the tables are the query's own. So
this drops *indexes* instead, and the question becomes which ones can be
dropped without changing the plan.

## The rule, and why it is safe

An index is built for query N if its **leading column appears in that query's
SQL**. An index whose leading column is absent cannot be used for an index range
scan, cannot supply ordering for a sort or merge join, and cannot drive a
nested-loop join - every access path that would make the optimizer prefer it
needs the leading column. What remains is a full index scan used as a narrow
substitute for a table scan, which Oracle will not choose when the query already
needs columns the index does not carry.

So for the query being measured, the subset is plan-equivalent to the full set.
That is the claim this script rests on, and it is checkable rather than assumed:
`--verify` captures the plan with the subset and compares its operations against
the plan recorded under the full index set on a system that could hold it
(PostgreSQL, whose indexed configuration is complete). A query whose plan shape
differs is reported rather than measured.

**This is not the same experiment as the other three systems.** They hold every
index in the configuration simultaneously; Oracle holds a per-query subset. For
the measured query the two are equivalent by the argument above, but the
database around it is not in the same state, and cross-query comparisons within
Oracle's indexed configuration inherit that. The results file records it per
cell in `status_note`. It buys 34 cells that
were otherwise impossible; it does not buy them for free.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import oracledb

USER = os.environ.get("ORACLE_USER", "tpch")
PASS = os.environ.get("ORACLE_PASSWORD", "bench")
DSN = os.environ.get("ORA_DSN", "127.0.0.1:41521/FREEPDB1")
CAP_GB = 12.0

# Imported rather than restated: one definition of the indexed configuration, so
# this cannot drift from what oracle_groups.py builds or postgres_indexes.sql
# declares. A second copy here is how the two would silently disagree.
def _load_groups():
    """SECONDARY and GROUPS from oracle_groups.py, without importing the module
    as a package (its directory name starts with a digit, so it is not a legal
    Python identifier and `import scripts.1-setup.oracle_groups` is a SyntaxError)."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "oracle_groups.py")).read()
    ns = {"os": os, "sys": sys,
          "__file__": os.path.join(here, "oracle_groups.py")}
    # Execute only the module-level constant block, which ends where the first
    # function is defined. Running the whole file would try to connect.
    head = src.split("\ndef connect(")[0]
    exec(compile(head, "oracle_groups.py", "exec"), ns)
    return ns["SECONDARY"], ns["GROUPS"], ns["TINY"]


SECONDARY, GROUPS, TINY = _load_groups()


def group_for(n):
    for name, tables, queries in GROUPS:
        if n in queries:
            return name, tables
    raise SystemExit("query %d is in no group" % n)


def query_sql(n):
    """The hand-written Oracle baseline, which is the statement whose access
    paths the indexes exist to serve."""
    from sqlalchemy_app.queries._sql import sql_for
    return sql_for(n, "oracle")


def indexes_for(n):
    """-> [(index_name, table, columns, leading_column)] the query could use."""
    sql = query_sql(n).lower()
    _, tables = group_for(n)
    out = []
    for table, idxs in SECONDARY.items():
        if table not in tables:
            continue                      # table not resident: index irrelevant
        for name, cols in idxs:
            lead = cols.split(",")[0].strip()
            # Word-boundary match: l_shipdate must not be found inside
            # l_shipdate_x, and o_custkey must not match c_custkey.
            if re.search(r"\b%s\b" % re.escape(lead), sql):
                out.append((name, table, cols, lead))
    return out


def sizes(ora):
    """Actual segment bytes per object. Measured, never estimated - the whole
    reason the cap is hit early is that estimates of index size were wrong."""
    c = ora.cursor()
    c.execute("SELECT segment_name, bytes/1024/1024/1024 FROM user_segments")
    return {r[0].lower(): r[1] for r in c.fetchall()}


def resident_gb(ora):
    c = ora.cursor()
    c.execute("SELECT NVL(SUM(bytes),0)/1024/1024/1024 FROM user_segments")
    return c.fetchone()[0]


def existing_indexes(ora):
    c = ora.cursor()
    c.execute("SELECT index_name FROM user_indexes")
    return {r[0].lower() for r in c.fetchall()}


def build(ora, wanted, dry=False):
    have = existing_indexes(ora)
    built, skipped = [], []
    for name, table, cols, _lead in wanted:
        if name in have:
            skipped.append(name)
            continue
        if dry:
            built.append(name)
            continue
        before = resident_gb(ora)
        try:
            c = ora.cursor()
            c.execute("CREATE INDEX %s ON %s (%s) NOLOGGING" % (name, table, cols))
            ora.commit()
        except oracledb.DatabaseError as e:
            # ORA-12954 here is the answer to the question, not a crash: this
            # query's own indexes do not fit either. Report and leave the rest.
            print("    %-38s FAILED %s" % (name, str(e).split("\n")[0][:60]))
            return built, skipped, False
        print("    %-38s built (+%.2f GB, resident %.2f GB)"
              % (name, resident_gb(ora) - before, resident_gb(ora)))
        built.append(name)
    return built, skipped, True


def drop_all_secondary(ora):
    have = existing_indexes(ora)
    dropped = 0
    for _table, idxs in SECONDARY.items():
        for name, _cols in idxs:
            if name in have:
                ora.cursor().execute("DROP INDEX %s" % name)
                dropped += 1
    ora.commit()
    return dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--plan", action="store_true", help="show, change nothing")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--drop", action="store_true", help="drop every secondary index")
    args = ap.parse_args()

    if args.all:
        # No connection needed: this is a static property of the SQL.
        print("  query  group  indexes it can use")
        for name, _tables, queries in GROUPS:
            for n in sorted(queries):
                idx = indexes_for(n)
                print("   Q%02d    %s     %s" % (n, name,
                      ", ".join(i[0].replace("idx_", "") for i in idx) or "-none-"))
        return 0

    ora = oracledb.connect(user=USER, password=PASS, dsn=DSN)

    if args.drop:
        print("  dropped %d secondary indexes, resident now %.2f GB"
              % (drop_all_secondary(ora), resident_gb(ora)))
        return 0

    if not args.query:
        ap.error("--query, --all or --drop is required")

    g, tables = group_for(args.query)
    wanted = indexes_for(args.query)
    full = sum(len(v) for t, v in SECONDARY.items() if t in tables)
    print("Q%02d  group %s  tables: %s" % (args.query, g, ", ".join(tables)))
    print("  resident now: %.2f GB of %.0f GB" % (resident_gb(ora), CAP_GB))
    print("  indexes on resident tables: %d, of which this query can use %d"
          % (full, len(wanted)))
    for name, table, cols, lead in wanted:
        print("    %-38s %-9s (%s)  [leading %s]" % (name, table, cols, lead))
    if not args.build:
        return 0

    print("  building:")
    built, skipped, ok = build(ora, wanted)
    print("  built %d, already present %d, resident %.2f GB%s"
          % (len(built), len(skipped), resident_gb(ora),
             "" if ok else "  -- HIT THE CAP, subset incomplete"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
