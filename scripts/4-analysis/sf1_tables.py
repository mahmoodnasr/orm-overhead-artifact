#!/usr/bin/env python3
"""The three LaTeX tables Section 5 of the paper inputs, from the SF1 campaign.

    python3 scripts/4-analysis/sf1_tables.py --scale 1 --outdir ../../IJACSA_Paper/tables

Why this exists rather than analyze_final.py
--------------------------------------------
`analyze_final.py` writes `tab_noise` and `tab_headline` from a row per cell in
`all_results.csv`, and `phase_b.py` writes `tab_per_statement` the same way.
Pointed at the SF1 tree both of them are wrong, in two different ways, and only
one of the two announces itself:

  * `sql_cv_pct` and `orm_cv_pct` are blank on all 352 TPC-H rows of
    `results/sf1/all_results.csv` and populated only on the 80 TPC-C rows. The
    block protocol computes a path's variation across its eight blocks, and the
    results builder never filled the column for it. `t_noise` filters on those
    columns being present, finds no TPC-H rows, and emits a noise table whose
    TPC-H line is simply absent - a table that looks complete because the row it
    cannot compute is the row it does not print.

  * the headline is a median over cells of the block-paired estimand, and its
    interval resamples queries as clusters (ANALYSIS_PLAN section 1 and 4).
    `analyze_final.py` bootstraps cells.

So the noise figures are computed here from the block measurements, which is
where they exist. The estimand and the clustered bootstrap are the ones in
`sf1_analysis.py`, imported rather than restated so the tables and the CSVs
cannot drift apart.

The gate verdicts
-----------------
The noise table reports each campaign against the bound that was written into
ANALYSIS_PLAN section 8.1 before the pilot ran: median CV <= 5.0%, p90 CV <=
15.0%, and at most 5% of paths above 25%. All three must hold. Q18 is excluded
from the analytical distribution, per that plan's section 2.1, because its
parameter set 0 falls outside its own substitution range; `sf1_referee.py`
prints what that exclusion buys, which is no change to any verdict.

All sixteen campaigns are scored, not the eight analytical ones (C43). Twelve
miss a bound: four analytical and all eight transactional. Of the four, SQL
Server indexed misses the p90, the tail and - once it is scored against the
ceiling its own rows record rather than one read off 52 late rows (C45) - the
section 8.3 margin; SQL Server non-indexed misses the p90; Oracle indexed the
tail; Oracle non-indexed the margin alone.

The bounds were left as written. A threshold amended after seeing the data that
failed it is a description of that data.

Verified against the gate that produced those verdicts:

    for f in results/sf1/measurements/*.csv; do
        python3 scripts/4-analysis/pilot_gate.py "$f"; done

Every median, p90, tail share and margin this file prints matches that run, and
`tests/test_sf1_tables.py` holds it there.
"""
import argparse
import collections
import csv
import math
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "utils"))
sys.path.insert(0, HERE)
import anonymise                                              # noqa: E402
from sf1_analysis import (DBMS_LABEL, DBMS_ORDER, SCHEMAS,     # noqa: E402
                          FRAMEWORKS, SEED, cell_estimates,
                          clustered_bootstrap, load_blocks, pct)
# The gate is the authority on how these bounds are scored. Importing its
# ceiling parser and its interpolated percentile rather than restating them is
# what keeps the paper's table and the campaign's own verdict the same number.
from pilot_gate import parse_ceiling, percentile                # noqa: E402

# ANALYSIS_PLAN section 8.1. Fixed before the pilot; not amended after it.
CV_MEDIAN_MAX = 5.0
CV_P90_MAX = 15.0
CV_TAIL_SHARE_MAX = 5.0        # per cent of paths whose CV exceeds 25%
CV_TAIL_THRESHOLD = 25.0
# ANALYSIS_PLAN section 8.3. The margin required under the ceiling in force,
# and the ceiling a campaign is held to when its own rows do not record one.
MARGIN_MIN = 5.0
DEFAULT_CEILING_S = 900.0
# ANALYSIS_PLAN section 2.1: Q18's blocks are not exchangeable across each other.
CV_EXCLUDE_QUERIES = {"Q18"}

FW_LABEL = {"django": "Django", "sqlalchemy": "SQLAlchemy"}

# Statement counts read from the transaction code, carried over from phase_b.py
# unchanged - the transactions did not change between campaigns, so re-deriving
# them here would only create a second place for them to disagree.
STATEMENTS = {
    "T1": (6 + 3 * 10, 5 + 2 * 10 + 1, "New-Order"),
    "T2": (7, 7, "Payment"),
    "T3": (3, 3, "Order-Status"),
    "T4": (10 * 6, 10 * 6, "Delivery"),
    "T5": (4, 4, "Stock-Level"),
}


