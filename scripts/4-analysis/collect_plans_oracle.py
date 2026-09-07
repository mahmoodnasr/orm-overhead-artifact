#!/usr/bin/env python3
"""Capture Oracle execution plans for each of the four access paths.

    python3 collect_plans_oracle.py --queries 2,11,13,16,22
    python3 collect_plans_oracle.py --queries 2 --outdir results/corrected

`collect_plans.py` cannot do this: it issues
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, which is PostgreSQL syntax. Oracle
uses `EXPLAIN PLAN FOR` writing into PLAN_TABLE, read back through
`DBMS_XPLAN.DISPLAY`. The two produce different shapes and there is no common
subset worth abstracting over, so this is a separate script rather than a branch.

**The ORM statement is reconstructed, not intercepted.** This execs the source of
`run_query_orm` to rebuild the queryset and compile it, which is faithful for
most queries and not for all: Q22 compiles to something Oracle rejects with
ORA-00979 while its real ORM path measures cleanly and passes all five
validation checks. Treat a captured plan as evidence only where the same query
also has a timing in the results file.

**Only the queries whose tables are currently resident can be captured.** Oracle
Free's 12 GB cap means this study holds one working set at a time
(`scripts/1-setup/oracle_groups.py`), and `EXPLAIN PLAN` needs the tables to
exist even though it does not read them. Running this against a group that is not
loaded gives ORA-00942, which the script reports per query rather than treating
as a failure of the run.

What the plans are for: the timings say Django's Q02 costs 115x its own SQL
baseline, and only the plan says why — Oracle rewrites the hand-written
correlated subquery into a window function (`VW_WIF_1`) and does not apply that
transformation to the ORM's statement, which keeps a per-row `FILTER`. That is
the difference between reporting a number and explaining it.
"""
import argparse
import itertools
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_oracle")

import django
django.setup()

from django.db import connections
import oracledb

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def django_orm_sql(n):
    """The SQL Django's ORM path would send, with Oracle-style bind names."""
    import inspect
    from django_app.queries import get_query_module_for_db
    m = get_query_module_for_db(n, "oracle")
    src = inspect.getsource(m.run_query_orm)
    ns = {}
    exec(compile(src.replace("def run_query_orm(using='default'):", "def _q(using='default'):")
                    .replace("return list(results)", "return results"),
                 "<q%02d>" % n, "exec"), m.__dict__, ns)
    qs = ns["_q"](using="default")
    sql, params = qs.query.get_compiler(connection=connections["default"]).as_sql()
    # Django emits %s; Oracle needs named binds.
    c = itertools.count(1)
    sql = re.sub(r"%s", lambda _: ":b%d" % next(c), sql)
    return sql, {"b%d" % (i + 1): p for i, p in enumerate(params)}


def explain(cur, sql, binds, tag):
    cur.execute("EXPLAIN PLAN SET STATEMENT_ID = '%s' FOR %s" % (tag, sql), binds or {})
    cur.execute("SELECT plan_table_output FROM TABLE("
                "DBMS_XPLAN.DISPLAY(NULL, :t, 'BASIC +COST +ROWS'))", {"t": tag})
    return [r[0] for r in cur.fetchall() if r[0] is not None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="2,11,13,16,22")
    ap.add_argument("--schema", default="indexed")
    ap.add_argument("--outdir", default=os.path.join(REPO, "results", "corrected"))
    args = ap.parse_args()

    from sqlalchemy_app.queries._sql import sql_for

    cn = oracledb.connect(user=os.environ.get("ORACLE_USER", "tpch"),
                          password=os.environ.get("ORACLE_PASSWORD", "bench"),
                          dsn=os.environ.get("ORA_DSN", "127.0.0.1:41521/FREEPDB1"))
    cur = cn.cursor()

    outdir = os.path.join(args.outdir, "execution_plans_oracle", args.schema)
    os.makedirs(outdir, exist_ok=True)
    captured, skipped = 0, []

    for n in [int(x) for x in args.queries.split(",")]:
        qid = "Q%02d" % n
        paths = {}
        try:
            paths["django_orm"] = django_orm_sql(n)
        except Exception as e:
            paths["django_orm"] = None
            print("  %s django/orm: could not build - %s" % (qid, str(e)[:70]))
        paths["baseline_sql"] = (sql_for(n, "oracle"), {})

        for name, pair in paths.items():
            if pair is None:
                continue
            sql, binds = pair
            tag = ("%s_%s" % (qid, name))[:30]
            try:
                lines = explain(cur, sql, binds, tag)
            except Exception as e:
                msg = str(e).split("\n")[0]
                skipped.append("%s %s: %s" % (qid, name, msg[:60]))
                print("  %s %-13s skipped: %s" % (qid, name, msg[:60]))
                continue
            # The operation names are what the analysis reads; keep the SQL too so
            # a reader can see exactly what was explained.
            ops = [l.strip() for l in lines if "|" in l and "Id" not in l and "---" not in l]
            with open(os.path.join(outdir, "%s_%s.json" % (qid, name)), "w") as fh:
                json.dump({"query_id": qid, "path": name, "dbms": "oracle",
                           "schema_config": args.schema, "sql": sql,
                           "plan_text": lines, "operations": ops}, fh, indent=2)
            captured += 1
            print("  %s %-13s captured (%d plan lines)" % (qid, name, len(lines)))

    cn.close()
    print("\n  %d plans written to %s" % (captured, os.path.relpath(outdir, REPO)))
    if skipped:
        print("  %d skipped:" % len(skipped))
        for s in skipped[:8]:
            print("   ", s)
        print("\n  Two different causes, and they mean different things:")
        print("   ORA-00942  the working set for that query is not resident. Oracle")
        print("              Free holds one group at a time; load it and re-run.")
        print("   anything else  this script reconstructs the ORM queryset by")
        print("              exec-ing the source of run_query_orm, and that")
        print("              reconstruction is not faithful for every query. Q22")
        print("              raises ORA-00979 here while its ORM path measures")
        print("              cleanly and passes all five validation checks, so the")
        print("              fault is in the reconstruction, not the query. A plan")
        print("              is only trustworthy if the same query also ran.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
