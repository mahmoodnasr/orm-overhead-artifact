"""Eight seeded substitution-parameter sets per TPC-H query.

Why this exists
---------------
The campaign measures each cell in eight four-path blocks (SF1_RERUN_PLAN.md
section 5). Running one parameter instance eight times measures one plan eight
times, and if that instance happens to be unusually favourable or unusually
hostile, the cell's whole result inherits it. Q16's 82-point swing between the
two SF10 campaigns is the standing example of how far a single-instance
measurement can move. Eight paired sets measure the query.

The sets are *paired*, not merely varied: within a block, all four access paths
- Django SQL, Django ORM, SQLAlchemy SQL, SQLAlchemy ORM - use the identical
parameter set, so the log ratio taken inside that block compares the same work.
Both frameworks import their parameters from this one module, which is the same
mechanism that keeps them from drifting apart on Q11's FRACTION (defect C6).

Determinism
-----------
Everything derives from SEED via a per-query stream. Regenerating on any
machine with any Python 3.11+ gives byte-identical sets, because the draws use
random.Random's Mersenne Twister with an explicit integer seed and never touch
the global random module, dict ordering, or set iteration. The sets are
therefore reproducible from this file alone and are also written into the
artifact as data.

Set 0 is pinned
---------------
For every query, **set 0 is the TPC-H validation-set instance** - the parameter
values the specification's qualification query uses, and the values this
harness has always used. That is deliberate on two counts: the validation
queries in scripts/validate_queries.py keep working unchanged against set 0,
and every measurement taken before this module existed remains comparable to
block 0 of the new campaign rather than being orphaned.

Sets 1..7 are drawn from the specification's substitution ranges (clause 2.x,
"Substitution Parameters", per query).

Two queries have no substitution parameters at all in the specification - Q01
has DELTA only, and Q22's country codes are the only draw - so nothing here
invents variation the benchmark does not define. Where a query's parameters
must satisfy a constraint (Q07's two nations must differ, Q12's two ship modes
must differ, Q16's eight sizes must be distinct, Q19's three quantity ranges
are ordered, Q22's seven country codes are distinct), the constraint is
enforced at generation, not hoped for.
"""
import datetime as _dt
import random as _random

from tpch_domains import (
    BRANDS, COLORS, CONTAINERS, NATIONS, NATION_REGION, REGIONS, SEGMENTS,
    SHIPMODES, TYPE_SYLLABLE_1, TYPE_SYLLABLE_2, TYPE_SYLLABLE_3,
)
from tpch_params import Q11_FRACTION

SEED = 20260902
N_SETS = 8

_D = _dt.date