def table(path, caption, label, cols, header, body_rows, wide=False):
    """One LaTeX table in the thesis's own form.

    `[H]` and `\\textwidth` are what `IJACSA_Paper/adapt_tables.py` expects to
    rewrite for the two-column template. Emitting paper-ready markup here would
    put the adaptation in two places, and the one that stopped being run would
    be the one nobody noticed.
    """
    with open(path, "w") as fh:
        fh.write("\\begin{table}[H]\n")
        fh.write("\\caption{%s}\n" % caption)
        fh.write("\\label{%s}\n" % label)
        fh.write("\\centering\n\\renewcommand{\\arraystretch}{1.2}\n")
        if wide:
            fh.write("\\resizebox{\\textwidth}{!}{%\n")
        fh.write("\\begin{tabular}{%s}\n\\hline\\hline\n" % cols)
        fh.write(" & ".join("\\textbf{%s}" % h for h in header) + "\\\\\n")
        fh.write("\\hline\\hline\n")
        for row in body_rows:
            fh.write(" & ".join(str(c) for c in row) + "\\\\ \\hline\n")
        fh.write("\\hline\n\\end{tabular}" + ("}\n" if wide else "\n"))
        fh.write("\\end{table}\n")
    print("  wrote", os.path.basename(path))


def path_cvs(meas_dir):
    """CV per access path across its eight blocks, the campaign maximum, and
    the ceiling that was actually in force.

    One CV per (dbms, schema, query, framework, path). The quantity is defined
    across blocks, and each block draws its own substitution parameters, so it
    carries real parameter-to-parameter variation as well as measurement noise.
    ANALYSIS_PLAN section 8.1 sets the bound against that larger quantity
    deliberately; it is not the repeatability of one parameter set.

    The ceiling is read per row, and a campaign is scored against the value its
    own rows carry only when *every* row carries one. Otherwise it is scored
    against ANALYSIS_PLAN section 8.3's declared default of 900 s.

    That rule replaces one that took the largest parsable value any row held,
    and the change costs the paper a passing campaign. SQL Server's indexed run
    records the bare string `client-side` on 1,480 rows and `client-side:2700`
    on the 52 appended when Q13 was re-run after C42 was fixed. The old rule
    read 2700 s off those 52 rows and scored the whole campaign at 12x. Under
    the plan's default the same campaign is 900 / 232.5 = 3.87x and fails.

    The 2700 s is real and pre-registered, but section 8.3 declares it as the
    retry ceiling for a *censored* cell, applied once. No cell in that campaign
    was censored, so no retry fired, and the parser that made 2700 s legible to
    this gate was committed after that campaign had run. A bound the analysis
    can only reach by reading rows written afterwards is not a bound the
    campaign was held to, and the honest scoring is the declared default.
    """
    series = collections.defaultdict(list)
    slowest = collections.defaultdict(lambda: (0.0, None))
    ceilings = collections.defaultdict(list)
    for fn in sorted(os.listdir(meas_dir)):
        if not fn.endswith(".csv") or "tpcc" in fn:
            continue
        rows = list(csv.DictReader(open(os.path.join(meas_dir, fn))))
        if not rows or "block" not in rows[0]:
            continue
        for r in rows:
            camp = (r["dbms"], r["schema_config"])
            # Every row votes on the ceiling, warmup rows included: the question
            # is what the campaign recorded, not what it timed.
            ceilings[camp].append(parse_ceiling(r.get("ceiling_s")))
            if r.get("is_warmup") != "0" or r.get("status") != "ok":
                continue
            elapsed = float(r["elapsed_s"])
            series[(camp, r["query_id"], r["framework"], r["path"])].append(elapsed)
            if elapsed > slowest[camp][0]:
                slowest[camp] = (elapsed, (r["query_id"], r["framework"], r["path"]))

    cvs = collections.defaultdict(list)
    for (camp, q, _fw, _p), vals in series.items():
        if q in CV_EXCLUDE_QUERIES or len(vals) < 2:
            continue
        mean = statistics.mean(vals)
        if mean > 0:
            cvs[camp].append(100.0 * statistics.stdev(vals) / mean)
    # A campaign evidences a ceiling only if none of its rows is missing one.
    ceiling = {}
    for camp, votes in ceilings.items():
        recorded = [v for v in votes if v]
        ceiling[camp] = (max(recorded) if recorded and len(recorded) == len(votes)
                         else DEFAULT_CEILING_S)
    return cvs, slowest, ceiling


