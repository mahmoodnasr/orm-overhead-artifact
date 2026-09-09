#!/usr/bin/env python3
"""Validation harness for the TPC-H query implementations.

Five checks per query, one line of output each. The last two were added after
each let a real defect reach the results file.

  ORM?     the SQLAlchemy run_query_orm path emits SQL built by the ORM, not a
           text() literal. This is the defect that invalidated the original
           SQLAlchemy measurements, so it is checked mechanically.
  MATCH    SQLAlchemy ORM results equal Django ORM results.
  SQL=     the two hand-written baselines agree, i.e. the two frameworks are
           running the same query.
  ORM=SQL  each ORM result equals its own SQL baseline. Without this, a fault
           hitting both ORM paths identically is invisible - which is what
           Oracle's CHAR binding was, and all three earlier checks passed on it.
  ROWS>0   the query returned something. Every TPC-H query does, against a valid
           database; Q11 with the wrong scale-dependent threshold did not, and
           still produced a plausible execution time.

Environment:
  DJ_VENDOR         postgresql (default), mysql, oracle, sqlserver
  SA_DSN            SQLAlchemy URL for the same database
  TPCH_SF           scale factor, for the parameters that depend on it
  VALIDATE_TIMEOUT  seconds per statement, default 900

Usage:  python3 validate.py [q01 q02 ...]
"""

import os, sys, time, json, decimal, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")

import django
import tpch_paramsets

django.setup()
from django.db import connections

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

PG = os.environ.get(
    "SA_DSN", "postgresql+psycopg2://postgres:bench@127.0.0.1:55432/tpch"
)

# A validation run had no deadline of its own, which is fine until a query the
# physical design cannot support meets a 60-million-row table: Q17's correlated
# subquery ran for over half an hour on Oracle without the LINEITEM part-key
# index and would have blocked the campaign indefinitely. Bound it.
TIMEOUT_S = float(os.environ.get("VALIDATE_TIMEOUT", "900"))

VENDOR = os.environ.get("DJ_VENDOR", "postgresql")
TIMEOUT_MS = int(TIMEOUT_S * 1000)


def _connect_args():
    """PostgreSQL's ceiling travels as a libpq connection option, not as SQL.

    C32: it used to be `SET statement_timeout` issued on the Session, and
    PostgreSQL undoes a SET whose transaction is rolled back. `check()` rolls
    back deliberately after a path fails, so the first SQLAlchemy path to time
    out removed the ceiling for the second, which then ran unbounded - measured
    at 790 s and 1273 s against a 600 s ceiling on Q17 and Q20. Django never had
    the problem because it runs in autocommit, so the two frameworks were being
    validated under different rules. As a connection option there is no
    statement and no transaction, so nothing can undo it."""
    if VENDOR == "postgresql":
        return {"options": "-c statement_timeout=%d" % TIMEOUT_MS}
    return {}


engine = create_engine(PG, future=True, connect_args=_connect_args())
Session = sessionmaker(bind=engine, future=True)


@event.listens_for(engine, "connect")
def _arm_every_connection(dbapi_conn, _record):
    """The vendors whose ceiling is a driver attribute or a non-transactional
    session setting, armed once per connection rather than once per query, so a
    reconnect cannot hand back an unbounded one (C32). PostgreSQL is handled by
    _connect_args and is deliberately absent here."""
    try:
        if VENDOR == "oracle":
            dbapi_conn.call_timeout = TIMEOUT_MS
        elif VENDOR in ("mssql", "sqlserver"):
            dbapi_conn.timeout = int(TIMEOUT_S)
        elif VENDOR == "mysql":
            cur = dbapi_conn.cursor()
            try:
                cur.execute("SET SESSION max_execution_time = %d" % TIMEOUT_MS)
            finally:
                cur.close()
    except Exception:
        pass


# --- capture every statement SQLAlchemy sends, so we can tell ORM-built SQL
#     from a hand-written text() literal ------------------------------------
_emitted = []


@event.listens_for(engine, "before_cursor_execute")
def _capture(conn, cursor, statement, params, context, executemany):
    _emitted.append(statement)


def norm(v):
    """Normalize a value so Django and SQLAlchemy results can be compared."""
    if isinstance(v, decimal.Decimal):
        return round(float(v), 2)
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return str(v)[:10]
    if isinstance(v, str):
        return v.strip()
    return v


def rowset(rows):
    """Order-insensitive, key-insensitive comparable form of a result set."""
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(tuple(sorted((norm(x) for x in r.values()), key=repr)))
        elif isinstance(r, (list, tuple)):
            out.append(tuple(sorted((norm(x) for x in r), key=repr)))
        else:
            out.append((norm(r),))
    return sorted(out, key=repr)


