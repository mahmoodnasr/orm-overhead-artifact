#!/usr/bin/env python3
"""Capture SQL Server execution plans for the ORM and hand-written paths.

    python3 collect_plans_sqlserver.py --queries 17,12,20,13
    python3 collect_plans_sqlserver.py --queries 17 --schema indexed

`collect_plans.py` issues `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, which is
PostgreSQL syntax, and `collect_plans_oracle.py` uses `DBMS_XPLAN`. SQL Server
uses `SET SHOWPLAN_XML ON`, which returns the plan **without executing the
statement** - so this is safe to run against queries that time out, which is
precisely the set it exists for.

## Why this was written late, and what it is for

SQL Server carries the largest unexplained overheads in the study:

| | | |
|---|---|---:|
| Q17 | Django, indexed | +19,426 % |
| Q17 | SQLAlchemy, indexed | +13,935 % |
| Q12 | Django, indexed | +487 % |
| Q20 | SQLAlchemy, indexed | +334 % |

A number that large is either the study's most interesting finding or a defect,
and the timings cannot tell those apart. Only the plan can. PostgreSQL's Q17
runs the *opposite* way - Django's ORM formulation beats the hand-written
baseline by 98.7 % - so the same query and the same two formulations invert
between two systems, and that inversion is the thing worth explaining.

Like the Oracle collector, **the ORM statement is reconstructed, not
intercepted**: this execs the source of `run_query_orm` to rebuild the queryset
and compile it. Treat a captured plan as evidence only where the same query also
has a timing in the results file.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_sqlserver")

import django
django.setup()

from django.db import connections
import pyodbc

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def connect():
    drv = max((d for d in pyodbc.drivers() if "SQL Server" in d),
              key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))
    return pyodbc.connect(
        "DRIVER={%s};SERVER=127.0.0.1,1433;DATABASE=tpch;UID=sa;PWD=%s;"
        "TrustServerCertificate=yes"
        % (drv, os.environ.get("SQLSERVER_SA_PASSWORD", "YourStrong!Passw0rd")),
        autocommit=True)


def django_orm_sql(n):
    """The statement Django's ORM path would send, with parameters inlined.

    SHOWPLAN_XML cannot take parameters through pyodbc's binding, because the
    plan request and the statement must arrive in the same batch. Literals are
    substituted instead - which is also what makes the captured plan comparable
    with the hand-written baseline, whose parameters are literals too.
    """
    import inspect
    from django_app.queries import get_query_module_for_db
    m = get_query_module_for_db(n, "sqlserver")
    src = inspect.getsource(m.run_query_orm)
    ns = {}
    exec(compile(src.replace("def run_query_orm(using='default'):", "def _q(using='default'):")
                    .replace("return list(results)", "return results"),
                 "<q%02d>" % n, "exec"), m.__dict__, ns)
    result = ns["_q"](using="default")

    # Most modules return a queryset, which carries `.query` and can be
    # compiled without touching the server. Q17 does not: it ends in
    # `.aggregate()`, which evaluates immediately and returns a dict, so there
    # is no queryset left to compile - and Q17 is the query with the largest
    # overhead in the study, so it is exactly the one that must not be skipped.
    #
    # For that case, intercept the compiler instead of reconstructing: patch
    # execute_sql to record what it was about to send and abort before it sends
    # it. That yields the real statement for any shape of ORM call, evaluated or
    # not, and never runs the query.
    if not hasattr(result, "query"):
        from django.db.models.sql.compiler import SQLCompiler
        captured = {}

        class _Stop(Exception):
            pass

        original = SQLCompiler.execute_sql

        def _capture(self, *a, **kw):
            if "sql" not in captured:
                captured["sql"], captured["params"] = self.as_sql()
            raise _Stop()

        SQLCompiler.execute_sql = _capture
        try:
            ns["_q"](using="default")
        except _Stop:
            pass
        finally:
            SQLCompiler.execute_sql = original
        if "sql" not in captured:
            raise RuntimeError("compiler was never reached")
        sql, params = captured["sql"], captured["params"]
    else:
        sql, params = result.query.get_compiler(
            connection=connections["default"]).as_sql()

    for p in params:
        lit = ("'%s'" % str(p).replace("'", "''")) if isinstance(p, str) else str(p)
        sql = sql.replace("%s", lit, 1)
    return sql


def showplan(cur, sql):
    """-> the XML plan. SHOWPLAN_XML returns the plan and does not run the query."""
    cur.execute("SET SHOWPLAN_XML ON")
    try:
        cur.execute(sql)
        chunks = []
        while True:
            for row in cur.fetchall():
                chunks.append(row[0])
            if not cur.nextset():
                break
        return "".join(c for c in chunks if c)
    finally:
        cur.execute("SET SHOWPLAN_XML OFF")


def operators(xml):
    """The physical operators, in document order - what the analysis compares.

    Parsed with a regex rather than an XML parser on purpose: the plan carries a
    default namespace, so every ElementTree path would need qualifying, and the
    only thing wanted here is an ordered list of attribute values.
    """
    return re.findall(r'PhysicalOp="([^"]+)"', xml or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="17,12,20,13,09,02",
                    help="the outliers, by default")
    ap.add_argument("--schema", default="indexed")
    ap.add_argument("--outdir", default=os.path.join(REPO, "results", "corrected"))
    args = ap.parse_args()

    from sqlalchemy_app.queries._sql import sql_for

    cn = connect()
    cur = cn.cursor()
    outdir = os.path.join(args.outdir, "execution_plans_sqlserver", args.schema)
    os.makedirs(outdir, exist_ok=True)
    captured, skipped = 0, []

    for n in [int(x) for x in args.queries.split(",")]:
        qid = "Q%02d" % n
        paths = {}
        try:
            paths["django_orm"] = django_orm_sql(n)
        except Exception as e:
            print("  %s django/orm: could not build - %s" % (qid, str(e)[:70]))
        try:
            paths["baseline_sql"] = sql_for(n, "sqlserver")
        except Exception as e:
            print("  %s baseline:   could not build - %s" % (qid, str(e)[:70]))

        for name, sql in paths.items():
            try:
                xml = showplan(cur, sql)
            except Exception as e:
                msg = str(e).split("\n")[0]
                skipped.append("%s %s: %s" % (qid, name, msg[:60]))
                print("  %s %-13s skipped: %s" % (qid, name, msg[:60]))
                continue
            ops = operators(xml)
            with open(os.path.join(outdir, "%s_%s.json" % (qid, name)), "w") as fh:
                json.dump({"query_id": qid, "path": name, "dbms": "sqlserver",
                           "schema_config": args.schema, "sql": sql,
                           "plan_xml": xml, "operations": ops}, fh, indent=2)
            captured += 1
            print("  %s %-13s captured (%d operators: %s)"
                  % (qid, name, len(ops), ", ".join(ops[:6])))

    cn.close()
    print("\n  %d plans written to %s" % (captured, os.path.relpath(outdir, REPO)))
    for s in skipped:
        print("   skipped:", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
