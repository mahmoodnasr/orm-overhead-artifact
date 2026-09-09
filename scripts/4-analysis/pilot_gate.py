#!/usr/bin/env python3
"""Score a phase 6 pilot against ANALYSIS_PLAN.md section 8, and exit non-zero
if it fails.

The thresholds this applies were written into ANALYSIS_PLAN.md **before** the
pilot ran, which is the only thing that makes them capable of failing. A bound
chosen after seeing the output is a description of that output. This script
therefore contains no judgement of its own: every number it compares against is
quoted from section 8, and changing one here without changing it there is a
defect, not a tuning.

    python3 scripts/4-analysis/pilot_gate.py results/sf1/pilot/postgresql_indexed.csv

What it checks, in the plan's own order:

  8.1  noise        median CV <= 5%, p90 CV <= 15%, share above 25% <= 5%
  8.2  completeness zero executions failing for a reason not declared in 6
  8.3  ceiling      every non-censored path finishes with >= 5x margin

and two things the plan requires be verified in the raw file rather than
intended: that the Williams counterbalancing actually happened, and that every
block used its own parameter set. A design is only counterbalanced if the rows
say so.

It also prints the estimand itself - the median within-block paired log ratio,
per framework, per cell - because a gate that reports only variance tells you
the run was quiet without telling you whether it measured anything.
"""

import argparse
import csv
import math
import os
import re
import statistics
import sys
from collections import defaultdict

# --- ANALYSIS_PLAN.md section 8. Quoted, not chosen. --------------------------
CV_MEDIAN_MAX = 5.0  # 8.1
CV_P90_MAX = 15.0  # 8.1
CV_TAIL_FRACTION_MAX = 5.0  # 8.1, share of paths above CV_TAIL_CV
CV_TAIL_CV = 25.0  # 8.1
CEILING_MARGIN_MIN = 5.0  # 8.3
DEFAULT_CEILING_S = 900.0  # 8.3
N_BLOCKS = 8  # section 2
N_PATHS = 4

# Section 2.1: Q18's set 0 falls outside its own substitution range, so its
# across-block spread carries a parameter effect the other queries do not have
# and it is excluded from the CV distribution. It is not in the pilot's six
# queries, but the rule belongs with the threshold, not with the query list.
CV_EXCLUDED_QUERIES = {"Q18"}

# Statuses that mean "this path produced no timing, and the plan says why".
# A ceiling timeout is a one-sided bound under section 6; an inexpressible
# query is C17, a result the study reports rather than a gap. Neither is a
# failure, and neither belongs in the CV distribution or the ceiling margin.
DECLARED_ABSENT = ("timeout", "not_expressible")

PASS, FAIL, INFO = "pass", "FAIL", "----"


