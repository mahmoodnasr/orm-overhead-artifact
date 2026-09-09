#!/usr/bin/env python3
"""Every path must actually use the parameter set it is handed.

Why this exists, and why tests/test_paramsets.py is not enough
-------------------------------------------------------------
test_paramsets.py proves that set 0 reproduces the pre-parameterisation SQL
byte for byte. That is the right check for "the refactor changed no query's
meaning", and it is structurally incapable of catching the opposite defect.

A substitution that was missed leaves a hard-coded value in the code. That
value IS set 0. So the byte-identity check passes, precisely because nothing
changed - and nothing changing is exactly what a parameter being ignored looks
like. The check and the defect are invisible to each other.

This happened. django_app/queries/q01.py bound its cut-off to a local
variable, `cutoff_date = date(1998, 9, 2)`, so a scan looking for the literal
in a filter expression did not see it and the substitution table did not cover
it. Every guard passed. It was caught only by running the validator across all
eight parameter sets, where q01 set 1 read MATCH DIFF and ORM=SQL DIFF: Django
was querying a different date from the other three paths.

The consequence had it survived: eight blocks would all have measured the same
instance on that path, reported an impressively low CV, passed the noise gate
in ANALYSIS_PLAN.md section 8.1, and measured one plan eight times - which is
the exact thing the eight-block design exists to prevent. It is C6's family:
a plausible measurement of something that is not the query.

So the test here is the inverse one. Not "is set 0 unchanged" but "does the
work DIFFER between two sets". Both are needed; neither implies the other.

Comparison is over statement text AND bound parameter values, because both
ORMs bind rather than inline: two parameter sets produce byte-identical ORM
SQL and differ only in the values, so a text-only comparison would report an
ignored parameter as a pass.

Requires a live PostgreSQL at SF1. Run with the campaign environment set:

    PYTHONPATH=. TPCH_SF=1 DJANGO_SETTINGS_MODULE=django_app.settings \
    SA_DSN=... venv/bin/python tests/test_parameters_take_effect.py
"""

import glob
import os
import re
import sys
import importlib

HERE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE_ROOT)
os.environ.setdefault("TPCH_SF", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")

import django

django.setup()
from django.db.backends import utils as dbutils
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Two sets far apart in the stream, used as the source of alternative values.
SETS = (0, 3)

# Comparing set 0 against set 3 wholesale is NOT sufficient, and the first
# version of this file made exactly that mistake.
#
# It asked "does anything change between two sets", which a module passes as
# soon as ONE of its parameters is threaded. Three queries passed it while
# still carrying a hard-coded value:
#
#   Q03  Django ORM held order_date/ship_date as local `date(1995, 3, 15)`
#        literals; only its segment was parameterised, and the segment
#        changing was enough to satisfy the coarse test.
#   Q06  Django ORM held start_date/end_date the same way; discount and
#        quantity were threaded.
#   Q16  SQLAlchemy ORM kept `Part.size.in_([49, 14, 23, 45, 19, 3, 36, 9])`;
#        brand and type were threaded.
#
# All three were caught instead by validating all eight parameter sets, where
# MATCH and ORM=SQL read DIFF on every set but set 0 - the paths disagreeing
# with each other is what a partly-threaded query looks like from outside.
#
# So the test varies ONE key at a time and requires the emitted work to change
# for that key specifically. A key whose value happens to coincide between the
# two source sets cannot be tested this way and is reported, not skipped
# silently.

_DJ = []
_orig = dbutils.CursorWrapper.execute


def _hook(self, sql, params=None):
    _DJ.append((str(sql), tuple(str(x) for x in params) if params else ()))
    return _orig(self, sql, params)


dbutils.CursorWrapper.execute = _hook

_engine = create_engine(os.environ["SA_DSN"], future=True)
_SA = []


@event.listens_for(_engine, "before_cursor_execute")
def _sa_hook(conn, cur, statement, parameters, context, executemany):
    _SA.append((str(statement), str(parameters)))


_Session = sessionmaker(bind=_engine, future=True)


class _FakeCursor:
    """Collects the statement without a database. Django's SQL path only."""

    def __init__(self, sink):
        self.sink, self.description = sink, []

    def execute(self, sql, params=None):
        self.sink.append((str(sql), tuple(map(str, params)) if params else ()))

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, vendor, sink):
        self.vendor, self.sink = vendor, sink

    def cursor(self):
        return _FakeCursor(self.sink)


