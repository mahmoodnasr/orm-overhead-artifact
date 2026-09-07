#!/usr/bin/env python3
"""Every figure the second referee report asked for, computed from the campaign.

    python3 scripts/4-analysis/sf1_referee.py --scale 1

Five quantities the paper reported for the analytical half and not for the
transactional one, plus the two the report showed were scored against the wrong
rule. Each is printed with the rows it came from so a reader can redo it.

Why a separate script
---------------------
`sf1_tables.py` writes the tables. This one is the working out behind the
sentences those tables cannot carry, and it is kept separate so that a prose
number can be regenerated without regenerating a table and vice versa. Nothing
here is written into a table; `sf1_tables.py` imports what it needs.
"""
import argparse
import collections
import csv
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from pilot_gate import parse_ceiling, percentile              # noqa: E402

DEFAULT_CEILING_S = 900.0     # ANALYSIS_PLAN section 8.3
CV_MEDIAN_MAX, CV_P90_MAX, CV_TAIL_SHARE_MAX, CV_TAIL = 5.0, 15.0, 5.0, 25.0


# ---------------------------------------------------------------- loading

def tpcc_latency(meas):
    """One row per (dbms, schema, transaction, framework, path).

    The transactional harness writes the median already taken, plus the CV
    across the three repetitions behind it. That CV is the only resolution
    figure the transactional half has, and until now nothing read it.
    """
    out = {}
    for fn in sorted(os.listdir(meas)):
        if not fn.endswith(".csv") or "tpcc" not in fn or "throughput" in fn:
            continue
        for r in csv.DictReader(open(os.path.join(meas, fn))):
            if r.get("status") != "ok":
                continue
            out[(r["dbms"], r["schema_config"], r["query_id"],
                 r["framework"], r["path"])] = r
    return out


def tpch_blocks(meas):
    """Timed executions per (campaign, query, framework, path, block)."""
    out = collections.defaultdict(dict)
    for fn in sorted(os.listdir(meas)):
        if not fn.endswith(".csv") or "tpcc" in fn:
            continue
        rows = list(csv.DictReader(open(os.path.join(meas, fn))))
        if not rows or "block" not in rows[0]:
            continue
        for r in rows:
            if r.get("is_warmup") != "0" or r.get("status") != "ok":
                continue
            key = (r["dbms"], r["schema_config"], r["query_id"], r["block"])
            out[key][(r["framework"], r["path"])] = float(r["elapsed_s"])
    return out


# ------------------------------------------------------- 1. TPC-C noise

def tpcc_noise(lat):
    """The section 8.1 bound applied to the transactional campaigns.

    The quantity is not the same one Table III reports. There it is a path's
    spread across eight blocks that each draw their own parameters; here it is
    the spread across three repetitions of one parameter set, which is the
    smaller quantity. The bound is therefore being applied in the transactional
    half's favour and still fails.
    """
    by = collections.defaultdict(list)
    for (dbms, schema, _q, _fw, _p), r in lat.items():
        if r["cv_pct"] not in ("", "nan"):
            by[(dbms, schema)].append(float(r["cv_pct"]))
    rows = []
    for camp in sorted(by):
        v = sorted(by[camp])
        rows.append((camp, len(v), statistics.median(v), percentile(v, 0.90),
                     100.0 * sum(1 for x in v if x > CV_TAIL) / len(v)))
    allv = sorted(x for v in by.values() for x in v)
    return rows, (len(allv), statistics.median(allv), percentile(allv, 0.90),
                  100.0 * sum(1 for x in allv if x > CV_TAIL) / len(allv))


# --------------------------------------- 2. do the two baselines agree?

def baseline_agreement_tpch(blocks):
    """Django's hand-written path over SQLAlchemy's, per block.

    This is the check section III-C already reports. Recomputed here only so
    the transactional figure below is produced by the same code and the two are
    comparable.
    """
    d = []
    for _k, paths in blocks.items():
        dj, sa = paths.get(("django", "sql")), paths.get(("sqlalchemy", "sql"))
        if dj and sa and sa > 0:
            d.append(100.0 * (dj / sa - 1.0))
    return d