def tpcc_path_cvs(meas_dir):
    """CV per transactional access path, from the harness's own column.

    Not the same quantity as the analytical CV above, and the difference runs
    in the transactional half's favour. There a path's spread is taken across
    eight blocks that each draw their own substitution parameters, so it carries
    parameter sensitivity as well as noise. Here it is the spread across three
    repetitions of one transaction under one parameter draw, which is closer to
    pure repeatability. The section 8.1 bound was written against the larger
    quantity and is applied here to the smaller one.

    This column has been in every TPC-C latency file since the campaign ran and
    nothing read it. Table III reported eight analytical campaigns and the
    paper's headline contrast rests on these eight.
    """
    cvs = collections.defaultdict(list)
    for fn in sorted(os.listdir(meas_dir)):
        if not fn.endswith(".csv") or "tpcc" not in fn or "throughput" in fn:
            continue
        for r in csv.DictReader(open(os.path.join(meas_dir, fn))):
            if r.get("status") != "ok" or r.get("cv_pct") in (None, "", "nan"):
                continue
            cvs[(r["dbms"], r["schema_config"])].append(float(r["cv_pct"]))
    return cvs


def t_noise(meas_dir, out, anon):
    """The measurement's own resolution, per campaign, against the bound.

    Per campaign rather than per workload because that is the unit the bound was
    written for and the unit that failed it. All sixteen campaigns are here, two
    per row: an earlier version reported the eight analytical ones, which left
    the paper's largest effect - the transactional contrast of Section 5 - as the
    only quantity in it with no stated resolution, and that is the objection
    Section 1 makes against the prior literature (C43).

    One row per system and schema, with the two workloads side by side, because
    sixteen rows of eight columns cost the paper a page it did not have and the
    interesting comparison is across a row rather than down the table.
    """
    cvs, slowest, ceiling = path_cvs(meas_dir)
    tpcc_cvs = tpcc_path_cvs(meas_dir)
    body, failures = [], []

    def score(v):
        med = statistics.median(v)
        p90 = percentile(sorted(v), 0.90)
        share = 100.0 * sum(1 for x in v if x > CV_TAIL_THRESHOLD) / len(v)
        missed = []
        if med > CV_MEDIAN_MAX:
            missed.append("median")
        if p90 > CV_P90_MAX:
            missed.append("p90")
        if share > CV_TAIL_SHARE_MAX:
            missed.append("tail")
        return med, p90, share, missed

    npaths = {}
    for dbms in DBMS_ORDER:
        for schema in SCHEMAS:
            camp = (dbms, schema)
            row = [anonymise.public(DBMS_LABEL[dbms], anon), schema]
            for workload, table_cvs in (("TPC-H", cvs), ("TPC-C", tpcc_cvs)):
                v = table_cvs.get(camp)
                if not v:
                    row += ["--"] * (5 if workload == "TPC-H" else 4)
                    continue
                npaths.setdefault(workload, set()).add(len(v))
                med, p90, share, missed = score(v)
                cap = margin = None
                margin_cell = None
                if workload == "TPC-H":
                    worst, _w = slowest[camp]
                    cap = ceiling.get(camp)
                    margin = (cap / worst) if (cap and worst > 0) else None
                    if margin is not None and margin < MARGIN_MIN:
                        missed.append("margin")
                    margin_cell = ("$%.1f\\times$" % margin
                                   if margin and margin < 100
                                   else ("$>$100$\\times$" if margin else "--"))
                if missed:
                    failures.append((workload, dbms, schema, missed, med, p90,
                                     share, cap, margin))
                verdict = "GO" if not missed else "\\textbf{%s}" % ", ".join(missed)
                row += [verdict, "%.2f" % med, "%.2f" % p90, "%.1f" % share]
                if margin_cell is not None:
                    row.append(margin_cell)
            body.append(row)

    tpch_fail = sum(1 for f in failures if f[0] == "TPC-H")
    tpcc_fail = sum(1 for f in failures if f[0] == "TPC-C")
    table(os.path.join(out, "tab_noise.tex"),
          "Every campaign against the bounds fixed before the pilot ran: a "
          "median CV at or below 5\\%%, a p90 at or below 15\\%%, and at most "
          "5\\%% of paths above 25\\%%. %d analytical campaigns miss one and all "
          "%d transactional campaigns miss all three. The two CVs are not the "
          "same quantity and the difference favours the transactional half "
          "(Section~\\ref{sec:results}). Margin is the ceiling over the slowest "
          "path, required to be 5$\\times$; a campaign whose rows do not all "
          "record a ceiling is held to the declared 900~s default, and the "
          "transactional files record none. Query~18 is excluded from the "
          "analytical distribution, which flips no verdict. Each analytical "
          "campaign contributes 83 or 84 access paths and each transactional "
          "one 20. Causes are in Section~\\ref{sec:threats}."
          % (tpch_fail, tpcc_fail),
          "tab_r_noise", "l l l r r r r l r r r",
          ["System", "Schema",
           "TPC-H", "med", "p90", "$>$25", "Margin",
           "TPC-C", "med", "p90", "$>$25"],
          body, wide=True)
    return failures