def timed(fn, *a, **kw):
    t = time.perf_counter()
    res = fn(*a, **kw)
    return time.perf_counter() - t, res


def arm_timeout(dj_conn, sa_session):
    """Bound one statement on the DJANGO connection.

    SQLAlchemy's side is no longer armed here: it is armed once per connection,
    by _connect_args and _arm_every_connection above, because a ceiling set
    through this function did not survive the rollback `check()` performs after
    a failed path (C32). This function is kept for Django, whose autocommit
    makes the same statement durable, and its Oracle and SQL Server branches
    still touch the SQLAlchemy raw connection as a second belt - those are
    driver attributes, not transactional state, so re-applying them is free.

    PostgreSQL and MySQL take a session setting; Oracle's server-side equivalent
    is a Resource Manager plan needing DBA rights, so use the driver's
    round-trip deadline instead, and SQL Server has no session setting at all -
    its ceiling is a client-side timeout on the ODBC connection. Before that
    last branch existed, "sqlserver" fell through the lookup below and
    validation ran with no ceiling of any kind."""
    ms = TIMEOUT_MS
    vendor = VENDOR
    try:
        if vendor == "oracle":
            # Django connects lazily; without this the deadline lands on None.
            dj_conn.ensure_connection()
            for raw in (
                getattr(dj_conn, "connection", None),
                sa_session.connection().connection.dbapi_connection,
            ):
                if raw is not None:
                    raw.call_timeout = ms
        elif vendor in ("mssql", "sqlserver"):
            dj_conn.ensure_connection()
            for raw in (
                getattr(dj_conn, "connection", None),
                sa_session.connection().connection.dbapi_connection,
            ):
                if raw is not None:
                    raw.timeout = int(TIMEOUT_S)  # pyodbc, whole seconds
        else:
            stmt = {
                "postgresql": f"SET statement_timeout = {ms}",
                "mysql": f"SET SESSION max_execution_time = {ms}",
            }.get(vendor)
            if stmt:
                with dj_conn.cursor() as c:
                    c.execute(stmt)
    except Exception:
        pass


def ceiling_now(sa_session):
    """What ceiling is this session actually under, as the server reports it.

    C32 was invisible for as long as the harness set a ceiling and assumed it.
    Returns a string for the log, or None where the vendor has no server-side
    setting to read (Oracle and SQL Server bound the call from the client, so
    there is nothing to ask the server for)."""
    from sqlalchemy import text

    stmt = {
        "postgresql": "SHOW statement_timeout",
        "mysql": "SELECT @@SESSION.max_execution_time",
    }.get(VENDOR)
    if stmt is None:
        return None
    try:
        return str(sa_session.execute(text(stmt)).scalar())
    except Exception:
        return "unreadable"


def assert_ceiling(sa_session, where):
    """Refuse to time a path that is running with no ceiling. C32 produced a
    number that looked measured and was taken under no limit at all; that is
    worse than a missing cell, because nothing downstream can tell."""
    c = ceiling_now(sa_session)
    if c is not None and c in ("0", "0s", "unreadable"):
        raise RuntimeError(
            "statement ceiling is %r before %s - refusing to time an "
            "unbounded path (C32)" % (c, where)
        )
    return c