def baseline_agreement_tpcc(lat):
    """The same check on the transactional cells, which nobody had run.

    No block structure exists here, so the pair is the two frameworks' medians
    for one transaction on one system in one configuration. That is a weaker
    pairing than the analytical one and it is the strongest available.
    """
    pair = collections.defaultdict(dict)
    for (dbms, schema, q, fw, p), r in lat.items():
        if p == "sql":
            pair[(dbms, schema, q)][fw] = float(r["median_s"])
    d = []
    for k, v in sorted(pair.items()):
        if "django" in v and "sqlalchemy" in v and v["sqlalchemy"] > 0:
            d.append((100.0 * (v["django"] / v["sqlalchemy"] - 1.0), k))
    return d


def baseline_agreement_throughput(meas):
    """The same asymmetry in the throughput runs, per concurrency level."""
    per = collections.defaultdict(dict)
    for fn in sorted(os.listdir(meas)):
        if "throughput" not in fn:
            continue
        for r in csv.DictReader(open(os.path.join(meas, fn))):
            if r["path"] != "sql":
                continue
            k = (r["dbms"], r["schema_config"], r["transaction_id"],
                 int(r["concurrency"]))
            per[k][r["framework"]] = float(r["qpm"])
    by_c = collections.defaultdict(list)
    for (_d, _s, _t, c), v in per.items():
        if "django" in v and "sqlalchemy" in v and v["sqlalchemy"] > 0:
            by_c[c].append(v["django"] / v["sqlalchemy"])
    return {c: (statistics.median(v), min(v), max(v), len(v))
            for c, v in sorted(by_c.items())}


# ------------------------------------------ 3. the ceiling that was used

def ceiling_record(meas):
    """What each campaign's own rows say the ceiling was.

    C42 fixed the harness to write `client-side:2700`, and the fix landed after
    seven of the eight campaigns had run. A campaign whose rows do not all carry
    a readable ceiling cannot evidence one, and the plan's default is then the
    only bound it can be scored against.
    """
    out = {}
    for fn in sorted(os.listdir(meas)):
        if not fn.endswith(".csv") or "tpcc" in fn:
            continue
        rows = list(csv.DictReader(open(os.path.join(meas, fn))))
        if not rows or "ceiling_s" not in rows[0]:
            continue
        seen = collections.Counter()
        slowest = 0.0
        for r in rows:
            seen[r["ceiling_s"]] += 1
            if r.get("status") == "ok":
                slowest = max(slowest, float(r["elapsed_s"]))
        parsed = {parse_ceiling(k) for k in seen}
        camp = (rows[0]["dbms"], rows[0]["schema_config"])
        out[camp] = dict(counts=dict(seen), slowest=slowest,
                         unreadable=sum(n for k, n in seen.items()
                                        if parse_ceiling(k) is None),
                         readable=sorted(x for x in parsed if x))
    return out


# ------------------------------------- 4. does excluding Q18 flip a verdict?

def q18_effect(blocks):
    """Table III's three statistics with Q18 in and out, per campaign."""
    def stats(exclude):
        series = collections.defaultdict(list)
        for (dbms, schema, q, _b), paths in blocks.items():
            if q in exclude:
                continue
            for (fw, p), t in paths.items():
                series[((dbms, schema), q, fw, p)].append(t)
        by = collections.defaultdict(list)
        for (camp, _q, _f, _p), vals in series.items():
            if len(vals) > 1 and statistics.mean(vals) > 0:
                by[camp].append(100.0 * statistics.stdev(vals)
                                / statistics.mean(vals))
        return {c: (len(v), statistics.median(v), percentile(sorted(v), 0.90),
                    100.0 * sum(1 for x in v if x > CV_TAIL) / len(v))
                for c, v in by.items()}

    def verdict(s):
        m = []
        if s[1] > CV_MEDIAN_MAX:
            m.append("median")
        if s[2] > CV_P90_MAX:
            m.append("p90")
        if s[3] > CV_TAIL_SHARE_MAX:
            m.append("tail")
        return ",".join(m) or "GO"

    inc, exc = stats(set()), stats({"Q18"})
    return [(c, inc[c], exc[c], verdict(inc[c]), verdict(exc[c]))
            for c in sorted(inc)]