def load_tpcc(meas_dir):
    """Per-cell TPC-C log ratios, from the transaction latency files.

    The TPC-C files carry one row per (transaction, framework, path) with the
    median already taken, not one row per block, so the paired within-block
    estimand the analytical grid uses is not available here. This is a ratio of
    medians and the difference is stated rather than hidden.
    """
    paths = collections.defaultdict(dict)
    for fn in sorted(os.listdir(meas_dir)):
        if not fn.endswith(".csv") or "tpcc" not in fn or "throughput" in fn:
            continue
        for r in csv.DictReader(open(os.path.join(meas_dir, fn))):
            if r.get("status") != "ok":
                continue
            paths[(r["dbms"], r["schema_config"], r["query_id"],
                   r["framework"])][r["path"]] = float(r["median_s"])
    out = {}
    for k, d in paths.items():
        if "orm" in d and "sql" in d and d["sql"] > 0 and d["orm"] > 0:
            out[k] = (math.log(d["orm"] / d["sql"]), d["orm"] - d["sql"])
    return out


def baseline_spread(meas_dir):
    """How far apart the two frameworks' hand-written baselines are.

    Section 3 licenses comparing the two frameworks' overheads by showing their
    denominators agree. It showed it on the analytical grid, where they do, and
    the comparison the paper leans on hardest is transactional, where they do
    not. Both are computed here so the paper can state both.

    The analytical pair is per block: the same query, the same substitution
    parameters, seconds apart. The transactional harness has no blocks, so the
    pair is the two frameworks' medians for one transaction on one system in one
    configuration - a weaker pairing, and the strongest available.
    """
    tpch = []
    for fn in sorted(os.listdir(meas_dir)):
        if not fn.endswith(".csv") or "tpcc" in fn:
            continue
        rows = list(csv.DictReader(open(os.path.join(meas_dir, fn))))
        if not rows or "block" not in rows[0]:
            continue
        blocks = collections.defaultdict(dict)
        for r in rows:
            if r.get("is_warmup") != "0" or r.get("status") != "ok" \
                    or r["path"] != "sql":
                continue
            blocks[(r["dbms"], r["schema_config"], r["query_id"],
                    r["block"])][r["framework"]] = float(r["elapsed_s"])
        for v in blocks.values():
            if "django" in v and "sqlalchemy" in v and v["sqlalchemy"] > 0:
                tpch.append(100.0 * (v["django"] / v["sqlalchemy"] - 1.0))

    pairs = collections.defaultdict(dict)
    for fn in sorted(os.listdir(meas_dir)):
        if not fn.endswith(".csv") or "tpcc" not in fn or "throughput" in fn:
            continue
        for r in csv.DictReader(open(os.path.join(meas_dir, fn))):
            if r.get("status") != "ok" or r["path"] != "sql":
                continue
            pairs[(r["dbms"], r["schema_config"],
                   r["query_id"])][r["framework"]] = float(r["median_s"])
    tpcc = [100.0 * (v["django"] / v["sqlalchemy"] - 1.0) for v in pairs.values()
            if "django" in v and "sqlalchemy" in v and v["sqlalchemy"] > 0]

    def describe(v):
        s = sorted(v)
        return dict(n=len(s), median=statistics.median(s),
                    p10=percentile(s, 0.10), p90=percentile(s, 0.90),
                    beyond5=100.0 * sum(1 for x in s if abs(x) > 5) / len(s),
                    lo_ratio=1.0 + min(s) / 100.0, hi_ratio=1.0 + max(s) / 100.0)
    return describe(tpch), describe(tpcc)


def orm_rows_returned(meas_dir):
    """Rows the ORM path returned, per cell.

    The outlier table needs it to rule out object materialisation: a cell that
    hands back one row cannot owe a doubled runtime to building objects out of
    it, whatever else it owes it to.
    """
    out = {}
    for fn in sorted(os.listdir(meas_dir)):
        if not fn.endswith(".csv") or "tpcc" in fn:
            continue
        rows = list(csv.DictReader(open(os.path.join(meas_dir, fn))))
        if not rows or "block" not in rows[0]:
            continue
        for r in rows:
            if (r.get("is_warmup") != "0" or r.get("status") != "ok"
                    or r["path"] != "orm"):
                continue
            try:
                out[(r["dbms"], r["schema_config"], r["query_id"],
                     r["framework"])] = int(r["rows_returned"])
            except (ValueError, TypeError):
                pass
    return out