def _perturbations(qnum):
    """One (key, parameter-set) pair per parameter, each differing in that key.

    Only BASE keys are varied - the ones the generator draws. Derived keys
    (date_end, disc_lo/disc_hi, sizes_sql, like_pattern, codes_sql) cannot be
    varied independently, because every path resolves its parameters through
    tpch_paramsets.resolve(), which calls expand(), which RECOMPUTES the derived
    keys from their base keys and discards whatever was passed in. A first
    version of this test perturbed them anyway and reported 158 false failures.

    That recomputation is not an obstacle to be worked around; it IS the
    guarantee that a derived value cannot disagree with the value it is derived
    from, which is the shape defect C9 took. What it does mean is that this test
    cannot see a module that reads `date` and hard-codes the end of its range -
    perturbing `date` moves both, so the module still appears to respond. That
    gap is covered by test_no_leftover_substitution_literals() below, which is
    a static scan and does not depend on emitted output at all.
    """
    import tpch_paramsets as ps

    raw_base = ps.PARAM_SETS[qnum][SETS[0]]
    raw_alt = ps.PARAM_SETS[qnum][SETS[1]]
    base = ps.params_of(qnum, SETS[0])
    out, unvaried = [], []
    for key in raw_base:
        if key in ps.NON_SUBSTITUTING:
            continue
        if key not in raw_alt or raw_alt[key] == raw_base[key]:
            unvaried.append(key)
            continue
        perturbed = dict(raw_base)
        perturbed[key] = raw_alt[key]
        out.append((key, ps.expand(qnum, perturbed)))
    return base, out, unvaried


def _django_sql(mod, vendor, params):
    sink = []
    mod.run_query_sql(_FakeConn(vendor, sink), params=params)
    return tuple(sink)


def _django_orm(mod, params):
    _DJ.clear()
    mod.run_query_orm(using="default", params=params)
    return tuple(_DJ)


def _sqlalchemy(fn, params):
    _SA.clear()
    session = _Session()
    try:
        fn(session, params=params)
    finally:
        session.close()
    return tuple(_SA)


# Date windows that ARE fixed by the specification and are correctly literal.
# Q07 compares two nations over 1995-01-01..1996-12-31 and Q08 computes a market
# share over 1995..1996; neither window is a substitution parameter, so neither
# appears in a parameter set and neither should be flagged.
SPEC_CONSTANT_DATES = {
    7: {"1995-01-01", "1996-12-31", "1995, 1, 1", "1996, 12, 31"},
    # Q08's window appears in two equivalent spellings across the modules: the
    # specification's own `BETWEEN '1995-01-01' AND '1996-12-31'`, and the
    # half-open `>= '1995-01-01' AND < '1997-01-01'`. On a DATE column with no
    # time component they select the same rows. Both are allowed; neither is a
    # substitution parameter.
    8: {
        "1995-01-01",
        "1997-01-01",
        "1996-12-31",
        "1995, 1, 1",
        "1997, 1, 1",
        "1996, 12, 31",
    },
}

_DATE_LITERAL = re.compile(
    r"date\((\d{4}, \d{1,2}, \d{1,2})\)|['\"](\d{4}-\d{2}-\d{2})['\"]"
)


