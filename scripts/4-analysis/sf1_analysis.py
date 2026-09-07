#!/usr/bin/env python3
"""Tables and figures for the SF1 campaign, from the block measurements.

    python3 scripts/4-analysis/sf1_analysis.py --scale 1

Why this exists rather than generate_figures.py: that script reads
`results/raw/summary_statistics.csv`, one row per cell with a median already
taken. The SF1 campaign writes one row per *execution* under the block
protocol, and the quantity the study reports is not recoverable from a table of
medians.

The estimand, from ANALYSIS_PLAN.md section 1
---------------------------------------------
For a cell (dbms, schema, query, framework), each of the eight blocks runs all
four paths once, close together, on the same substitution parameters. The
overhead is the **median over blocks of the within-block log ratio**

    theta = median_b [ log( t_orm(b) / t_sql(b) ) ]

reported as exp(theta) - 1. It is not median(t_orm) / median(t_sql). The two
differ whenever the blocks differ from each other, which is the normal case
because each block draws its own parameters, and only the first respects the
pairing the block design exists to create. C34 is the entry about the day that
distinction was found missing from the results builder.

Uncertainty is a **query-clustered bootstrap**: queries are resampled with
replacement rather than cells, because the 22 queries of a system are not 22
independent draws - a framework that is slow on one join-heavy query tends to
be slow on the others, so treating cells as independent would understate the
interval. 2000 resamples, percentile interval.

Censored cells are excluded from the estimand and counted separately. A cell
where every path exceeded the ceiling has no ratio to contribute, and one where
Django cannot express the query at all (C17) has no ORM arm.
"""
import argparse
import collections
import csv
import math
import os
import random
import statistics
import sys
import zlib

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "utils"))
import anonymise                                              # noqa: E402

DBMS_ORDER = ["postgresql", "mysql", "sqlserver", "oracle"]
DBMS_LABEL = {"postgresql": "PostgreSQL", "mysql": "MySQL",
              "sqlserver": "SQL Server", "oracle": "Oracle"}
SCHEMAS = ["indexed", "non-indexed"]
FRAMEWORKS = ["django", "sqlalchemy"]
BOOTSTRAP = 2000
SEED = 20260907


def load_blocks(meas_dir):
    """Per-cell within-block log ratios, and the censoring beside them."""
    ratios = collections.defaultdict(list)      # (dbms, schema, q, fw) -> [log ratio]
    censored = collections.defaultdict(set)     # (dbms, schema) -> {(q, fw/path)}
    for fn in sorted(os.listdir(meas_dir)):
        if not fn.endswith(".csv") or "tpcc" in fn:
            continue
        rows = list(csv.DictReader(open(os.path.join(meas_dir, fn))))
        if not rows or "block" not in rows[0]:
            continue
        for r in rows:
            if r.get("is_warmup") == "1" and r.get("status") in ("timeout", "not_expressible"):
                censored[(r["dbms"], r["schema_config"])].add(
                    (r["query_id"], r["framework"] + "/" + r["path"]))
        t = collections.defaultdict(dict)
        for r in rows:
            if r.get("is_warmup") != "0" or r.get("status") != "ok":
                continue
            t[(r["dbms"], r["schema_config"], r["query_id"],
               r["framework"], int(r["block"]))][r["path"]] = float(r["elapsed_s"])
        for (dbms, schema, q, fw, _b), d in t.items():
            if "orm" in d and "sql" in d and d["sql"] > 0 and d["orm"] > 0:
                ratios[(dbms, schema, q, fw)].append(math.log(d["orm"] / d["sql"]))
    return ratios, censored


def cell_estimates(ratios):
    """One theta per cell: the median of its within-block log ratios."""
    return {k: statistics.median(v) for k, v in ratios.items() if v}


def bootstrap_seed(cells):
    """A seed determined by the sample, so the same sample gives the same interval.

    C47. `clustered_bootstrap` used to take a caller's generator, and one
    `random.Random(SEED)` was threaded through every table in the run. The draws
    a table got then depended on how many draws the tables before it had taken,
    so the same statistic computed in two places came out differently: the
    pooled TPC-H Django interval printed [+0.5, +3.6] in the headline table and
    [+0.5, +3.7] in the sensitivity table's "none (as reported)" row, which is
    the same number by construction.

    Seeding from the sample instead makes the interval a function of the data
    and nothing else. Call order stops mattering, and so does which tables a
    run happens to build.
    """
    key = "|".join("%s:%.12g" % (q, th) for q, th in sorted(cells))
    return SEED ^ zlib.crc32(key.encode("utf-8"))


def clustered_bootstrap(cells, rng=None, n=BOOTSTRAP):
    """Percentile interval on the median theta, resampling QUERIES not cells.

    The cells of one system share their queries, and query difficulty is the
    dominant source of between-cell variation. Resampling cells independently
    would treat 22 correlated observations as 22 independent ones and report an
    interval narrower than the data supports.

    `rng` is accepted for callers that still pass one, but the default is a
    generator seeded from the sample itself (C47), which is what keeps two
    tables reporting the same statistic from disagreeing in the third digit.
    """
    if rng is None:
        rng = random.Random(bootstrap_seed(cells))
    by_query = collections.defaultdict(list)
    for (q, theta) in cells:
        by_query[q].append(theta)
    queries = list(by_query)
    if len(queries) < 2:
        return (None, None)
    out = []
    for _ in range(n):
        drawn = [t for _ in queries
                 for t in by_query[queries[rng.randrange(len(queries))]]]
        if drawn:
            out.append(statistics.median(drawn))
    if not out:
        return (None, None)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out))])