def t_outliers(cells, nrows, out, anon):
    """Every cell whose ORM path costs more than double its own baseline."""
    body = []
    big = sorted(((k, th) for k, th in cells.items() if pct(th) > 100.0),
                 key=lambda kv: -kv[1])
    for (dbms, schema, q, fw), th in big:
        n = nrows.get((dbms, schema, q, fw))
        body.append([q.replace("Q0", "Q").replace("Q", "Q"), FW_LABEL[fw],
                     anonymise.public(DBMS_LABEL[dbms], anon), schema,
                     "%+.1f\\%%" % pct(th), n if n is not None else "--"])
    small = sum(1 for (k, _th) in big
                if nrows.get(k) is not None and nrows[k] <= 100)
    known = sum(1 for (k, _th) in big if nrows.get(k) is not None)
    table(os.path.join(out, "tab_outliers.tex"),
          "All %d analytical cells with overhead beyond $+100\\%%$. %d of the %d "
          "return at most a hundred rows and %d return exactly one, so building "
          "objects out of the answer cannot account for the gap. Rows is what the "
          "ORM path returned; Query~15 is %d of these cells. "
          % (len(big), small, known,
             sum(1 for (k, _t) in big if nrows.get(k) == 1),
             sum(1 for ((_d, _s, q, _f), _t) in big if q == "Q15"))
          + anonymise.NOTE,
          "tab_r_outliers", "l l l l r r",
          ["Query", "Framework", "System", "Schema", "Overhead", "Rows"],
          body, wide=True)
    return big


def t_completeness(results_csv, out, anon):
    """Coverage of the 432-cell grid, from the results file rather than the
    measurements, because the results file is where a cell that was never
    attempted still has a row.

    Reads the two status columns rather than a count of files. A cell is
    complete when both paths ran, censored when a path hit the ceiling, and
    inexpressible when the ORM has no construct for the query. Those three
    exhaust the grid at SF1, and the table prints the fourth column as zero so
    that a future campaign with an unexplained cell cannot hide it in a total.
    """
    rows = list(csv.DictReader(open(results_csv)))
    grid = collections.defaultdict(collections.Counter)
    for r in rows:
        workload = "TPC-H" if r["benchmark"] == "tpch" else "TPC-C"
        c = grid[(r["dbms"], workload)]
        c["cells"] += 1
        sql, orm = r["sql_status"], r["orm_status"]
        if sql == "ok" and orm == "ok":
            c["complete"] += 1
        elif orm == "not_expressible":
            c["inexpressible"] += 1
        elif "timeout" in (sql, orm):
            c["censored"] += 1
        else:
            c["unexplained"] += 1

    order = [DBMS_LABEL[d] for d in DBMS_ORDER]
    body = []
    for label in order:
        for workload in ("TPC-H", "TPC-C"):
            c = grid.get((label, workload))
            if not c:
                continue
            body.append([anonymise.public(label, anon), workload, c["cells"],
                         c["complete"], c["censored"], c["inexpressible"],
                         c["unexplained"]])
    table(os.path.join(out, "tab_completeness.tex"),
          "Coverage of the design grid. Every cell of the $4 \\times 2 \\times 2 "
          "\\times 27$ design is in the results file, and one not measured "
          "carries a reason rather than being absent. Censored means a path "
          "exceeded the statement ceiling; inexpressible means the ORM has no "
          "construct for the query. The last column is the one that matters: no "
          "cell is missing for a reason we cannot name. "
          + anonymise.NOTE,
          "tab_r_completeness", "l l r r r r r",
          ["DBMS", "Workload", "Cells", "Complete", "Censored",
           "Inexpressible", "Unexplained"],
          body, wide=True)