def test_no_leftover_substitution_literals():
    """No query module may contain a date literal that is not a spec constant.

    This is the check the perturbation test cannot make. Perturbing `date`
    moves `date_end` with it, so a module that reads the start of its range and
    hard-codes the end still looks responsive. A static scan does not care what
    the module emits.

    It is also how the four defects found on 2026-09-02 would have been caught
    directly rather than through cross-path disagreement: all four were literals
    sitting in plain sight, three of them bound to a local variable
    (`order_date = date(1995, 3, 15)`) where a scan for the value inside a
    filter expression did not look.
    """
    offenders = []
    for path in sorted(
        glob.glob(
            os.path.join(
                os.path.dirname(HERE_ROOT),
                "orm-benchmark-reproducibility",
                "django_app/queries/q[0-9][0-9]*.py",
            )
        )
    ) or sorted(
        glob.glob(os.path.join(HERE_ROOT, "django_app/queries/q[0-9][0-9]*.py"))
    ):
        base = os.path.basename(path)
        qnum = int(base[1:3])
        allowed = SPEC_CONSTANT_DATES.get(qnum, set())
        for lineno, line in enumerate(open(path), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("--"):
                continue
            for m in _DATE_LITERAL.finditer(line):
                value = m.group(1) or m.group(2)
                if value in allowed:
                    continue
                offenders.append((base, lineno, value, stripped[:70]))
    if offenders:
        print(f"FAIL: {len(offenders)} hard-coded date literal(s) in query modules:")
        for b, ln, v, src in offenders:
            print(f"    {b}:{ln}  {v}   {src}")
        return 1
    print(
        "ok    no query module carries a date literal outside the "
        "specification's own fixed windows"
    )
    return 0


def main():
    inert, skipped, unvaried_report = [], [], []
    import tpch_paramsets as ps

    for q in range(1, 23):
        base, perturbations, unvaried = _perturbations(q)
        if unvaried:
            unvaried_report.append((q, unvaried))

        targets = []
        for suffix in ("", "_oracle", "_sqlserver"):
            name = f"django_app.queries.q{q:02d}{suffix}"
            try:
                mod = importlib.import_module(name)
            except ModuleNotFoundError:
                continue
            for vendor in ("postgresql", "mysql", "oracle", "microsoft"):
                targets.append(
                    (
                        name,
                        f"django/sql/{vendor}",
                        lambda pm, m=mod, v=vendor: _django_sql(m, v, pm),
                    )
                )
            targets.append((name, "django/orm", lambda pm, m=mod: _django_orm(m, pm)))
        sa = importlib.import_module(f"sqlalchemy_app.queries.q{q:02d}")
        for label, fn in (
            ("sqlalchemy/sql", sa.run_query_sql),
            ("sqlalchemy/orm", sa.run_query_orm),
        ):
            targets.append((f"q{q:02d}", label, lambda pm, f=fn: _sqlalchemy(f, pm)))

        for name, path, run in targets:
            try:
                reference = run(base)
            except Exception as e:
                if "NotExpressible" in type(e).__name__:
                    skipped.append((name, path, "not expressible"))
                    continue
                skipped.append((name, path, f"{type(e).__name__}"))
                continue
            for key, perturbed in perturbations:
                try:
                    got = run(perturbed)
                except Exception as e:
                    # An incoherent perturbation can raise; that still proves
                    # the value was read, which is what is being tested.
                    if "NotExpressible" in type(e).__name__:
                        continue
                    got = ("EXC", type(e).__name__)
                if got == reference:
                    inert.append((name, path, key))

    for name, path, why in skipped:
        print(f"  skip  {name:34s} {path:26s} {why}")
    if unvaried_report:
        print()
        print(
            "  keys that happen to coincide between the two source sets, so "
            "they could not be varied:"
        )
        for q, keys in unvaried_report:
            print(f"    Q{q:02d}: {', '.join(keys)}")
    print()
    if inert:
        print(
            f"FAIL: {len(inert)} (path, parameter) pair(s) where changing the "
            f"parameter changed nothing - it is being ignored:"
        )
        for name, path, key in inert:
            print(f"    {name:34s} {path:26s} {key}")
        return 1
    print("ok    every parameter is read by every path that should read it")
    return test_no_leftover_substitution_literals()


if __name__ == "__main__":
    sys.exit(main())