def q18_drift(blocks):
    """The commercial system's Q18 Django ORM path, in block order."""
    out = collections.defaultdict(list)
    for (dbms, schema, q, b), paths in blocks.items():
        if q == "Q18" and dbms == "sqlserver" and schema == "indexed":
            for k, t in paths.items():
                out[k].append((int(b), t))
    return {k: [t for _b, t in sorted(v)] for k, v in out.items()}


# ---------------------------------------------- 5. clustered significance

def wilcoxon_exact_two_sided(values):
    """Exact two-sided Wilcoxon signed-rank. Used where n is small enough that
    the normal approximation the tables use is not defensible - which is the
    whole point of clustering, since clustering is what makes n small."""
    nz = [v for v in values if v != 0]
    n = len(nz)
    if n == 0 or n > 25:
        return None
    ranks = sorted(range(n), key=lambda i: abs(nz[i]))
    rank_of = [0] * n
    for pos, i in enumerate(ranks):
        rank_of[i] = pos + 1
    w = sum(rank_of[i] for i in range(n) if nz[i] > 0)
    total = 1 << n
    dist = [0] * (n * (n + 1) // 2 + 1)
    dist[0] = 1
    for r in range(1, n + 1):
        for s in range(len(dist) - 1, r - 1, -1):
            dist[s] += dist[s - r]
    lo = sum(dist[: int(min(w, n * (n + 1) / 2.0 - w)) + 1])
    return min(1.0, 2.0 * lo / total)


def cluster_medians(cells, key):
    g = collections.defaultdict(list)
    for k, v in cells.items():
        g[key(k)].append(v)
    return {c: statistics.median(v) for c, v in g.items()}



def _cv(xs):
    if len(xs) < 2:
        return None
    m = statistics.mean(xs)
    return (statistics.stdev(xs) / m * 100.0) if m else None


def normalised_path_cvs(blocks, dbms, schema, exclude=("Q18",)):
    """Each execution divided by the median of the four paths in its own block.

    Section 7 explains Commercial System A's indexed p90 as parameter
    sensitivity rather than noise: the eight blocks each draw their own
    parameters, so a parameter-sensitive query varies across them for a reason
    that is not measurement error. Dividing every execution by its own block's
    median removes whatever moved that block. What survives is the part that
    differs between paths which saw identical parameters seconds apart.

    On the indexed campaign that takes the p90 from 23.50% to 14.67%, which is
    the explanation holding. On the non-indexed one it leaves 16.01%, which is
    the explanation failing, and Section 7 reports that campaign as failing
    rather than as explained.

    Q18 is excluded, per ANALYSIS_PLAN section 2.1 and the rest of this file.
    Its parameter set 0 falls outside its own substitution range, so its spread
    across blocks carries a parameter effect the other 21 queries do not have -
    which is the very quantity this normalisation is trying to remove.
    """
    series = collections.defaultdict(dict)
    scaled = collections.defaultdict(dict)
    for (d, sch, q, b), by_path in blocks.items():
        if d != dbms or sch != schema or q in exclude:
            continue
        med = statistics.median(list(by_path.values())) if by_path else None
        for (fw, path), t in by_path.items():
            series[(q, fw, path)][b] = t
            if med:
                scaled[(q, fw, path)][b] = t / med
    plain = [c for k in series
             if (c := _cv([series[k][b] for b in sorted(series[k])])) is not None]
    norm = [c for k in scaled
            if (c := _cv([scaled[k][b] for b in sorted(scaled[k])])) is not None]
    return sorted(plain), sorted(norm)


def tpcc_ratio(lat):
    """One log ratio per transactional cell, for the pooled figure.

    `tpcc_latency` keys by path as well, so the two arms of a cell are two
    entries and have to be brought back together here.
    """
    paths = collections.defaultdict(dict)
    for (d, sch, q, f, path), row in lat.items():
        paths[(d, sch, q, f)][path] = float(row["median_s"])
    out = {}
    for k, d in paths.items():
        if d.get("orm") and d.get("sql"):
            out[k] = math.log(d["orm"] / d["sql"])
    return out


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="1")
    args = ap.parse_args()
    meas = os.path.join(REPO, "results", "sf%s" % args.scale, "measurements")
    res = os.path.join(REPO, "results", "sf%s" % args.scale, "all_results.csv")

    lat = tpcc_latency(meas)
    blocks = tpch_blocks(meas)

    print("=" * 74)
    print("1. THE SECTION 8.1 BOUND ON THE TRANSACTIONAL CAMPAIGNS")
    print("=" * 74)
    print("   bound: median <= %.0f%%, p90 <= %.0f%%, share above %.0f%% <= %.0f%%"
          % (CV_MEDIAN_MAX, CV_P90_MAX, CV_TAIL, CV_TAIL_SHARE_MAX))
    rows, pooled = tpcc_noise(lat)
    for (dbms, schema), n, med, p90, share in rows:
        miss = [nm for nm, ok in (("median", med <= CV_MEDIAN_MAX),
                                  ("p90", p90 <= CV_P90_MAX),
                                  ("tail", share <= CV_TAIL_SHARE_MAX)) if not ok]
        print("   %-11s %-12s n=%3d  median %6.2f%%  p90 %6.2f%%  tail %5.1f%%  %s"
              % (dbms, schema, n, med, p90, share, ",".join(miss) or "GO"))
    print("   POOLED      n=%d  median %.2f%%  p90 %.2f%%  tail %.1f%%"
          % pooled)

    print()
    print("=" * 74)
    print("2. DO THE TWO FRAMEWORKS' HAND-WRITTEN BASELINES AGREE?")
    print("=" * 74)
    a = sorted(baseline_agreement_tpch(blocks))
    print("   TPC-H, per block, Django over SQLAlchemy:")
    print("     n=%d  median %+.2f%%  p10 %+.1f%%  p90 %+.1f%%  |diff|>5%%: %.1f%%"
          % (len(a), statistics.median(a), percentile(a, 0.10),
             percentile(a, 0.90), 100.0 * sum(1 for x in a if abs(x) > 5) / len(a)))
    b = baseline_agreement_tpcc(lat)
    bv = sorted(x for x, _k in b)
    print("   TPC-C, per cell, Django over SQLAlchemy:")
    print("     n=%d  median %+.2f%%  p10 %+.1f%%  p90 %+.1f%%  |diff|>5%%: %.1f%%"
          % (len(bv), statistics.median(bv), percentile(bv, 0.10),
             percentile(bv, 0.90), 100.0 * sum(1 for x in bv if abs(x) > 5) / len(bv)))
    print("     range %+.1f%% to %+.1f%%   (ratio %.2fx to %.2fx)"
          % (min(bv), max(bv), 1 + min(bv) / 100.0, 1 + max(bv) / 100.0))
    for x, k in sorted(b)[:3] + sorted(b)[-3:]:
        print("       %-11s %-12s %-3s %+8.1f%%" % (k[0], k[1], k[2], x))
    print("   TPC-C throughput, Django SQL over SQLAlchemy SQL, by clients:")
    for c, (med, lo, hi, n) in baseline_agreement_throughput(meas).items():
        print("     %2d clients  n=%3d  median %.2fx  range %.2fx-%.2fx"
              % (c, n, med, lo, hi))

    print()
    print("=" * 74)
    print("3. THE CEILING EACH CAMPAIGN'S OWN ROWS RECORD")
    print("=" * 74)
    for camp, d in sorted(ceiling_record(meas).items()):
        readable = d["readable"]
        eff = max(readable) if readable else None
        print("   %-11s %-12s slowest %7.1f s   rows unreadable %4d   %s"
              % (camp[0], camp[1], d["slowest"], d["unreadable"],
                 " ".join("%s=%d" % kv for kv in sorted(d["counts"].items()))))
        for name, cap in (("recorded", eff), ("plan default", DEFAULT_CEILING_S)):
            if cap:
                m = cap / d["slowest"]
                print("        margin against %-13s %6.0f s = %5.2fx  %s"
                      % (name, cap, m, "GO" if m >= 5 else "FAIL"))

    print()
    print("=" * 74)
    print("4. DOES EXCLUDING Q18 FLIP A CAMPAIGN'S VERDICT?")
    print("=" * 74)
    for camp, inc, exc, vi, ve in q18_effect(blocks):
        flag = "  <-- FLIPS" if vi != ve else ""
        print("   %-11s %-12s  incl: med %5.2f p90 %5.2f tail %4.1f -> %-12s"
              "   excl: med %5.2f p90 %5.2f tail %4.1f -> %-12s%s"
              % (camp[0], camp[1], inc[1], inc[2], inc[3], vi,
                 exc[1], exc[2], exc[3], ve, flag))
    print("   Q18 on the commercial system, indexed, in block order:")
    for k, v in sorted(q18_drift(blocks).items()):
        print("     %-11s %-4s %s" % (k[0], k[1],
                                      " ".join("%.1f" % x for x in v)))

    print()
    print("=" * 74)
    print("5. SIGNIFICANCE WHEN THE CLUSTERS ARE THE UNIT")
    print("=" * 74)
    sys.path.insert(0, HERE)
    from sf1_analysis import cell_estimates, load_blocks, pct
    ratios, _c = load_blocks(meas)
    cells = cell_estimates(ratios)
    for fw in ("django", "sqlalchemy"):
        sel = {k: v for k, v in cells.items() if k[3] == fw}
        cm = cluster_medians(sel, lambda k: k[2])
        v = list(cm.values())
        print("   TPC-H %-11s cells n=%3d median %+.2f%%   clusters n=%2d "
              "median %+.2f%%  exact two-sided p = %.2g"
              % (fw, len(sel), pct(statistics.median(list(sel.values()))),
                 len(v), pct(statistics.median(v)),
                 wilcoxon_exact_two_sided(v)))
    tp = collections.defaultdict(dict)
    for (dbms, schema, q, fw, p), r in lat.items():
        tp[(dbms, schema, q, fw)][p] = float(r["median_s"])
    tcells = {k: math.log(d["orm"] / d["sql"]) for k, d in tp.items()
              if d.get("orm") and d.get("sql")}
    for fw in ("django", "sqlalchemy"):
        sel = {k: v for k, v in tcells.items() if k[3] == fw}
        cm = cluster_medians(sel, lambda k: k[2])
        v = list(cm.values())
        p = wilcoxon_exact_two_sided(v)
        print("   TPC-C %-11s cells n=%3d median %+.1f%%   clusters n=%2d "
              "median %+.1f%%  exact two-sided p = %.3g  (floor %.3g)"
              % (fw, len(sel), pct(statistics.median(list(sel.values()))),
                 len(v), pct(statistics.median(v)), p, 2.0 / (1 << len(v))))

    print()
    print("=" * 74)
    print("6. CENSORING THAT IS INFORMATIVE")
    print("=" * 74)
    for r in csv.DictReader(open(res)):
        if r["sql_status"] == "ok" and r["orm_status"] == "timeout":
            base = float(r["direct_sql_execution_s"])
            print("   %-4s %-11s %-11s %-12s baseline %6.3f s -> overhead > %+.0f%%"
                  % (r["query_id"], r["orm"], r["dbms"], r["schema_config"],
                     base, (DEFAULT_CEILING_S / base - 1) * 100))

    print()
    print("=" * 74)
    print("7. THE PER-STATEMENT FIGURE, AND WHICH AGGREGATION MAKES IT")
    print("=" * 74)
    from sf1_tables import STATEMENTS
    for fw, idx in (("django", 0), ("sqlalchemy", 1)):
        per, tot_ms, tot_n = [], 0.0, 0
        for (dbms, schema, q, f), d in sorted(tp.items()):
            if f != fw or not (d.get("orm") and d.get("sql")):
                continue
            n = STATEMENTS[q][idx]
            per.append((d["orm"] - d["sql"]) * 1000.0 / n)
            tot_ms += (d["orm"] - d["sql"]) * 1000.0
            tot_n += n
        by_txn = []
        for q in sorted(STATEMENTS):
            v = [(d["orm"] - d["sql"]) * 1000.0 for (_a, _b, qq, f), d
                 in tp.items() if qq == q and f == fw and d.get("orm")]
            by_txn.append(statistics.median(v) / STATEMENTS[q][idx])
        print("   %-11s over 80 cells: median %.3f ms   "
              "over 5 tabulated transactions: median %.3f ms   "
              "total/total: %.3f ms"
              % (fw, statistics.median(per), statistics.median(by_txn),
                 tot_ms / tot_n))
    print()
    print("=" * 74)
    print("8. DOES BLOCK-NORMALISING EXPLAIN THE COMMERCIAL SYSTEM'S TAIL?")
    print("=" * 74)
    print("   each execution divided by the median of the four paths in its block")
    for schema in ("indexed", "non-indexed"):
        plain, norm = normalised_path_cvs(blocks, "sqlserver", schema)
        if not plain:
            print("   sqlserver   %-12s no rows: this campaign's measurements "
                  "are not in this copy" % schema)
            continue
        print("   sqlserver   %-12s n=%3d   p90 %5.2f%%  ->  normalised p90 %5.2f%%"
              % (schema, len(plain), percentile(plain, 0.9),
                 percentile(norm, 0.9)))
    if any(normalised_path_cvs(blocks, "sqlserver", sch)[0]
           for sch in ("indexed", "non-indexed")):
        print("   indexed: the sensitivity explanation holds. non-indexed: it "
              "does not,")
        print("   and Section 7 reports that campaign as failing rather than "
              "explained.")

    print()
    print("=" * 74)
    print("9. THE PER-CELL AND POOLED FIGURES THE PROSE QUOTES")
    print("=" * 74)
    ratios, _cens = load_blocks(meas)
    cells = cell_estimates(ratios)
    print("   pooled, all analytical cells:      %+.2f%%" %
          pct(statistics.median(list(cells.values()))))
    tp = tpcc_ratio(lat)
    print("   pooled, all transactional cells:   %+.2f%%" %
          pct(statistics.median(list(tp.values()))))
    print("   by system, framework and schema:")
    agg = collections.defaultdict(list)
    for (d, sch, q, f), th in cells.items():
        agg[(d, sch, f)].append(th)
    for k in sorted(agg):
        print("     %-11s %-12s %-11s %+8.2f%%  (n=%d)"
              % (k[0], k[1], k[2], pct(statistics.median(agg[k])), len(agg[k])))
    print("   the queries the prose names, cell by cell:")
    NAMED = ("Q02", "Q04", "Q12", "Q13", "Q15", "Q17", "Q18", "Q20")
    for q in NAMED:
        rows = sorted((k for k in cells if k[2] == q))
        for (d, sch, qq, f) in rows:
            print("     %-4s %-11s %-12s %-11s %+12.2f%%"
                  % (qq, d, sch, f, pct(cells[(d, sch, qq, f)])))

    return 0


if __name__ == "__main__":
    sys.exit(main())
