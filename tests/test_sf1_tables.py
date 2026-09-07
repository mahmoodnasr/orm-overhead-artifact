"""The paper's noise table must report the campaign's own gate verdicts.

Section 5 of the paper states that four of the eight campaigns miss a
pre-registered bound and sends the reader to Section 7 for the causes. Both
sentences are only worth anything if the table beside them scores the campaigns
the way `pilot_gate.py` scored them at the time, because that gate is what wrote
`results/sf1/measurements/.gate_failures` and what the disclosures in
docs/CORRECTIONS.md quote.

Two ways that agreement can break, and both have already happened once:

  * the percentile. The gate interpolates between the two neighbouring order
    statistics; an index-based p90 puts SQL Server indexed at 23.13% where the
    gate says 23.50%. Neither number changes the verdict here, but a table that
    disagrees with the artifact in the third digit invites the reader to check
    the one place the two do differ materially.

  * the ceiling. SQL Server's indexed campaign ran at the 2700 s retry ceiling
    of ANALYSIS_PLAN section 8.3, and most of its rows record the bare string
    `client-side` from before C42 was fixed. Scoring it against the 900 s
    default fails it at 4x on a bound it passes at 12x, which is C42 itself,
    reintroduced one level further out in the very table that reports it.

Run:  python3 -m pytest tests/test_sf1_tables.py -q
"""
import os
import statistics
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "4-analysis"))
sys.path.insert(0, os.path.join(REPO, "scripts", "utils"))

import sf1_tables                                             # noqa: E402
from pilot_gate import percentile                             # noqa: E402

MEAS = os.path.join(REPO, "results", "sf1", "measurements")

# What the gate reported for each campaign, transcribed from
#   python3 scripts/4-analysis/pilot_gate.py <file> [--ceiling 2700]
# run on the committed SF1 measurements. Ceiling 2700 for the two SQL Server
# campaigns, the default elsewhere.
GATE = {
    ("postgresql", "indexed"):     dict(n=84, median=1.53, p90=4.07, tail=0.0),
    ("postgresql", "non-indexed"): dict(n=71, median=0.89, p90=2.04, tail=0.0),
    ("mysql", "indexed"):          dict(n=84, median=1.74, p90=4.53, tail=0.0),
    ("mysql", "non-indexed"):      dict(n=75, median=0.79, p90=2.51, tail=0.0),
    ("sqlserver", "indexed"):      dict(n=83, median=2.94, p90=23.50, tail=8.4),
    ("sqlserver", "non-indexed"):  dict(n=83, median=3.88, p90=17.54, tail=1.2),
    ("oracle", "indexed"):         dict(n=83, median=1.91, p90=8.48, tail=6.0),
    ("oracle", "non-indexed"):     dict(n=83, median=1.38, p90=9.89, tail=0.0),
}

# The four disclosed in .gate_failures, and which bound each one misses.
EXPECTED_FAILURES = {
    ("sqlserver", "indexed"):     {"p90", "tail", "margin"},
    ("sqlserver", "non-indexed"): {"p90"},
    ("oracle", "indexed"):        {"tail"},
    ("oracle", "non-indexed"):    {"margin"},
}

# The ceiling each campaign is scored against, in seconds. A campaign gets the
# value its own rows carry only when every row carries one; otherwise it gets
# ANALYSIS_PLAN section 8.3's declared default (C45). SQL Server indexed is the
# case that distinction was written for: 1,480 of its rows record the bare
# string `client-side` and 52 record `client-side:2700`, so it is scored at
# 900 s and fails the margin at 3.87x. Its non-indexed sibling records 2700 s on
# every row and keeps it.
EXPECTED_CEILING = {
    ("postgresql", "indexed"): 900.0, ("postgresql", "non-indexed"): 900.0,
    ("mysql", "indexed"): 900.0, ("mysql", "non-indexed"): 900.0,
    ("sqlserver", "indexed"): 900.0, ("sqlserver", "non-indexed"): 2700.0,
    ("oracle", "indexed"): 900.0, ("oracle", "non-indexed"): 900.0,
}

pytestmark = pytest.mark.skipif(
    not os.path.isdir(MEAS), reason="SF1 measurements not present")


@pytest.fixture(scope="module")
def computed():
    cvs, slowest, ceiling = sf1_tables.path_cvs(MEAS)
    return cvs, slowest, ceiling


@pytest.mark.parametrize("campaign", sorted(GATE))
def test_cv_matches_the_gate(computed, campaign):
    """Median, p90 and tail share, to the precision the paper prints."""
    cvs, _slowest, _ceiling = computed
    v = cvs.get(campaign)
    assert v, f"no CV distribution for {campaign}"
    want = GATE[campaign]
    assert len(v) == want["n"]
    assert statistics.median(v) == pytest.approx(want["median"], abs=0.005)
    assert percentile(sorted(v), 0.90) == pytest.approx(want["p90"], abs=0.005)
    share = 100.0 * sum(1 for x in v if x > sf1_tables.CV_TAIL_THRESHOLD) / len(v)
    assert share == pytest.approx(want["tail"], abs=0.05)


@pytest.mark.parametrize("campaign", sorted(EXPECTED_CEILING))
def test_ceiling_is_read_not_assumed(computed, campaign):
    """C42 and C45: the ceiling comes off the rows, and only if all of them
    carry it. SQL Server non-indexed records 2700 s throughout and keeps it;
    SQL Server indexed records it on 52 rows of 1,532 and does not."""
    _cvs, _slowest, ceiling = computed
    assert ceiling.get(campaign) == EXPECTED_CEILING[campaign]