def pct(theta):
    return (math.exp(theta) - 1.0) * 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="1")
    ap.add_argument("--out", default=None)
    # On by default: these tables are what the paper quotes. --identify is for
    # reading the results against the campaign logs, which keep the real names.
    ap.add_argument("--identify", action="store_true",
                    help="print the real vendor name instead of the licensed "
                         "substitute (internal use only)")
    args = ap.parse_args()

    meas = os.path.join(REPO, "results", "sf%s" % args.scale, "measurements")
    outdir = args.out or os.path.join(REPO, "results", "sf%s" % args.scale, "analysis")
    os.makedirs(outdir, exist_ok=True)

    anon = not args.identify
    label = lambda k: anonymise.public(DBMS_LABEL[k], anon)

    ratios, censored = load_blocks(meas)
    cells = cell_estimates(ratios)
    if not cells:
        print("no block measurements found in %s" % meas, file=sys.stderr)
        return 2
    rng = random.Random(SEED)

    # ---- headline table -----------------------------------------------------
    print("=" * 84)
    print("ORM OVERHEAD AT SCALE FACTOR %s" % args.scale)
    print("  median within-block paired log ratio, as percentage overhead")
    print("  95%% CI from a query-clustered bootstrap, %d resamples" % BOOTSTRAP)
    print("=" * 84)
    print(f"{'system':20s} {'configuration':14s} {'framework':11s} "
          f"{'overhead':>9s} {'95% CI':>18s} {'cells':>6s} {'cens':>5s}")
    print("-" * 84)
    summary = []
    for dbms in DBMS_ORDER:
        for schema in SCHEMAS:
            for fw in FRAMEWORKS:
                sel = [(q, th) for (d, s, q, f), th in cells.items()
                       if d == dbms and s == schema and f == fw]
                if not sel:
                    continue
                med = statistics.median([th for _q, th in sel])
                lo, hi = clustered_bootstrap(sel)
                ncens = len({q for (q, p) in censored.get((dbms, schema), set())
                             if p.startswith(fw)})
                ci = ("[%+6.1f%%, %+6.1f%%]" % (pct(lo), pct(hi))) if lo is not None else "".rjust(18)
                print(f"{label(dbms):20s} {schema:14s} {fw:11s} "
                      f"{pct(med):+8.1f}% {ci:>18s} {len(sel):6d} {ncens:5d}")
                summary.append(dict(dbms=label(dbms), schema_config=schema,
                                    framework=fw, overhead_pct=round(pct(med), 2),
                                    ci_low_pct=round(pct(lo), 2) if lo is not None else "",
                                    ci_high_pct=round(pct(hi), 2) if hi is not None else "",
                                    n_cells=len(sel), n_censored_queries=ncens,
                                    log_ratio_median=round(med, 4)))
        print("-" * 84)

    with open(os.path.join(outdir, "overhead_summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader(); w.writerows(summary)

    # ---- per-query table ----------------------------------------------------
    per_q = []
    for (dbms, schema, q, fw), th in sorted(cells.items()):
        per_q.append(dict(dbms=label(dbms), schema_config=schema, query_id=q,
                          framework=fw, overhead_pct=round(pct(th), 2),
                          log_ratio=round(th, 4), n_blocks=len(ratios[(dbms, schema, q, fw)])))
    with open(os.path.join(outdir, "overhead_by_query.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_q[0]))
        w.writeheader(); w.writerows(per_q)

    # ---- the cells a reader will ask about first ----------------------------
    print()
    print("LARGEST ORM PENALTIES        (overhead > +50%%)")
    big = sorted((v for v in per_q if v["overhead_pct"] > 50),
                 key=lambda v: -v["overhead_pct"])
    for v in big[:12]:
        print(f"  {v['dbms']:20s} {v['schema_config']:12s} {v['query_id']:4s} "
              f"{v['framework']:11s} {v['overhead_pct']:+9.1f}%")
    print()
    print("ORM FASTER THAN ITS OWN SQL  (overhead < -20%%)")
    neg = sorted((v for v in per_q if v["overhead_pct"] < -20),
                 key=lambda v: v["overhead_pct"])
    for v in neg[:12]:
        print(f"  {v['dbms']:20s} {v['schema_config']:12s} {v['query_id']:4s} "
              f"{v['framework']:11s} {v['overhead_pct']:+9.1f}%")

    if anonymise.anonymised_any([DBMS_LABEL[d] for d in DBMS_ORDER], anon):
        print()
        print("NOTE: " + anonymise.NOTE)
    print()
    print("wrote %s" % os.path.join(outdir, "overhead_summary.csv"))
    print("wrote %s" % os.path.join(outdir, "overhead_by_query.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