def check(qnum, set_index=0):
    """Run all four access paths, independently, and check whatever survives.

    `set_index` selects one of the eight substitution-parameter sets from
    tpch_paramsets; all four paths in a call use the same one, which is what
    makes the comparison a comparison. Set 0 is the TPC-H validation instance,
    so calling this with no set reproduces the historical behaviour exactly.
    Validating every set matters: a set is eight new predicates, and a
    predicate that returns nothing still returns a plausible time (C6).

    Each path used to share one try block with the other three, so the first
    exception ended the query and the paths after it were never run. Django
    cannot express Q13 on SQL Server or Oracle - a real result, C17 - and that
    exception aborted Q13's whole validation on both systems, leaving
    SQLAlchemy's ORM and both hand-written baselines uncompared. Those three
    cells were then measured anyway (C23) and the results file recorded them as
    passing (C22). Reloading the databases would have reproduced the identical
    ERROR line, because the fault was here and not in the data.

    Now: one try per path, per-path errors recorded, and every check computed
    over the paths that did run. A check that needs a path which failed reports
    `n/a`, which is not a pass - the campaign gate in
    scripts/utils/validated_queries.py keeps only queries whose five checks all
    read `yes`/`ok`, so an unavailable check still refuses the timing.
    """
    tag = f"q{qnum:02d}"
    from django_app.queries import get_query_module_for_db

    dj = get_query_module_for_db(qnum, os.environ.get("DJ_VENDOR", "postgresql"))
    sa = __import__(f"sqlalchemy_app.queries.{tag}", fromlist=["x"])

    conn = connections["default"]
    probe = Session()
    arm_timeout(conn, probe)
    probe.close()

    res, err, dur, emitted = {}, {}, {}, {}

    def run(name, fn, *a, **kw):
        try:
            dur[name], res[name] = timed(fn, *a, **kw)
        except Exception as e:
            err[name] = f"{type(e).__name__}: {e}"

    run("django/sql", dj.run_query_sql, conn, params=set_index)
    run("django/orm", dj.run_query_orm, using="default", params=set_index)

    sess = Session()
    arm_timeout(conn, sess)
    try:
        for name, fn in (
            ("sqlalchemy/orm", sa.run_query_orm),
            ("sqlalchemy/sql", sa.run_query_sql),
        ):
            # Order matters. assert_ceiling issues a statement of its own, and
            # _emitted feeds the ORM? check, which compares the FIRST statement
            # each path emitted. Clearing before the assertion left "SHOW
            # statement_timeout" as statement zero for both paths, they
            # compared equal, and ORM? read NO for all 22 queries - the check
            # that exists to catch C1, defeated by the probe meant to protect
            # the ceiling. Assert first, then clear, then run.
            try:
                assert_ceiling(sess, name)
            except Exception as e:
                err[name] = f"{type(e).__name__}: {e}"
                continue
            _emitted.clear()
            run(name, fn, sess, params=set_index)
            emitted[name] = list(_emitted)
            if name in err:
                # A failed statement can leave the session unusable for the
                # next one, which would report the first path's failure twice.
                try:
                    sess.rollback()
                except Exception:
                    pass
    finally:
        sess.close()

    if len(err) == 4:
        raise RuntimeError("; ".join(f"{k} {v}" for k, v in err.items())[:200])

    def ok(*paths):
        return all(p in res for p in paths)

    # Is the ORM path really the ORM? An ORM-built statement carries bound
    # parameter markers and a generated alias/label vocabulary; a text()
    # literal is byte-identical to the baseline statement.
    if ok("sqlalchemy/orm", "sqlalchemy/sql"):
        o, b = emitted.get("sqlalchemy/orm") or [], emitted.get("sqlalchemy/sql") or []
        same_as_literal = bool(o) and bool(b) and o[0].strip() == b[0].strip()
        is_orm = bool(o) and not same_as_literal
    else:
        is_orm = None

    match_orm = (
        rowset(res["django/orm"]) == rowset(res["sqlalchemy/orm"])
        if ok("django/orm", "sqlalchemy/orm")
        else None
    )
    match_sql = (
        rowset(res["django/sql"]) == rowset(res["sqlalchemy/sql"])
        if ok("django/sql", "sqlalchemy/sql")
        else None
    )

    # ORM=SQL: the original three checks compared ORM against ORM and baseline
    # against baseline, so a fault that hit both ORM paths identically was
    # invisible. On Oracle, Q2 returned 100 rows through both raw-SQL paths and
    # 0 rows through both ORM paths, and all three checks passed.
    #
    # It compared Django's pair only, so the mirror fault - one that hits
    # SQLAlchemy's ORM alone - was equally invisible. Both pairs are checked
    # now, and the verdict is the conjunction over whichever pairs ran.
    pairs = [
        (rowset(res[f"{fw}/orm"]) == rowset(res[f"{fw}/sql"]))
        for fw in ("django", "sqlalchemy")
        if ok(f"{fw}/orm", f"{fw}/sql")
    ]
    match_cross = all(pairs) if pairs else None

    # NONEMPTY: every TPC-H query returns at least one row against a valid
    # database. Q11's FRACTION is 0.0001/SF, and held at the SF1 constant its
    # HAVING clause excluded every group at SF10 - the query still scanned,
    # aggregated, sorted and reported a plausible time, so it was recorded as a
    # successful measurement of a query that returns nothing.
    nonempty = all(bool(v) for v in res.values()) if res else None

    any_rows = next((v for v in res.values() if isinstance(v, list)), None)
    return {
        "query": tag,
        "set": set_index,
        "set_id": tpch_paramsets.set_id(qnum, set_index),
        "is_orm": is_orm,
        "match_orm": match_orm,
        "match_sql": match_sql,
        "match_cross": match_cross,
        "nonempty": nonempty,
        "rows": len(any_rows) if any_rows is not None else 0,
        "paths_ok": sorted(res),
        "paths_failed": err,
        "t_django_orm": round(dur.get("django/orm", 0), 3),
        "t_sqla_orm": round(dur.get("sqlalchemy/orm", 0), 3),
        "t_django_sql": round(dur.get("django/sql", 0), 3),
        "t_sqla_sql": round(dur.get("sqlalchemy/sql", 0), 3),
        "overhead_django_pct": (
            round((dur["django/orm"] - dur["django/sql"]) / dur["django/sql"] * 100, 1)
            if ok("django/orm", "django/sql") and dur["django/sql"]
            else None
        ),
        "overhead_sqla_pct": (
            round(
                (dur["sqlalchemy/orm"] - dur["sqlalchemy/sql"])
                / dur["sqlalchemy/sql"]
                * 100,
                1,
            )
            if ok("sqlalchemy/orm", "sqlalchemy/sql") and dur["sqlalchemy/sql"]
            else None
        ),
    }


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    # --sets=all runs every parameter set; --sets=0,3 runs a chosen few. The
    # default is set 0 alone, so every existing invocation behaves as before.
    sets_arg = next(
        (a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--sets=")), "0"
    )
    if sets_arg == "all":
        sets = list(range(tpch_paramsets.N_SETS))
    else:
        sets = [int(x) for x in sets_arg.split(",") if x != ""]
    nums = [int(w.lstrip("q")) for w in want] if want else list(range(1, 23))
    results = []
    print(
        f"{'query':6s} {'ORM?':5s} {'MATCH':6s} {'SQL=':5s} {'ORM=SQL':8s} "
        f"{'ROWS>0':7s} {'rows':>7s}  "
        f"{'dj_orm':>7s} {'sa_orm':>7s} {'dj_sql':>7s} {'sa_sql':>7s}"
    )
    print("-" * 96)

    def verdict(v, yes, no):
        # None means a path this check needs did not run. It is printed as n/a
        # and is not a pass: the campaign gate keeps only yes/ok.
        return "n/a" if v is None else (yes if v else no)

    def t(r, k, path):
        return f"{r[k]:>7.3f}" if path in r["paths_ok"] else "  -----"

    for n, si in [(n, si) for n in nums for si in sets]:
        try:
            r = check(n, si)
            results.append(r)
            print(
                f"{r['query'] + ('' if len(sets) == 1 else '.s%d' % si):6s} {verdict(r['is_orm'], 'yes', 'NO'):5s} "
                f"{verdict(r['match_orm'], 'ok', 'DIFF'):6s} "
                f"{verdict(r['match_sql'], 'ok', 'DIFF'):5s} "
                f"{verdict(r['match_cross'], 'ok', 'DIFF'):8s} "
                f"{verdict(r['nonempty'], 'ok', 'EMPTY'):7s} {r['rows']:>7d}  "
                f"{t(r, 't_django_orm', 'django/orm')} {t(r, 't_sqla_orm', 'sqlalchemy/orm')} "
                f"{t(r, 't_django_sql', 'django/sql')} {t(r, 't_sqla_sql', 'sqlalchemy/sql')}"
            )
            # Name the paths that failed, on their own lines, so the log says
            # which of the four is missing rather than leaving a reader to infer
            # it from an n/a.
            for path, msg in sorted(r["paths_failed"].items()):
                print(f"       {r['query']}: {path} failed - {msg[:70]}")
        except Exception as e:
            results.append({"query": f"q{n:02d}", "error": f"{type(e).__name__}: {e}"})
            print(f"q{n:02d}    ERROR  {type(e).__name__}: {str(e)[:60]}")
    with open("validation_results.json", "w") as fh:
        json.dump(results, fh, indent=2)
    CHECKS = ("is_orm", "match_orm", "match_sql", "match_cross", "nonempty")
    ok = [r for r in results if all(r.get(c) for c in CHECKS)]
    print("-" * 96)
    print(f"{len(ok)}/{len(results)} queries pass all five checks")
    for r in results:
        if "error" in r:
            bad = ["error"]
        else:
            bad = [
                ("%s(n/a)" % c) if r.get(c) is None else c
                for c in CHECKS
                if not r.get(c)
            ]
        if bad:
            print(f"  {r['query']}: {', '.join(bad)}")
    # Say so in the exit status too. This returned 0 whatever it found, and the
    # campaign chains - which pipe it through tee - had nothing to react to; the
    # table above was read by people and by nothing else (C23). The chains now
    # gate on scripts/utils/validated_queries.py, which reads the table back;
    # the status is for anything simpler that just wants to know.
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