def sensitivity_groups(cells):
    """The groups a reader is entitled to suspect, each with why.

    Not every subset of the data: the ones where a reviewer could argue the
    cells do not belong, or where this campaign itself has already conceded
    something. Two of them come from our own disclosures rather than from an
    imagined objection.
    """
    return [
        ("none (as reported)",
         lambda k: False),
        ("Commercial System A",
         lambda k: k[0] == "sqlserver"),
        ("Oracle",
         lambda k: k[0] == "oracle"),
        # The four analytical campaigns that miss a bound in Table III. Still
        # four: SQL Server indexed already missed the p90 and the tail, and
        # scoring it against the ceiling its own rows record adds the margin to
        # the same campaign rather than adding a campaign.
        ("the four campaigns that missed a bound",
         lambda k: (k[0], k[1]) in {("sqlserver", "indexed"),
                                    ("sqlserver", "non-indexed"),
                                    ("oracle", "indexed"),
                                    ("oracle", "non-indexed")}),
        ("Query~18, whose parameter sets are not exchangeable",
         lambda k: k[2] == "Q18"),
        ("Query~15, nine of the 25 largest cells",
         lambda k: k[2] == "Q15"),
        ("every cell above $+100\\%$",
         lambda k: pct(cells[k]) > 100.0),
        ("the non-indexed configuration",
         lambda k: k[1] == "non-indexed"),
        ("the indexed configuration",
         lambda k: k[1] == "indexed"),
    ]


def t_sensitivity(cells, out, rng):
    """Every pooled analytical figure, recomputed with each group removed.

    A conclusion that moves when a group is dropped is not a conclusion. This
    table exists so that a reader can check the one this paper rests on rather
    than take our word that it holds.
    """
    body, spans = [], {fw: [] for fw in FRAMEWORKS}
    for name, drop in sensitivity_groups(cells):
        row = [name]
        for fw in FRAMEWORKS:
            sel = [(q, th) for (d, sc, q, f), th in cells.items()
                   if f == fw and not drop((d, sc, q, f))]
            if not sel:
                row += ["--", "--", "--"]
                continue
            med = statistics.median([th for _q, th in sel])
            lo, hi = clustered_bootstrap(sel, rng)
            spans[fw].append(pct(med))
            row += ["%+.2f\%%" % pct(med),
                    "[%+.1f, %+.1f]" % (pct(lo), pct(hi)) if lo is not None else "--",
                    len(sel)]
        body.append(row)

    dj, sa = spans["django"], spans["sqlalchemy"]
    table(os.path.join(out, "tab_sensitivity.tex"),
          "Pooled analytical overhead recomputed with each group of cells "
          "removed. The first row is the figure the paper reports; each other "
          "drops a group a reader might argue does not belong. Django stays "
          "between %+.2f\\%% and %+.2f\\%% and SQLAlchemy between %+.2f\\%% "
          "and %+.2f\\%%, and neither changes sign."
          % (min(dj), max(dj), min(sa), max(sa)),
          "tab_r_sensitivity", "l r l r r l r",
          ["Group removed", "Django", "95\% CI", "$n$",
           "SQLAlchemy", "95\% CI", "$n$"],
          body, wide=True)
    return spans


def wilcoxon_p(values):
    """Two-sided Wilcoxon signed-rank against zero, normal approximation.

    scipy is in the campaign venv but this script is also run from the paper
    tree, where it may not be. The normal approximation with a continuity
    correction agrees with scipy to the precision the paper quotes at these
    sample sizes (n >= 40).
    """
    nz = [v for v in values if v != 0]
    n = len(nz)
    if n < 10:
        return None
    ranks = sorted(range(n), key=lambda i: abs(nz[i]))
    w = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(nz[ranks[j + 1]]) == abs(nz[ranks[i]]):
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            if nz[ranks[k]] > 0:
                w += avg
        i = j + 1
    mean = n * (n + 1) / 4.0
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    if sd == 0:
        return None
    z = (abs(w - mean) - 0.5) / sd
    return math.erfc(z / math.sqrt(2.0))