def parse_ceiling(raw):
    """Seconds from whatever the server said when the ceiling was read back.

    PostgreSQL answers SHOW statement_timeout in its own duration syntax
    ('15min', '900s', '900000ms'), MySQL in integer milliseconds, and Oracle and
    SQL Server bound the client round trip instead and report 'client-side'.
    Returning None for the last case is deliberate: the margin is then computed
    against the campaign default rather than silently against zero.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s.startswith("client-side:"):
        # The harness records the client-side bound it is actually enforcing.
        # Returning None here sent the gate to its 900 s default and scored a
        # 2700 s run against the wrong ceiling.
        try:
            return float(s.split(":", 1)[1])
        except ValueError:
            return None
    if not s or s in ("client-side", "0"):
        return None
    if s.startswith("unreadable"):
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s|min|h)?", s)
    if not m:
        return None
    value, unit = float(m.group(1)), (m.group(2) or "ms")
    return value * {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0}[unit]


def cv(xs):
    if len(xs) < 2:
        return None
    mean = statistics.mean(xs)
    return (statistics.stdev(xs) / mean * 100.0) if mean else None


def percentile(sorted_xs, p):
    if not sorted_xs:
        return None
    k = (len(sorted_xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_xs[int(k)]
    return sorted_xs[lo] * (hi - k) + sorted_xs[hi] * (k - lo)


def line(status, label, detail=""):
    mark = {PASS: "  ok  ", FAIL: "  FAIL", INFO: "      "}[status]
    print(f"{mark}  {label}" + (f"   {detail}" if detail else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument(
        "--ceiling",
        type=float,
        default=DEFAULT_CEILING_S,
        help="campaign ceiling in seconds, used where the server "
        "reports a client-side bound it cannot read back",
    )
    args = ap.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"no such file: {args.csv_path}", file=sys.stderr)
        return 2

    rows = list(csv.DictReader(open(args.csv_path)))
    if not rows:
        print("empty pilot file", file=sys.stderr)
        return 2

    measured = [r for r in rows if r.get("is_warmup") == "0"]
    warmup = [r for r in rows if r.get("is_warmup") not in ("0", None)]

    print("=" * 78)
    print(f"PILOT GATE   {args.csv_path}")
    print("=" * 78)
    meta = lambda k: ", ".join(sorted({r.get(k, "") for r in rows}))
    print(
        f"  campaign   {meta('campaign_id')}   host {meta('host')}   "
        f"scale factor {meta('scale_factor')}"
    )
    print(f"  systems    {meta('dbms')} / {meta('schema_config')}")
    print(f"  queries    {meta('query_id')}")
    print(f"  rows       {len(measured)} measured, {len(warmup)} warmup")
    print()

    failures = []

    # --- integrity: the design has to be in the data, not just in the script --
    print(
        "DESIGN INTEGRITY  (plan section 5: verified in the raw files, not just intended)"
    )
    # Keyed off every row, not only the measured ones. A cell whose four paths
    # all exceeded the ceiling in the cell warmup produces no measured row at
    # all, so building this from `measured` made a fully censored cell invisible
    # to the shape check rather than checked and reported - the one shape that
    # most needs saying out loud.
    cells = defaultdict(list)
    for r in rows:
        cells[(r["query_id"], r["dbms"], r["schema_config"])].append(r)

    bad_shape, bad_positions, bad_paramsets, bad_sequences = [], [], [], []
    censored_cells = []
    for key, allrs in sorted(cells.items()):
        rs = [r for r in allrs if r.get("is_warmup") == "0"]
        # A path censored in the cell warmup is excluded from every block by
        # run_block.py, by design: section 6 records it as a one-sided bound
        # rather than spending 8 x 900 s re-proving it. So the cell's expected
        # width is four minus the censored paths, not four. Requiring 4 flatly
        # reported PostgreSQL non-indexed Q13 - django/orm over the ceiling,
        # the other three paths complete - as a broken design, which would have
        # excluded a whole campaign over a correctly recorded result.
        censored_paths = {
            f"{r['framework']}/{r['path']}"
            for r in allrs
            if r.get("is_warmup") == "1" and r["status"] in DECLARED_ABSENT
        }
        want_paths = N_PATHS - len(censored_paths)
        if want_paths == 0:
            censored_cells.append(key[0])
            if rs:
                bad_shape.append(
                    f"{key[0]}: fully censored but has {len(rs)} measured rows"
                )
            continue
        blocks = defaultdict(list)
        for r in rs:
            blocks[int(r["block"])].append(r)
        if len(blocks) != N_BLOCKS or any(
            len(v) != want_paths for v in blocks.values()
        ):
            bad_shape.append(
                f"{key[0]}: {len(blocks)} blocks"
                + (
                    f" x {want_paths} uncensored paths expected"
                    if censored_paths
                    else ""
                )
            )
        if censored_paths:
            censored_cells.append(f"{key[0]} ({', '.join(sorted(censored_paths))})")
        # Every path once in every position, across the eight blocks.
        by_position = defaultdict(list)
        for r in rs:
            by_position[int(r["position"])].append(f"{r['framework']}/{r['path']}")
        for pos, names in by_position.items():
            if len(set(names)) < 2:
                bad_positions.append(f"{key[0]} position {pos}")
        # One parameter set per block, and eight distinct ones per cell.
        psets = {int(r["block"]): r["param_set_id"] for r in rs}
        if len(set(psets.values())) != N_BLOCKS:
            bad_paramsets.append(f"{key[0]}: {len(set(psets.values()))} distinct sets")
        seqs = sorted(
            int(r["sequence_id"]) for r in {int(r["block"]): r for r in rs}.values()
        )
        if sorted(seqs) != [0, 0, 1, 1, 2, 2, 3, 3]:
            bad_sequences.append(f"{key[0]}: {seqs}")

    for label, bad in (
        (
            f"every cell has {N_BLOCKS} blocks x {N_PATHS} paths, "
            f"less any censored in warmup",
            bad_shape,
        ),
        ("every path appears in every sequence position", bad_positions),
        (f"{N_BLOCKS} distinct parameter sets per cell", bad_paramsets),
        ("each Williams sequence used exactly twice", bad_sequences),
    ):
        line(PASS if not bad else FAIL, label, "" if not bad else "; ".join(bad[:3]))
        if bad:
            failures.append(label)
    if censored_cells:
        line(
            INFO,
            f"{len(censored_cells)} cell(s) censored in warmup",
            "; ".join(censored_cells),
        )
    print()

    # --- 8.2 completeness ----------------------------------------------------
    print("SECTION 8.2  COMPLETENESS   (pilot bound: zero unplanned failures)")
    statuses = defaultdict(int)
    for r in measured:
        statuses[r["status"]] += 1
    unplanned = [r for r in measured if r["status"] not in ("ok",) + DECLARED_ABSENT]
    censored = [r for r in measured if r["status"] in DECLARED_ABSENT]
    line(INFO, "statuses", ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    line(
        PASS if not unplanned else FAIL,
        "zero executions failed for an undeclared reason",
        ""
        if not unplanned
        else f"{len(unplanned)}: "
        + "; ".join(sorted({r["note"][:60] for r in unplanned})[:2]),
    )
    if unplanned:
        failures.append("8.2 completeness")
    if censored:
        line(
            INFO,
            f"{len(censored)} censored execution(s)",
            "handled as one-sided bounds under section 6",
        )
    print()

    # --- 8.1 noise -----------------------------------------------------------
    print(
        f"SECTION 8.1  NOISE   (median CV <= {CV_MEDIAN_MAX}%, "
        f"p90 <= {CV_P90_MAX}%, share > {CV_TAIL_CV}% <= {CV_TAIL_FRACTION_MAX}%)"
    )
    paths = defaultdict(list)
    for r in measured:
        if r["status"] != "ok" or r["query_id"] in CV_EXCLUDED_QUERIES:
            continue
        paths[
            (r["query_id"], r["dbms"], r["schema_config"], r["framework"], r["path"])
        ].append(float(r["elapsed_s"]))

    cvs = []
    per_path_cv = {}
    for key, xs in paths.items():
        c = cv(xs)
        if c is not None:
            cvs.append(c)
            per_path_cv[key] = c
    cvs_sorted = sorted(cvs)

    if not cvs_sorted:
        line(FAIL, "no path had enough completed blocks to compute a CV")
        failures.append("8.1 noise")
    else:
        med = statistics.median(cvs_sorted)
        p90 = percentile(cvs_sorted, 0.90)
        tail = sum(1 for c in cvs_sorted if c > CV_TAIL_CV) / len(cvs_sorted) * 100
        line(
            PASS if med <= CV_MEDIAN_MAX else FAIL,
            f"median CV {med:5.2f}%",
            f"bound {CV_MEDIAN_MAX}%",
        )
        line(
            PASS if p90 <= CV_P90_MAX else FAIL,
            f"p90 CV    {p90:5.2f}%",
            f"bound {CV_P90_MAX}%",
        )
        line(
            PASS if tail <= CV_TAIL_FRACTION_MAX else FAIL,
            f"share above {CV_TAIL_CV}%: {tail:4.1f}%",
            f"bound {CV_TAIL_FRACTION_MAX}%",
        )
        if med > CV_MEDIAN_MAX or p90 > CV_P90_MAX or tail > CV_TAIL_FRACTION_MAX:
            failures.append("8.1 noise")
        line(
            INFO,
            f"n = {len(cvs_sorted)} paths",
            f"min {cvs_sorted[0]:.2f}%  max {cvs_sorted[-1]:.2f}%",
        )
        worst = sorted(per_path_cv.items(), key=lambda kv: -kv[1])[:3]
        for (q, _d, _s, fw, p), c in worst:
            line(INFO, f"  noisiest: {q} {fw}/{p}", f"CV {c:.2f}%")
    print()

    # --- 8.3 ceiling ---------------------------------------------------------
    print(
        f"SECTION 8.3  CEILING   (margin >= {CEILING_MARGIN_MIN}x on every "
        "non-censored path)"
    )
    reported = {parse_ceiling(r.get("ceiling_s")) for r in measured}
    reported.discard(None)
    ceiling = min(reported) if reported else args.ceiling
    source = (
        "read back off the server"
        if reported
        else f"campaign default, server reports a client-side bound"
    )
    line(INFO, f"ceiling {ceiling:.0f} s", source)

    completed = [float(r["elapsed_s"]) for r in measured if r["status"] == "ok"]
    if completed:
        observed_max = max(completed)
        margin = ceiling / observed_max if observed_max else float("inf")
        ok = margin >= CEILING_MARGIN_MIN
        line(
            PASS if ok else FAIL,
            f"slowest completed execution {observed_max:.3f} s",
            f"margin {margin:.0f}x, bound {CEILING_MARGIN_MIN}x",
        )
        if not ok:
            failures.append("8.3 ceiling")
        slowest = max(
            (
                (r["query_id"], r["framework"], r["path"], float(r["elapsed_s"]))
                for r in measured
                if r["status"] == "ok"
            ),
            key=lambda t: t[3],
        )
        line(INFO, f"  slowest is {slowest[0]} {slowest[1]}/{slowest[2]}")
    print()

    # --- the estimand, so the gate says what was measured, not only how quietly
    print("ESTIMAND   (section 1: median within-block paired log ratio per framework)")
    per_cell = defaultdict(lambda: defaultdict(dict))
    for r in measured:
        if r["status"] != "ok":
            continue
        per_cell[(r["query_id"], r["dbms"], r["schema_config"])][
            (r["framework"], int(r["block"]))
        ][r["path"]] = float(r["elapsed_s"])

    print(f"    {'cell':22s} {'Django':>18s} {'SQLAlchemy':>18s}")
    for cell, blocks in sorted(per_cell.items()):
        out = {}
        for fw in ("django", "sqlalchemy"):
            ratios = [
                math.log(v["orm"] / v["sql"])
                for (f, _b), v in blocks.items()
                if f == fw and "orm" in v and "sql" in v and v["sql"] > 0
            ]
            out[fw] = statistics.median(ratios) if ratios else None
        fmt = lambda t: (
            "      n/a"
            if t is None
            else f"{(math.exp(t) - 1) * 100:+7.1f}%  ({t:+.3f})"
        )
        print(
            f"    {cell[0] + ' ' + cell[1]:22s} {fmt(out['django']):>18s} "
            f"{fmt(out['sqlalchemy']):>18s}"
        )
    print()
    print("    Reported as percentage overhead and as the log ratio itself. The")
    print("    median is taken over the eight within-block ratios, never over a")
    print("    ratio of medians - the two differ and only the first respects the")
    print("    pairing (section 2).")
    print()

    # --- 8.4 input -----------------------------------------------------------
    if cvs_sorted:
        print("SECTION 8.4  MICROBENCHMARK REPLICATION   (input, not a gate)")
        typical = statistics.median(cvs_sorted)
        n_needed = math.ceil((1.96 * typical / 10.0) ** 2)
        line(
            INFO,
            f"typical within-path CV {typical:.2f}%",
            f"=> n >= {max(n_needed, 100)} per block for a 10% relative "
            f"half-width (floor 100, cap 2000)",
        )
        print()

    print("=" * 78)
    if failures:
        print(f"NO-GO — {len(failures)} bound(s) missed: {', '.join(failures)}")
        print("Section 8.5: diagnose before any primary-campaign execution. If the")
        print("protocol changes, every pilot measurement is excluded from the")
        print("campaign, and the miss and its fix are written into the analysis")
        print("plan and docs/CORRECTIONS.md.")
        return 1
    print("GO — every bound in sections 8.1 to 8.3 holds, and the design is")
    print("present in the raw rows rather than only in the runner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