def test_the_four_disclosed_failures_are_exactly_these(computed):
    """No campaign quietly joins or leaves the disclosed set.

    Section 5 says four analytical campaigns and Section 7 explains four causes.
    A fifth failure, or a fourth that turned into a pass, makes both sentences
    wrong. The set of campaigns is fixed here and so is which bounds each one
    misses, because C45 changed the second without changing the first.
    """
    cvs, slowest, ceiling = computed
    failures = {}
    for campaign, v in cvs.items():
        missed = set()
        if statistics.median(v) > sf1_tables.CV_MEDIAN_MAX:
            missed.add("median")
        if percentile(sorted(v), 0.90) > sf1_tables.CV_P90_MAX:
            missed.add("p90")
        share = 100.0 * sum(1 for x in v if x > sf1_tables.CV_TAIL_THRESHOLD) / len(v)
        if share > sf1_tables.CV_TAIL_SHARE_MAX:
            missed.add("tail")
        worst, _where = slowest[campaign]
        cap = ceiling.get(campaign)
        if cap and worst > 0 and cap / worst < sf1_tables.MARGIN_MIN:
            missed.add("margin")
        if missed:
            failures[campaign] = missed
    assert failures == EXPECTED_FAILURES


def test_gate_failures_file_agrees(computed):
    """The disclosed set matches what the campaign scripts wrote down."""
    path = os.path.join(MEAS, ".gate_failures")
    if not os.path.exists(path):
        pytest.skip(".gate_failures not present")
    recorded = {tuple(line.split()) for line in
                open(path).read().split("\n") if line.strip()}
    assert recorded == set(EXPECTED_FAILURES)


def test_sqlserver_indexed_is_scored_against_the_declared_default():
    """C45, asserted so a later refactor cannot walk back into it.

    2700 s would carry this campaign past the margin, and 52 of its 1,532 rows
    record it. The other 1,480 record the bare string `client-side`. A campaign
    that did not write down the bound it ran under is scored against the one
    section 8.3 declares, which is 900 s, and it fails the margin at 3.87x.

    The opposite assertion stood here while the paper reported a pass. Both
    cannot be right, and the one that reads a bound off the minority of rows
    written after the run is the one that is not.
    """
    _cvs, slowest, ceiling = sf1_tables.path_cvs(MEAS)
    worst, _where = slowest[("sqlserver", "indexed")]
    assert ceiling[("sqlserver", "indexed")] == sf1_tables.DEFAULT_CEILING_S
    assert ceiling[("sqlserver", "indexed")] / worst < sf1_tables.MARGIN_MIN
    assert 2700.0 / worst >= sf1_tables.MARGIN_MIN


def test_transactional_rows_carry_a_range_and_not_a_bootstrap_interval(tmp_path):
    """C46. Five clusters cannot support a percentile interval.

    The bootstrap resamples clusters with replacement, so five transactions give
    5**5 resamples whose medians land on a few dozen distinct values. Printing
    two of them as `[+63.1, +144.9]` advertises a precision the design has not
    got, in the one column of that table still asserting conventional precision
    on the transactional half.

    The guard is on the shape rather than the numbers: the analytical rows must
    keep an interval and the transactional rows must not have one. Enumerating
    the reachable medians here would re-derive the register entry rather than
    test the table.
    """
    import random
    import re

    ratios, _censored = sf1_tables.load_blocks(MEAS)
    cells = sf1_tables.cell_estimates(ratios)
    tpcc = sf1_tables.load_tpcc(MEAS)
    sf1_tables.t_headline(cells, tpcc, str(tmp_path), random.Random(0))

    rows = [l for l in open(os.path.join(str(tmp_path), "tab_headline.tex"))
            if l.startswith(("TPC-H", "TPC-C"))]
    assert len(rows) == 4, rows
    for row in rows:
        ci = row.split("&")[2].strip()
        if row.startswith("TPC-H"):
            assert re.fullmatch(r"\[[+-][\d.]+, [+-][\d.]+\]", ci), ci
        else:
            assert re.fullmatch(r"[+-][\d.]+ to [+-][\d.]+", ci), ci


def test_the_same_statistic_is_the_same_number_in_both_tables(tmp_path):
    """C47. The headline and the sensitivity table's first row are one figure.

    `tab_sensitivity`'s "none (as reported)" row removes no group, so it is by
    construction the pooled median and interval that `tab_headline` prints. They
    disagreed: [+0.5, +3.6] against [+0.5, +3.7]. One `random.Random(SEED)` was
    threaded through the whole run, so a table's draws depended on how many
    draws the tables built before it had taken.

    `clustered_bootstrap` now seeds from the sample. The guard is that the two
    agree, not that either equals a transcribed constant, because the point is
    that one statistic has one value wherever the paper prints it.
    """
    import random
    import re

    ratios, _censored = sf1_tables.load_blocks(MEAS)
    cells = sf1_tables.cell_estimates(ratios)
    tpcc = sf1_tables.load_tpcc(MEAS)
    out = str(tmp_path)
    sf1_tables.t_headline(cells, tpcc, out, random.Random(0))
    sf1_tables.t_sensitivity(cells, out, random.Random(0))

    head = open(os.path.join(out, "tab_headline.tex")).read()
    sens = open(os.path.join(out, "tab_sensitivity.tex")).read()
    row = re.search(r"none \(as reported\) & (\S+) & (\[[^\]]+\]) & \d+ & "
                    r"(\S+) & (\[[^\]]+\])", sens)
    assert row, sens
    for label, med, ci in (("Django", row.group(1), row.group(2)),
                           ("SQLAlchemy", row.group(3), row.group(4))):
        m = re.search(r"TPC-H, %s & (\S+) & (\[[^\]]+\])" % label, head)
        assert m, head
        assert m.group(1) == med, (label, m.group(1), med)
        assert m.group(2) == ci, (label, m.group(2), ci)