def wilcoxon_exact_p(values):
    """Exact two-sided Wilcoxon signed-rank against zero.

    Used instead of `wilcoxon_p` wherever the unit of analysis is the cluster,
    because clustering is what makes n small and the normal approximation the
    other function uses is not defensible at n = 5.

    The whole point of clustering here: a cell is not an independent
    observation. Each query contributes up to sixteen of them, sharing a
    statement, a plan shape and a framework's rewrite of it. The intervals in
    this table already resample queries as clusters for exactly that reason, and
    a p-value over cells while the interval is over clusters asserts two
    different things about the same data.
    """
    nz = [v for v in values if v != 0]
    n = len(nz)
    if n == 0 or n > 25:
        return None
    order = sorted(range(n), key=lambda i: abs(nz[i]))
    rank = [0] * n
    for pos, i in enumerate(order):
        rank[i] = pos + 1
    w = sum(rank[i] for i in range(n) if nz[i] > 0)
    dist = [0] * (n * (n + 1) // 2 + 1)
    dist[0] = 1
    for r in range(1, n + 1):
        for s in range(len(dist) - 1, r - 1, -1):
            dist[s] += dist[s - r]
    tail = int(min(w, n * (n + 1) / 2.0 - w))
    return min(1.0, 2.0 * sum(dist[: tail + 1]) / float(1 << n))


def cluster_medians(pairs):
    """One value per cluster: the median of the cells sharing a query."""
    g = collections.defaultdict(list)
    for q, v in pairs:
        g[q].append(v)
    return [statistics.median(v) for v in g.values()]


def fmt_p(p):
    """Two significant figures, in the form Section 5 quotes them.

    An earlier version printed 0.001455 in one row and 5e-07 in the next, so the
    table disagreed with the prose beside it on both rows at once.
    """
    if p is None:
        return "--"
    if p >= 0.01:
        return "%.4g" % p
    mant, exp = ("%.1e" % p).split("e")
    return "$%s \\times 10^{%d}$" % (mant, int(exp))


def t_headline(cells, tpcc, out, rng):
    """The pooled result, both workloads, tested and bounded on the same unit.

    Both the interval and the p-value take the query as the unit. An earlier
    version resampled queries for the interval and tested cells for the p-value,
    which claimed independence in one column that the next column denied. The
    cost is visible in the transactional rows: with five transactions there are
    five clusters, and an exact signed-rank test on five values cannot report
    below 0.0625 however large the effect. That is stated rather than avoided by
    keeping a cell-level test that would have printed 10^-12.

    The transactional rows carry a range and not a bootstrap interval (C46). A
    percentile interval resampling five clusters can land on 43 distinct values
    for Django and 65 for SQLAlchemy out of 5^5 resamples, so the [+63.1,
    +144.9] it printed was a discrete artefact set in continuous-looking
    brackets. The five transaction medians are the whole of what those 40 cells
    say about spread, and they are what the column now reports.
    """
    body = []
    floor = None
    for fw in FRAMEWORKS:
        sel = [(q, th) for (_d, _s, q, f), th in cells.items() if f == fw]
        thetas = [th for _q, th in sel]
        cl = cluster_medians(sel)
        lo, hi = clustered_bootstrap(sel, rng)
        body.append(["TPC-H, " + FW_LABEL[fw],
                     "%+.2f\\%%" % pct(statistics.median(thetas)),
                     "[%+.1f, %+.1f]" % (pct(lo), pct(hi)),
                     fmt_p(wilcoxon_exact_p(cl)), len(thetas)])
    for fw in FRAMEWORKS:
        sel = [(q, lr) for (_d, _s, q, f), (lr, _ms) in tpcc.items() if f == fw]
        thetas = [th for _q, th in sel]
        cl = cluster_medians(sel)
        floor = 2.0 / float(1 << len(cl))
        per_tx = sorted(pct(th) for th in cl)
        body.append(["TPC-C, " + FW_LABEL[fw],
                     "%+.1f\\%%" % pct(statistics.median(thetas)),
                     "%+.1f to %+.1f" % (per_tx[0], per_tx[-1]),
                     fmt_p(wilcoxon_exact_p(cl)), len(thetas)])

    table(os.path.join(out, "tab_headline.tex"),
          "Median ORM overhead over the framework's own hand-written SQL "
          "baseline, pooled across the four systems and both configurations. "
          "Each TPC-H cell contributes the median over its eight blocks of the "
          "within-block log ratio; the TPC-C harness records a median per path "
          "rather than per block, so those cells are a ratio of medians. Cells "
          "are not independent -- one query contributes up to sixteen of them "
          "-- so both the 2{,}000-resample bootstrap interval and the exact "
          "two-sided Wilcoxon signed-rank test take the query or transaction as "
          "the unit. The analytical rows give that interval. The transactional "
          "rows give the range of their five transaction medians instead, "
          "because a percentile interval over five clusters can take only 43 "
          "and 65 distinct values and would read as more precision than five "
          "numbers hold. Five clusters also stop the exact test below %.4f "
          "whatever the effect size, so the transactional claim rests on the "
          "effect against the resolution in Table~\\ref{tab_r_noise} and not "
          "on its $p$." % floor,
          "tab_r_headline", "l r r r r",
          ["Workload, framework", "Median", "95\\% CI / range",
           "$p$ vs.\\ zero", "Cells"],
          body)


def t_per_statement(tpcc, out, base_spread):
    """One table for everything TPC-C costs per transaction.

    This was two tables, one of ratios and one of milliseconds, printing the
    same eighty cells twice in a paper carrying thirteen floats. They are one
    table now, and the column order says which to read: the ratio is meaningful
    within a framework and the milliseconds across them, because a ratio divides
    by that framework's own baseline and on these cells the two baselines
    disagree over a range of 0.45x to 2.15x (C44).

    A clean per-statement constant would leave the two "per stmt" columns flat.
    They are not, which is the finding: the cost is a magnitude, not a constant.
    """
    body = []
    for tid in sorted(STATEMENTS):
        dj, sa, name = STATEMENTS[tid]
        cells, ns = [tid, name], 0
        for fw, nstmt in (("django", dj), ("sqlalchemy", sa)):
            sel = [(lr, ms) for (_d, _s, q, f), (lr, ms) in tpcc.items()
                   if q == tid and f == fw]
            ns = len(sel)
            if not sel:
                cells += ["--", "--", "--", "--"]
                continue
            ms = statistics.median([m for _l, m in sel]) * 1000.0
            cells += [nstmt,
                      "%+.1f\\%%" % pct(statistics.median([l for l, _m in sel])),
                      "%.2f" % ms, "%.3f" % (ms / nstmt)]
        cells.append(ns)
        body.append(cells)

    table(os.path.join(out, "tab_per_statement.tex"),
          "What each TPC-C transaction costs, across the four systems and both "
          "configurations, and the per-statement model tested against it. "
          "Statement counts are read from the transaction code and differ for "
          "T1 because SQLAlchemy's unit of work defers its inserts to one flush "
          "while Django issues each immediately. Read the ratio within a "
          "framework and the milliseconds across them: a ratio divides by that "
          "framework's own hand-written baseline, and on these cells the two "
          "baselines differ over a range of %.2f$\\times$ to %.2f$\\times$ "
          "(Section~\\ref{sec:method}). All are ratios of medians rather than "
          "the block-paired ratios of the analytical grid, at a resolution "
          "Table~\\ref{tab_r_noise} reports as failing the study's own bound. A "
          "clean per-statement constant would leave each \\emph{per stmt} "
          "column flat."
          % (base_spread["lo_ratio"], base_spread["hi_ratio"]),
          "tab_r_per_statement", "l l r r r r r r r r r",
          ["", "Transaction",
           "Stmts", "Django", "ms", "per stmt",
           "Stmts", "SQLAlchemy", "ms", "per stmt", "$n$"],
          body, wide=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="1")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--identify", action="store_true",
                    help="print the real vendor name instead of the licensed "
                         "substitute (internal use only)")
    args = ap.parse_args()

    meas = os.path.join(REPO, "results", "sf%s" % args.scale, "measurements")
    out = os.path.abspath(args.outdir)
    os.makedirs(out, exist_ok=True)
    anon = not args.identify

    ratios, _censored = load_blocks(meas)
    cells = cell_estimates(ratios)
    tpcc = load_tpcc(meas)
    if not cells or not tpcc:
        print("no measurements found in %s" % meas, file=sys.stderr)
        return 2

    rng = random.Random(SEED)
    tpch_base, tpcc_base = baseline_spread(meas)
    failures = t_noise(meas, out, anon)
    t_headline(cells, tpcc, out, rng)
    t_per_statement(tpcc, out, tpcc_base)
    big = t_outliers(cells, orm_rows_returned(meas), out, anon)
    t_completeness(os.path.join(REPO, "results", "sf%s" % args.scale,
                                "all_results.csv"), out, anon)
    spans = t_sensitivity(cells, out, rng)

    print("\n%d TPC-H cells, %d TPC-C cells, %d above +100%%"
          % (len(cells), len(tpcc), len(big)))
    for name, d in (("TPC-H", tpch_base), ("TPC-C", tpcc_base)):
        print("baselines, %s: n=%d median %+.2f%% p10 %+.1f%% p90 %+.1f%% "
              "beyond 5%%: %.1f%%  range %.2fx-%.2fx"
              % (name, d["n"], d["median"], d["p10"], d["p90"], d["beyond5"],
                 d["lo_ratio"], d["hi_ratio"]))
    print("sensitivity: Django %+.2f%% to %+.2f%%, SQLAlchemy %+.2f%% to %+.2f%%"
          % (min(spans["django"]), max(spans["django"]),
             min(spans["sqlalchemy"]), max(spans["sqlalchemy"])))
    print("campaigns missing a pre-registered bound: %d of 16" % len(failures))
    for workload, dbms, schema, missed, med, p90, share, cap, margin in failures:
        print("  %-6s %-11s %-12s %-20s median %6.2f%%  p90 %6.2f%%  "
              "tail %5.1f%%  ceiling %s  margin %s"
              % (workload, dbms, schema, ",".join(missed), med, p90, share,
                 ("%g s" % cap) if cap else "--",
                 ("%.2fx" % margin) if margin else "--"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
