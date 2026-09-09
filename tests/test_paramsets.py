#!/usr/bin/env python3
"""Guards on the eight-block substitution-parameter machinery.

Run with:  PYTHONPATH=. TPCH_SF=1 venv/bin/python tests/test_paramsets.py

The important test here is `test_set0_is_byte_identical`. Parameterising the
SQL baselines rewrote 52 fragments across 22 statements, and a single wrong
fragment would change a query's selectivity while leaving it valid SQL and
returning plausible rows - the exact shape of defect C6, which recorded a
believable time for a query that was not Q11. sql_baseline_pre_paramsets.json
is a snapshot of all 88 statements (22 queries x 4 vendors) taken immediately
before the refactor, and set 0 has to reproduce every one of them exactly.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TPCH_SF", "1")

import tpch_domains as domains
import tpch_paramsets as ps
from sqlalchemy_app.queries import _sql

HERE = os.path.dirname(os.path.abspath(__file__))
failures = []


def check(name, cond, detail=""):
    print(
        ("  ok   " if cond else "  FAIL ")
        + name
        + (f"  {detail}" if detail and not cond else "")
    )
    if not cond:
        failures.append(name)
        # Pytest ignores this module's final __main__ block. Fail at the check
        # itself so an invalid SQL baseline cannot be reported as a passing test.
        raise AssertionError(f"{name}: {detail}")


def test_set0_is_byte_identical():
    """Set 0 must emit exactly the SQL the harness emitted before parameters."""
    snap = json.load(open(os.path.join(HERE, "sql_baseline_pre_paramsets.json")))
    bad = [
        k
        for k, want in snap.items()
        if _sql.sql_for(int(k.split(":")[0]), k.split(":")[1]) != want
    ]
    check(
        f"set 0 reproduces all {len(snap)} pre-refactor statements",
        not bad,
        f"differ: {bad}",
    )


def test_every_placeholder_is_substituted():
    """No {P_*} may survive into a statement handed to a database."""
    left = []
    for q in range(1, 23):
        for v in ("postgresql", "mysql", "oracle", "microsoft"):
            for i in range(ps.N_SETS):
                sql = _sql.sql_for(q, v, ps.params(q, i))
                if "{P_" in sql or "{Q11" in sql or "{LIMIT" in sql or "{SUBSTR" in sql:
                    left.append(f"Q{q:02d}/{v}/s{i}")
    check("no unsubstituted placeholders in 704 statements", not left, str(left[:5]))


def test_parameters_actually_move_the_sql():
    """A parameter set that changes nothing would silently defeat the design.

    Q18 is the exception and it is expected: its domain is four values, so some
    of its eight sets repeat. Everything else must differ from set 0.
    """
    inert = []
    for q in range(1, 23):
        base = _sql.sql_for(q, "postgresql", ps.params(q, 0))
        variants = {
            _sql.sql_for(q, "postgresql", ps.params(q, i)) for i in range(1, ps.N_SETS)
        }
        if base in variants or len(variants) < 2:
            if q not in ps._SMALL_DOMAIN:
                inert.append(q)
    check("every query's parameter sets produce distinct SQL", not inert, str(inert))


def test_set_count_and_distinctness():
    dup = []
    for q, sets in ps.PARAM_SETS.items():
        if len(sets) != ps.N_SETS:
            dup.append((q, "wrong count"))
        seen = []
        for s in sets:
            if s in seen and q not in ps._SMALL_DOMAIN:
                dup.append((q, s))
            seen.append(s)
    check(
        f"{ps.N_SETS} distinct sets per query (Q18 exempt, four legal values)",
        not dup,
        str(dup),
    )


def test_determinism():
    """Regenerating must give the same sets, or the artifact is not reproducible."""
    import importlib

    first = {q: list(v) for q, v in ps.PARAM_SETS.items()}
    importlib.reload(ps)
    check("regeneration is deterministic", first == ps.PARAM_SETS)


def test_parameters_are_in_the_data():
    """A value absent from the database gives an empty result and a real time.

    That combination - plausible duration, zero rows - is how C6 survived a
    whole campaign, so the domains are checked against the data's own
    vocabulary rather than trusted.
    """
    bad = []
    for q in range(1, 23):
        for i in range(ps.N_SETS):
            p = ps.params(q, i)
            for key, pool in (
                ("region", domains.REGIONS),
                ("nation", domains.NATIONS),
                ("nation1", domains.NATIONS),
                ("nation2", domains.NATIONS),
                ("segment", domains.SEGMENTS),
                ("color", domains.COLORS),
                ("container", domains.CONTAINERS),
                ("brand", domains.BRANDS),
                ("brand1", domains.BRANDS),
                ("brand2", domains.BRANDS),
                ("brand3", domains.BRANDS),
                ("shipmode1", domains.SHIPMODES),
                ("shipmode2", domains.SHIPMODES),
            ):
                if key in p and p[key] not in pool:
                    bad.append((q, i, key, p[key]))
    check("every drawn value exists in the data's domain", not bad, str(bad[:5]))


def test_q18_set0_is_declared_out_of_range():
    """Q18's validation value is outside its own substitution range.

    Kept deliberately (block 0 stays comparable to every earlier measurement),
    but it must stay declared, because it makes Q18's across-block spread
    include a parameter effect the other 21 queries do not have. Measured on
    SF1: 57 order groups at 300, 9-10 at 312-315.
    """
    check(
        "Q18 declared in _SET0_OUTSIDE_RANGE",
        18 in ps._SET0_OUTSIDE_RANGE and ps.PARAM_SETS[18][0]["quantity"] == 300,
    )


def test_williams_design_is_actually_williams():
    """A design that is only labelled Williams is not one.

    Four arbitrary orders would leave some adjacent ordered pairs unbalanced,
    which is the single property the counterbalancing exists to provide. Both
    conditions are checked: every path once in every position, and every
    ordered adjacent pair exactly once.
    """
    src = open(
        os.path.join(os.path.dirname(HERE), "scripts/2-benchmark/run_block.py")
    ).read()
    ns = {}
    exec(src[src.index("PATHS = (") : src.index("FIELDS = [")], ns)
    W, P = ns["WILLIAMS"], ns["PATHS"]
    positions = all(sorted(seq[i] for seq in W) == sorted(P) for i in range(4))
    pairs = [(seq[i], seq[i + 1]) for seq in W for i in range(3)]
    check("Williams: every path once in every position", positions)
    check(
        "Williams: every ordered adjacent pair exactly once",
        len(pairs) == len(set(pairs)) == 12,
    )


def test_warmup_instance_is_not_a_measured_one():
    """Warming with a measured set would start that block warmer than the rest."""
    overlap = [q for q in range(1, 23) if ps.WARMUP_SETS[q] in ps.PARAM_SETS[q]]
    check(
        "warmup parameters distinct from all eight measured sets",
        overlap == [18],
        f"unexpected overlap: {[q for q in overlap if q != 18]}",
    )


if __name__ == "__main__":
    print(__doc__.strip().splitlines()[0])
    for fn in (
        test_set0_is_byte_identical,
        test_every_placeholder_is_substituted,
        test_parameters_actually_move_the_sql,
        test_set_count_and_distinctness,
        test_determinism,
        test_parameters_are_in_the_data,
        test_q18_set0_is_declared_out_of_range,
        test_williams_design_is_actually_williams,
        test_warmup_instance_is_not_a_measured_one,
    ):
        fn()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all guards pass")