def add_months(d, months):
    """Advance a first-of-month date by whole months.

    Public, and imported by both the SQL baselines and the ORM implementations,
    because the end of a TPC-H date range is derived from its start and a fixed
    width. Two copies of this arithmetic is how defect C9 happened - four
    Oracle modules carrying Q04's window instead of their own.
    """
    m = d.month - 1 + months
    return d.replace(year=d.year + m // 12, month=m % 12 + 1, day=1)


def _month_range(start, end):
    """Inclusive list of (year, month) first-days between two (y, m) bounds."""
    (y0, m0), (y1, m1) = start, end
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(_D(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# --- per-query generators -------------------------------------------------
#
# Each returns the parameter dict for one draw. Set 0 never calls these; it is
# the pinned validation instance in _VALIDATION below.

def _q01(r):
    delta = r.randint(60, 120)
    return {"date": _D(1998, 12, 1) - _dt.timedelta(days=delta), "delta": delta}


def _q02(r):
    return {"size": r.randint(1, 50),
            "type_suffix": r.choice(TYPE_SYLLABLE_3),
            "region": r.choice(REGIONS)}


def _q03(r):
    return {"segment": r.choice(SEGMENTS),
            "date": _D(1995, 3, r.randint(1, 31))}


def _q04(r):
    return {"date": r.choice(_month_range((1993, 1), (1997, 10)))}


def _q05(r):
    y = r.randint(1993, 1997)
    return {"region": r.choice(REGIONS), "date": _D(y, 1, 1)}


def _q06(r):
    y = r.randint(1993, 1997)
    # DISCOUNT is drawn in hundredths; the predicate is DISCOUNT +/- 0.01.
    return {"date": _D(y, 1, 1),
            "discount": round(r.randint(2, 9) / 100.0, 2),
            "quantity": r.randint(24, 25)}


def _q07(r):
    n1, n2 = r.sample(NATIONS, 2)
    return {"nation1": n1, "nation2": n2}


def _q08(r):
    nation = r.choice(NATIONS)
    return {"nation": nation,
            "region": NATION_REGION[nation],
            "type": "%s %s %s" % (r.choice(TYPE_SYLLABLE_1),
                                  r.choice(TYPE_SYLLABLE_2),
                                  r.choice(TYPE_SYLLABLE_3))}


def _q09(r):
    return {"color": r.choice(COLORS)}


def _q10(r):
    return {"date": r.choice(_month_range((1993, 2), (1995, 1)))}


def _q11(r):
    return {"nation": r.choice(NATIONS), "fraction": Q11_FRACTION}


def _q12(r):
    m1, m2 = r.sample(SHIPMODES, 2)
    y = r.randint(1993, 1997)
    return {"shipmode1": m1, "shipmode2": m2, "date": _D(y, 1, 1)}


def _q13(r):
    return {"word1": r.choice(["special", "pending", "unusual", "express"]),
            "word2": r.choice(["packages", "requests", "accounts", "deposits"])}


def _q14(r):
    return {"date": r.choice(_month_range((1993, 1), (1997, 12)))}


def _q15(r):
    return {"date": r.choice(_month_range((1993, 1), (1997, 10)))}


def _q16(r):
    return {"brand": r.choice(BRANDS),
            "type": "%s %s" % (r.choice(TYPE_SYLLABLE_1),
                               r.choice(TYPE_SYLLABLE_2)),
            "sizes": sorted(r.sample(range(1, 51), 8))}


def _q17(r):
    return {"brand": r.choice(BRANDS), "container": r.choice(CONTAINERS)}


def _q18(r):
    return {"quantity": r.randint(312, 315)}


def _q19(r):
    b1, b2, b3 = (r.choice(BRANDS) for _ in range(3))
    return {"brand1": b1, "brand2": b2, "brand3": b3,
            "quantity1": r.randint(1, 10),
            "quantity2": r.randint(10, 20),
            "quantity3": r.randint(20, 30)}


def _q20(r):
    y = r.randint(1993, 1997)
    return {"color": r.choice(COLORS), "date": _D(y, 1, 1),
            "nation": r.choice(NATIONS)}


def _q21(r):
    return {"nation": r.choice(NATIONS)}


def _q22(r):
    return {"country_codes": sorted(r.sample([f"{c:02d}" for c in range(10, 35)], 7))}


_GEN = {
    1: _q01, 2: _q02, 3: _q03, 4: _q04, 5: _q05, 6: _q06, 7: _q07, 8: _q08,
    9: _q09, 10: _q10, 11: _q11, 12: _q12, 13: _q13, 14: _q14, 15: _q15,
    16: _q16, 17: _q17, 18: _q18, 19: _q19, 20: _q20, 21: _q21, 22: _q22,
}

# The TPC-H validation-set instance for each query - what the harness measured
# before this module existed. Pinned as set 0; see the module docstring.
_VALIDATION = {
    1:  {"date": _D(1998, 9, 2), "delta": 90},
    2:  {"size": 15, "type_suffix": "BRASS", "region": "EUROPE"},
    3:  {"segment": "BUILDING", "date": _D(1995, 3, 15)},
    4:  {"date": _D(1993, 7, 1)},
    5:  {"region": "ASIA", "date": _D(1994, 1, 1)},
    6:  {"date": _D(1994, 1, 1), "discount": 0.06, "quantity": 24},
    7:  {"nation1": "FRANCE", "nation2": "GERMANY"},
    8:  {"nation": "BRAZIL", "region": "AMERICA", "type": "ECONOMY ANODIZED STEEL"},
    9:  {"color": "green"},
    10: {"date": _D(1993, 10, 1)},
    11: {"nation": "GERMANY", "fraction": Q11_FRACTION},
    12: {"shipmode1": "MAIL", "shipmode2": "SHIP", "date": _D(1994, 1, 1)},
    13: {"word1": "special", "word2": "requests"},
    14: {"date": _D(1995, 9, 1)},
    15: {"date": _D(1996, 1, 1)},
    # The size list is kept in the specification's own order rather than
    # sorted: an IN list's order is semantically irrelevant but textually
    # visible, and set 0 has to reproduce the statement this harness has always
    # emitted, byte for byte. Sets 1..7 are sorted, which is only cosmetic.
    16: {"brand": "Brand#45", "type": "MEDIUM POLISHED",
         "sizes": [49, 14, 23, 45, 19, 3, 36, 9]},
    17: {"brand": "Brand#23", "container": "MED BOX"},
    18: {"quantity": 300},
    19: {"brand1": "Brand#12", "brand2": "Brand#23", "brand3": "Brand#34",
         "quantity1": 1, "quantity2": 10, "quantity3": 20},
    20: {"color": "forest", "date": _D(1994, 1, 1), "nation": "CANADA"},
    21: {"nation": "SAUDI ARABIA"},
    22: {"country_codes": ["13", "31", "23", "29", "30", "18", "17"]},
}


# Queries whose substitution domain is too small to yield eight distinct
# instances. Q18's QUANTITY has four legal values, so eight blocks must reuse
# them; that is a property of the specification, not a generator bug, and it is
# declared here rather than discovered as a surprise in the raw file.
_SMALL_DOMAIN = {18}

# Q18 is the one query whose qualification-query value falls OUTSIDE its own
# substitution range: the specification's validation instance is
# QUANTITY = 300, while clause 2.18.3 draws QUANTITY from [312, 315]. Set 0 is
# therefore not exchangeable with sets 1..7 for Q18 alone - 300 admits far more
# order groups than 312 does, so Q18's spread across the eight blocks contains
# a real parameter effect that the other 21 queries do not have. Kept at 300
# anyway, because every measurement this project has taken used 300 and block 0
# is what makes the new campaign comparable to the old one. Reported in the
# analysis plan; not silently averaged away.
_SET0_OUTSIDE_RANGE = {18}


def _build():
    sets = {}
    for q, gen in _GEN.items():
        # One stream per query, so adding or removing a query never shifts
        # another query's draws. SEED * 100 + q keeps the streams far apart.
        r = _random.Random(SEED * 100 + q)
        chosen = [dict(_VALIDATION[q])]
        attempts = 0
        while len(chosen) < N_SETS:
            cand = gen(r)
            attempts += 1
            # Eight blocks must be eight parameter instances, not five
            # instances with three repeats - a duplicate would make two blocks
            # measure the same plan and would look like low variance rather
            # than like a generator that gave up.
            if cand not in chosen:
                chosen.append(cand)
            elif attempts > 500:
                if q not in _SMALL_DOMAIN:
                    raise AssertionError(
                        f"Q{q:02d}: 500 draws without {N_SETS} distinct "
                        "parameter sets, and its domain is not declared small. "
                        "Either the generator is drawing from too narrow a "
                        "range or _SMALL_DOMAIN needs to say so explicitly."
                    )
                chosen.append(cand)
        sets[q] = chosen
    return sets


PARAM_SETS = _build()


def _build_warmup():
    """One extra parameter instance per query, used only by the warmup block.

    The warmup exists to fill caches and compile plans so that block 1 is not
    systematically slower than block 8. If it used one of the eight measured
    sets, it would warm that set's own pages and predicates specifically, and
    the block sharing it would start warmer than the other seven - a warmup
    that removes a bias from the cell while introducing one between its blocks.
    A ninth instance, never measured, warms the query without privileging any
    block.

    Drawn from a separate stream so adding it does not shift the eight.
    """
    out = {}
    for q, gen in _GEN.items():
        r = _random.Random(SEED * 100 + q + 7919)   # a prime offset, far away
        for _ in range(200):
            cand = gen(r)
            if cand not in PARAM_SETS[q]:
                out[q] = cand
                break
        else:
            # Q18 has four legal values and eight blocks, so a distinct ninth
            # is impossible. Declared, not silently reused.
            out[q] = gen(r)
    return out


WARMUP_SETS = _build_warmup()


def warmup_params(qnum):
    """The warmup block's parameters. Never appears in a measured row."""
    return expand(qnum, WARMUP_SETS[qnum])


# The width of each query's date range, in months, taken from the
# specification. It lives here, once, because it is the value defect C9 got
# wrong: four Oracle modules carried Q04's three-month window instead of their
# own. A range end is always derived from its start and this table, so a
# parameter set cannot carry a start and an end that disagree.
DATE_WIDTH_MONTHS = {4: 3, 5: 12, 6: 12, 10: 3, 12: 12, 14: 1, 15: 3, 20: 12}

# Keys carried for provenance that no query text uses. Q01's DELTA is the
# specification's actual substitution parameter - the predicate date is
# 1998-12-01 minus DELTA days - so the set records the draw as well as the date
# it produced, and only the date reaches a query. A test asking "does changing
# this key change the emitted work" must know that DELTA legitimately does not.
NON_SUBSTITUTING = {"delta"}


def expand(qnum, p):
    """One parameter set plus every value derived from it.

    Both frameworks call this, so the derived values cannot drift apart the way
    two hand-maintained copies would. Keys added:

      date_end      the end of the date range, from DATE_WIDTH_MONTHS
      disc_lo/hi    Q06's DISCOUNT +/- 0.01, as two-place Decimals
      sizes_sql     Q16's size list rendered for an IN clause
      like_pattern  Q13's '%word1%word2%'
    """
    from decimal import Decimal
    e = dict(p)
    if qnum in DATE_WIDTH_MONTHS and "date" in e:
        e["date_end"] = add_months(e["date"], DATE_WIDTH_MONTHS[qnum])
    if qnum == 6:
        # Decimal from a two-place string, not from float arithmetic:
        # Decimal(0.06 - 0.01) is 0.049999999999999996 and would bind a bound
        # the specification does not define.
        e["disc_lo"] = Decimal("%.2f" % round(e["discount"] - 0.01, 2))
        e["disc_hi"] = Decimal("%.2f" % round(e["discount"] + 0.01, 2))
    if qnum == 16:
        e["sizes_sql"] = ", ".join(str(x) for x in e["sizes"])
    if qnum == 13:
        e["like_pattern"] = "%%%s%%%s%%" % (e["word1"], e["word2"])
    if qnum == 22:
        # Two renderings of one list, because the two hand-written baselines
        # have always spaced their IN clauses differently and the emitted text
        # is the measurement. The list itself is defined once.
        e["codes_sql"] = ",".join("'%s'" % c for c in e["country_codes"])
        e["codes_sql_spaced"] = ", ".join("'%s'" % c for c in e["country_codes"])
    return e


def params_of(qnum, set_index=0):
    """The substitution parameters for one query and one block.

    set_index is taken modulo N_SETS, so a caller running more than eight
    blocks cycles rather than raising - but the campaign runs exactly eight.
    """
    return expand(qnum, PARAM_SETS[qnum][set_index % N_SETS])


# Kept as the historical name; resolve() is what the query modules call.
params = params_of


def resolve(qnum, params=None):
    """Turn whatever a caller passed into one expanded parameter set.

    Accepts None (meaning set 0, the TPC-H validation instance), an integer
    block index, or a set that is already built. Callers in the query modules
    take `params=None` so that every entry point keeps working unchanged for
    code written before the eight-block protocol - the validator, the ad-hoc
    scripts, and anything that just wants "the" TPC-H query.
    """
    if params is None:
        return params_of(qnum, 0)
    if isinstance(params, int):
        return params_of(qnum, params)
    return expand(qnum, params)


def set_id(qnum, set_index):
    """The identifier recorded on every raw measurement row."""
    return f"q{qnum:02d}s{set_index % N_SETS}"


if __name__ == "__main__":
    for q in sorted(PARAM_SETS):
        print(f"Q{q:02d}")
        for i, p in enumerate(PARAM_SETS[q]):
            print(f"  s{i}: {p}")
