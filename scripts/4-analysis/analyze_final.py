#!/usr/bin/env python3
"""Generate every table and figure in the thesis and the paper from
results/all_results.csv.

Nothing here is transcribed by hand. If a measurement changes, the tables change
with it, and the numbers in the text are the numbers in the file.

    python3 analyze_final.py --results all_results.csv --outdir analysis
"""
import argparse, csv, json, os, statistics as st

import numpy as np
from scipy.stats import wilcoxon, mannwhitneyu

DBMS_ORDER = ["PostgreSQL", "MySQL", "SQL Server", "Oracle"]

# SQL Server's licence (section 6 of the Developer EULA the container accepts)
# forbids disclosing the results of any benchmark test of the software without
# Microsoft's prior written approval. Anonymising is the alternative to seeking
# that approval, not a step towards it, and it is the accepted practice: Leis et
# al. (PVLDB 2015), cited in this study's own related work, anonymised the
# commercial systems for the same reason.
#
# --anonymise turns it on for the paper. The thesis names the system and is a
# disclosure too; the same treatment is applied there before deposit, which is a
# separate decision from this flag.
ANON = {"SQL Server": "Commercial system A"}
anonymise = False


def dbname(db):
    return ANON.get(db, db) if anonymise else db


# Oracle's indexed TPC-H configuration is not a sample of the 22 queries. The
# edition caps user data at 12 GB, LINEITEM's secondary indexes are about 1.1 GB
# each on top of 7.22 GB of data, and the fourth raises ORA-12954 - so the
# configuration is reachable only for the queries whose working set fits.
#
# Those queries are the small ones, and the difference is not marginal: measured
# on Oracle's *non-indexed* configuration, where both groups ran, their median
# baseline is far below the sixteen they exclude. Any figure drawn from this
# configuration is drawn from much faster queries, and every table that shows it
# says so rather than reporting an n.
#
# The two medians were written here as constants until 2026-08-30, when the B1a
# campaign re-measured Q16 and moved the six's median from 0.539 s to 0.615 s
# while the caption went on saying 0.539. A number in a caption that does not
# come from the data is the same defect as C22, one layer further out, so it is
# computed now. `oracle_indexed_note(rows)` takes the rows the tables were built
# from, and a caption cannot go stale while the table beside it moves.
ORACLE_INDEXED_QUERIES = ("Q02", "Q11", "Q13", "Q16", "Q17", "Q22")


def oracle_indexed_note(rows):
    """The caption for any table showing Oracle's indexed configuration."""
    # Every row carrying a baseline time, not only the rows with a complete
    # overhead pair. The claim is about how expensive these six queries are, and
    # filtering on ORM success drops Q13's and Q17's Django baselines - two of
    # the slower queries among the six, whose ORM paths are inexpressible and
    # over the timeout. That filtering moved the median from 0.615 s to 0.484 s
    # and made the six look smaller than they are.
    base = [(r["query_id"], float(r["direct_sql_execution_s"])) for r in rows
            if r["dbms"] == "Oracle" and r["schema_config"] == "Non-Indexed"
            and r.get("benchmark") == "tpch" and r.get("direct_sql_execution_s")]
    fit = [s for q, s in base if q in ORACLE_INDEXED_QUERIES]
    excl = [s for q, s in base if q not in ORACLE_INDEXED_QUERIES]
    if not fit or not excl:
        return ("Oracle's indexed row is six queries -- %s -- not a sample of the "
                "22, and the comparison that quantifies the gap could not be "
                "computed from these rows." % ", ".join(ORACLE_INDEXED_QUERIES))
    a, b = st.median(fit), st.median(excl)
    return ("Oracle's indexed row is six queries -- %s -- not a sample of the 22. "
            "The edition caps user data at 12~GB and the rest exceed it "
            "(\\texttt{ORA-12954}), and the six that fit are the small ones: on "
            "Oracle's non-indexed configuration, where both groups ran, their "
            "median baseline is %.3f~s against %.3f~s for the sixteen they "
            "exclude, a factor of %.0f. Read it as a statement about those six."
            % (", ".join(ORACLE_INDEXED_QUERIES), a, b, b / a))


def is_oracle_indexed(r):
    return (r["dbms"] == "Oracle" and r["schema_config"] == "Indexed"
            and r["benchmark"] == "tpch")


SCHEMAS = ["Indexed", "Non-Indexed"]
FRAMEWORKS = [("DJANGO", "Django"), ("SQLALCHEMY", "SQLAlchemy")]
# The outlier and faster tables used to print the framework with .title(),
# which renders SQLALCHEMY as "Sqlalchemy" - four times in the paper's largest
# table before a reviewer caught it (2026-08-31). The label comes from
# FRAMEWORKS now, the same place every other table gets it.
FW_LABEL = dict(FRAMEWORKS)
BENCH = [("tpch", "TPC-H"), ("tpcc", "TPC-C")]
SEED = 20260801


# --------------------------------------------------------------- helpers

def load(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        for k in ("overhead_percentage", "direct_sql_execution_s",
                  "total_orm_execution_s", "rows_returned", "orm_median_qerror",
                  "orm_max_qerror", "sql_median_qerror", "sql_max_qerror",
                  "overhead_abs_s", "sql_cv_pct", "orm_cv_pct"):
            try:
                r[k] = float(r[k])
            except (TypeError, ValueError):
                r[k] = None
    return rows


def usable(rows):
    """Rows with a complete ORM/SQL pair that is not marked invalid."""
    return [r for r in rows if r["overhead_percentage"] is not None
            and r["sql_status"] not in ("invalid",)
            and r["orm_status"] not in ("invalid",)]


VCOLS = ("validated_orm_path_is_orm", "validated_results_match",
         "validated_baselines_match", "validated_orm_equals_sql",
         "validated_rows_nonzero")


def is_c23(r):
    """Measured, but the validator never passed it - defect C23.

    The five ``validated_*`` columns carry the campaign's own verdict for the
    query on that system and schema. Anything that is not ``pass`` - a failed
    check, a timeout on the validator's clock, or the validator stopping at
    Django's Q13 exception before it compared this path - means the timing
    stands on a statement whose result equality was never confirmed. Such
    cells stay in every table by decision (2026-08-29) and are marked.
    ``not_recorded`` is a different condition: no validation log survives for
    that campaign. It is stated in the captions rather than marked per cell.
    """
    return any(r.get(c, "") not in ("pass", "not_recorded", "") for c in VCOLS)


def not_recorded(r):
    return all(r.get(c, "") == "not_recorded" for c in VCOLS)


def flag(r):
    return "$^{\\dagger}$" if is_c23(r) else ""


DAGGER_NOTE = ("$^{\\dagger}$~measured without a passing validation (C23): the "
               "timing is real, the equality of the result with the baseline "
               "was never confirmed.")

# Set once in main() from the loaded rows and appended to the caption of every
# pooled TPC-H table, so the reader meets the caveat where the number is.
C23_NOTE = ""


def boot_ci(v, n=10000, seed=SEED):
    if len(v) < 3:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    b = [np.median(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return tuple(np.percentile(b, [2.5, 97.5]))


def tex_escape(s):
    return str(s).replace("%", r"\%").replace("&", r"\&").replace("_", r"\_")


def table(path, caption, label, cols, header, body_rows, wide=False, note=None):
    """One LaTeX table. ``wide`` wraps the tabular in a \\resizebox so it fits
    an A4 text block - the thesis used to add that by hand after every
    regeneration, with a comment asking the next person to re-apply it.
    ``note`` is appended to the caption; it carries the C23 disclosure."""
    if note:
        caption = caption.rstrip() + " " + note
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


def pct(x, d=1):
    return ("%+.*f\\%%" % (d, x)) if x is not None else "--"


# --------------------------------------------------------------- tables

def t_headline(rows, out):
    """The result the whole study turns on: workload, not framework."""
    body = []
    for bkey, blabel in BENCH:
        for fkey, flabel in FRAMEWORKS:
            v = [r["overhead_percentage"] for r in rows
                 if r["benchmark"] == bkey and r["orm"] == fkey]
            if not v:
                continue
            lo, hi = boot_ci(v)
            _, p = wilcoxon(v)
            body.append([f"{blabel}, {flabel}", pct(st.median(v)),
                         "[%+.1f, %+.1f]" % (lo, hi),
                         ("$<10^{-4}$" if p < 1e-4 else "%.3f" % p), len(v)])
    table(os.path.join(out, "tab_headline.tex"),
          "Median ORM overhead over the framework's own hand-written SQL "
          "baseline, pooled across all four database systems and both schema "
          "configurations. The confidence interval is a 10{,}000-iteration "
          "bootstrap of the median; the $p$-value is a Wilcoxon signed-rank "
          "test against zero overhead.",
          "tab_r_headline", "l r r r r",
          ["Workload, framework", "Median", "95\\% CI", "$p$ vs.\\ zero", "$n$"],
          body, note=C23_NOTE)


def t_by_system(rows, out, all_rows=None):
    body = []
    for db in DBMS_ORDER:
        for sc in SCHEMAS:
            for bkey, blabel in BENCH:
                cells = []
                for fkey, _ in FRAMEWORKS:
                    v = [r["overhead_percentage"] for r in rows
                         if r["dbms"] == db and r["schema_config"] == sc
                         and r["benchmark"] == bkey and r["orm"] == fkey]
                    cells.append((pct(st.median(v)) if v else "--", len(v)))
                if cells[0][1] == 0 and cells[1][1] == 0:
                    continue
                body.append([dbname(db), sc, blabel,
                             cells[0][0], cells[0][1], cells[1][0], cells[1][1]])
    table(os.path.join(out, "tab_by_system.tex"),
          "Median ORM overhead by database system, schema configuration and "
          "workload.",
          "tab_r_by_system", "l l l r r r r",
          ["DBMS", "Schema", "Workload", "Django", "$n$", "SQLAlchemy", "$n$"],
          body, note=oracle_indexed_note(all_rows or rows) + " " + C23_NOTE)


def t_stats(rows, out):
    """Paired framework comparison, and the workload contrast."""
    body = []
    for bkey, blabel in BENCH:
        d = {}
        for r in rows:
            if r["benchmark"] != bkey:
                continue
            d.setdefault((r["dbms"], r["schema_config"], r["query_id"]), {})[
                r["orm"]] = r["overhead_percentage"]
        pairs = [(v["DJANGO"], v["SQLALCHEMY"]) for v in d.values()
                 if "DJANGO" in v and "SQLALCHEMY" in v]
        dj = np.array([a for a, _ in pairs])
        sa = np.array([b for _, b in pairs])
        _, p = wilcoxon(dj, sa)
        diff = dj - sa
        cd = float(np.mean(diff) / np.std(diff, ddof=1))
        body.append([f"Django vs.\\ SQLAlchemy, {blabel}", len(pairs),
                     pct(float(np.median(dj))), pct(float(np.median(sa))),
                     ("$<0.001$" if p < 1e-3 else "%.3f" % p), "%.2f" % cd])

    a = [r["overhead_percentage"] for r in rows if r["benchmark"] == "tpch"]
    b = [r["overhead_percentage"] for r in rows if r["benchmark"] == "tpcc"]
    _, p = mannwhitneyu(a, b)
    body.append(["TPC-H vs.\\ TPC-C, both frameworks", f"{len(a)}/{len(b)}",
                 pct(st.median(a)), pct(st.median(b)),
                 ("$<10^{-20}$" if p < 1e-20 else "%.3g" % p), "--"])

    table(os.path.join(out, "tab_stats.tex"),
          "Statistical comparisons. The framework rows are paired Wilcoxon "
          "signed-rank tests over per-query overhead, paired within "
          "(system, schema, query); the effect size is Cohen's $d_z$, the "
          "mean of the paired differences divided by their standard "
          "deviation. The final row is an unpaired Mann--Whitney $U$ test "
          "contrasting the two workloads.",
          "tab_r_stats", "l r r r r r",
          ["Comparison", "$n$", "Django", "SQLAlchemy", "$p$", "Cohen's $d_z$"],
          body, wide=True, note=C23_NOTE)


def t_tpcc(rows, out):
    body = []
    for t in ("T1", "T2", "T3", "T4", "T5"):
        sub = [r for r in rows if r["query_id"] == t]
        if not sub:
            continue
        name = sub[0]["query_name"]
        cells = []
        for fkey, _ in FRAMEWORKS:
            v = [r["overhead_percentage"] for r in sub if r["orm"] == fkey]
            cells.append(pct(st.median(v)) if v else "--")
        n = len([r for r in sub if r["orm"] == "DJANGO"])
        body.append([t, name, cells[0], cells[1], n])
    table(os.path.join(out, "tab_tpcc.tex"),
          "Median ORM overhead per TPC-C transaction, pooled across all four "
          "database systems and both schema configurations. Each transaction is "
          "a short sequence of statements, so per-statement framework cost is a "
          "large fraction of the total rather than a rounding error.",
          "tab_r_tpcc", "l l r r r",
          ["", "Transaction", "Django", "SQLAlchemy", "$n$ per framework"], body)


def t_outliers(rows, out, threshold=100.0):
    """Every cell beyond the threshold, not a top-k. Section 6 reasons about
    the full set - nineteen cells, ten accounted for - and until 2026-08-31
    this table showed the ten largest under a prose sentence claiming it
    listed all nineteen. A reviewer counted. Selecting by the stated criterion
    makes the table and the sentence the same claim, and the caption's counts
    are computed from the selection so the two cannot drift apart again."""
    tp = sorted([r for r in rows if r["benchmark"] == "tpch"
                 and r["overhead_percentage"] > threshold],
                key=lambda r: -r["overhead_percentage"])
    body = []
    for r in tp:
        body.append([r["query_id"] + flag(r), dbname(r["dbms"]), r["schema_config"],
                     FW_LABEL[r["orm"]],
                     "%.3f" % r["direct_sql_execution_s"],
                     "%.3f" % r["total_orm_execution_s"],
                     pct(r["overhead_percentage"], 0),
                     int(r["rows_returned"]) if r["rows_returned"] else "--"])
    small = sum(1 for r in tp if r["rows_returned"] is not None
                and r["rows_returned"] <= 100)
    table(os.path.join(out, "tab_outliers.tex"),
          "All %d analytical cells with overhead beyond $+%d\\%%$, where the "
          "ORM path costs more than double its own baseline. %d of the %d "
          "return at most a hundred rows, so object materialisation cannot "
          "account for the gap; the cost is in how the optimiser treats the "
          "statement the ORM emitted." % (len(tp), int(threshold),
                                          small, len(tp)),
          "tab_r_outliers", "l l l l r r r r",
          ["Query", "DBMS", "Schema", "Framework", "SQL (s)", "ORM (s)",
           "Overhead", "Rows"], body, wide=True,
          note=(DAGGER_NOTE if any(is_c23(r) for r in tp) else None))


def t_faster(rows, out, k=8):
    tp = sorted([r for r in rows if r["benchmark"] == "tpch"],
                key=lambda r: r["overhead_percentage"])
    body = []
    for r in tp[:k]:
        body.append([r["query_id"] + flag(r), dbname(r["dbms"]), r["schema_config"],
                     FW_LABEL[r["orm"]],
                     "%.3f" % r["direct_sql_execution_s"],
                     "%.3f" % r["total_orm_execution_s"],
                     pct(r["overhead_percentage"], 0),
                     int(r["rows_returned"]) if r["rows_returned"] else "--"])
    table(os.path.join(out, "tab_faster.tex"),
          "Configurations where the ORM path was faster than the hand-written "
          "baseline. The same query can appear among the largest overheads on "
          "one system and among the largest savings on another, which is the "
          "clearest evidence that the effect belongs to the optimiser rather "
          "than to the framework.",
          "tab_r_faster", "l l l l r r r r",
          ["Query", "DBMS", "Schema", "Framework", "SQL (s)", "ORM (s)",
           "Overhead", "Rows"], body, wide=True,
          note=(DAGGER_NOTE if any(is_c23(r) for r in tp[:k]) else None))


def t_complexity(rows, out):
    order = ["Simple", "Medium", "Complex", "Very Complex"]
    body = []
    for band in order:
        sub = [r for r in rows if r["complexity_band"] == band
               and r["benchmark"] == "tpch"]
        if not sub:
            continue
        cells = []
        for fkey, _ in FRAMEWORKS:
            v = [r["overhead_percentage"] for r in sub if r["orm"] == fkey]
            cells.append(pct(st.median(v)) if v else "--")
        med_sql = st.median([r["direct_sql_execution_s"] for r in sub])
        body.append([band, "%.2f" % med_sql, cells[0], cells[1],
                     len([r for r in sub if r["orm"] == "DJANGO"])])
    table(os.path.join(out, "tab_complexity.tex"),
          "Median ORM overhead by TPC-H complexity band. Overhead does not rise "
          "with query complexity: the band that costs the most to execute is "
          "not the band the ORM makes worse.",
          "tab_r_complexity", "l r r r r",
          ["Band", "Median SQL (s)", "Django", "SQLAlchemy", "$n$"], body,
          note=C23_NOTE)


def t_indexing(rows, out, all_rows=None):
    body = []
    for db in DBMS_ORDER:
        for fkey, flabel in FRAMEWORKS:
            cells = []
            for sc in SCHEMAS:
                v = [r["overhead_percentage"] for r in rows
                     if r["dbms"] == db and r["orm"] == fkey
                     and r["schema_config"] == sc and r["benchmark"] == "tpch"]
                cells.append((pct(st.median(v)) if v else "--", len(v)))
            if cells[0][1] == 0 and cells[1][1] == 0:
                continue
            body.append([dbname(db), flabel, cells[0][0], cells[0][1],
                         cells[1][0], cells[1][1]])
    table(os.path.join(out, "tab_indexing.tex"),
          "ORM overhead under the indexed and non-indexed physical designs, "
          "TPC-H. Indexing changes absolute execution time by orders of "
          "magnitude and leaves the relative cost of the ORM essentially where "
          "it was.",
          "tab_r_indexing", "l l r r r r",
          ["DBMS", "Framework", "Indexed", "$n$", "Non-Indexed", "$n$"], body,
          note=oracle_indexed_note(all_rows or rows) + " " + C23_NOTE)


def t_completeness(all_rows, out):
    body = []
    for db in DBMS_ORDER:
        for bkey, blabel in BENCH:
            sub = [r for r in all_rows if r["dbms"] == db
                   and r["benchmark"] == bkey]
            comp = sum(1 for r in sub if r["overhead_percentage"] is not None
                       and r["sql_status"] not in ("invalid",))
            inval = sum(1 for r in sub if r["sql_status"] == "invalid"
                        or r["orm_status"] == "invalid")
            nrun = sum(1 for r in sub if r["sql_status"] == "not_run"
                       and r["orm_status"] == "not_run")
            body.append([dbname(db), blabel, len(sub), comp,
                         len(sub) - comp - inval - nrun, inval, nrun])
    table(os.path.join(out, "tab_completeness.tex"),
          "Coverage of the design grid. Every cell of the $4 \\times 2 \\times "
          "2 \\times 27$ design is present in the results file; cells that were "
          "not measured carry a status and a reason rather than being absent.",
          "tab_r_completeness", "l l r r r r r",
          ["DBMS", "Workload", "Cells", "Complete", "Partial", "Invalid",
           "Not run"], body)


def t_perquery(rows, out):
    body = []
    for q in sorted({r["query_id"] for r in rows if r["benchmark"] == "tpch"}):
        sub = [r for r in rows if r["query_id"] == q]
        if not sub:
            continue
        cells = []
        for fkey, _ in FRAMEWORKS:
            v = [r["overhead_percentage"] for r in sub if r["orm"] == fkey]
            cells.append((pct(st.median(v)) if v else "--",
                          "%+.0f" % min(v) if v else "--",
                          "%+.0f" % max(v) if v else "--"))
        body.append([q, sub[0]["query_name"], sub[0]["complexity_band"],
                     cells[0][0], f"[{cells[0][1]}, {cells[0][2]}]",
                     cells[1][0], f"[{cells[1][1]}, {cells[1][2]}]"])
    table(os.path.join(out, "tab_overhead_perquery.tex"),
          "Median ORM overhead per TPC-H query, with the range across the four "
          "database systems and two schema configurations in brackets. The "
          "spread within a single query is larger than the difference between "
          "the two frameworks.",
          "tab_r_overhead_perquery", "l l l r l r l",
          ["Query", "Name", "Band", "Django", "range", "SQLAlchemy", "range"],
          body, wide=True, note=C23_NOTE)


def _q(v, p):
    v = sorted(v)
    return v[int(p * (len(v) - 1))]


def t_noise(rows, out):
    """The measurement's own resolution, stated before any overhead is read
    against it. A cell whose overhead is smaller than its own run-to-run
    variation cannot be told from zero; how many cells that is, is the first
    number a reader needs."""
    body, digest = [], {}
    for bkey, blabel in BENCH:
        sub = [r for r in rows if r["benchmark"] == bkey
               and r["sql_cv_pct"] is not None and r["orm_cv_pct"] is not None]
        if not sub:
            continue
        cs = [r["sql_cv_pct"] for r in sub]
        co = [r["orm_cv_pct"] for r in sub]
        ov = [abs(r["overhead_percentage"]) for r in sub]
        below = sum(1 for r in sub if abs(r["overhead_percentage"]) < r["sql_cv_pct"])
        faster = sum(1 for r in sub if r["overhead_percentage"] < 0)
        body.append([blabel, len(sub),
                     "%.1f / %.1f / %.1f" % (st.median(cs), _q(cs, .75), _q(cs, .9)),
                     "%.1f / %.1f / %.1f" % (st.median(co), _q(co, .75), _q(co, .9)),
                     "%.1f\\%%" % st.median(ov),
                     "%d (%.0f\\%%)" % (below, 100.0 * below / len(sub)),
                     "%d (%.0f\\%%)" % (faster, 100.0 * faster / len(sub))])
        digest[bkey] = {"n": len(sub),
                        "sql_cv_p50_p75_p90": [round(st.median(cs), 1), round(_q(cs, .75), 1), round(_q(cs, .9), 1)],
                        "orm_cv_p50_p75_p90": [round(st.median(co), 1), round(_q(co, .75), 1), round(_q(co, .9), 1)],
                        "median_abs_overhead_pct": round(st.median(ov), 1),
                        "cells_below_own_cv": below, "cells_orm_faster": faster}
    table(os.path.join(out, "tab_noise.tex"),
          "Run-to-run resolution of the measurement. CV is the coefficient of "
          "variation across the three kept repetitions of one cell, on each "
          "access path. A cell whose overhead is smaller than its own CV cannot "
          "be told from zero. On analytical queries that is the typical cell, and "
          "the ORM path is faster than its own baseline about as often as it is "
          "slower; on transactions the overhead clears the noise by an order of "
          "magnitude.",
          "tab_r_noise", "l r r r r r r",
          ["Workload", "$n$", "SQL CV\\% p50/p75/p90", "ORM CV\\% p50/p75/p90",
           "Median $|$overhead$|$", "$|$overhead$|$ $<$ own CV", "ORM faster"],
          body, wide=True, note=C23_NOTE)
    return digest


def t_base(rows, out):
    """Overhead in seconds against the baseline's own runtime. This is the
    reviewer's Table 8 objection answered in its own currency: a ratio hides
    whether a constant is being divided by a small base or a large one, and
    seconds do not."""
    tp = [r for r in rows if r["benchmark"] == "tpch"
          and r["overhead_abs_s"] is not None and r["direct_sql_execution_s"]]
    bins = [(0, 1, "$<$ 1 s"), (1, 10, "1--10 s"), (10, 100, "10--100 s"),
            (100, float("inf"), "$\\geq$ 100 s")]
    body, digest = [], {}
    for lo, hi, lab in bins:
        sub = [r["overhead_abs_s"] for r in tp if lo <= r["direct_sql_execution_s"] < hi]
        if not sub:
            continue
        s = sorted(sub)
        body.append([lab, len(sub), "%+.3f" % st.median(sub),
                     "%+.3f" % s[len(s) // 4], "%+.3f" % s[3 * len(s) // 4],
                     "%+.1f" % max(sub)])
        digest[lab.replace("$", "").replace("\\", "")] = {
            "n": len(sub), "median_s": round(st.median(sub), 3),
            "p25_s": round(s[len(s) // 4], 3), "p75_s": round(s[3 * len(s) // 4], 3),
            "max_s": round(max(sub), 2)}
    xs = np.log10([r["direct_sql_execution_s"] for r in tp])
    ys = np.array([r["overhead_abs_s"] for r in tp])
    rr = float(np.corrcoef(xs, ys)[0, 1])
    table(os.path.join(out, "tab_overhead_by_base.tex"),
          "ORM overhead in seconds against the baseline's own runtime, TPC-H, "
          "all systems and both schemas. Pearson $r$ between $\\log_{10}$ base "
          "runtime and overhead in seconds is %.2f: the cost does not scale with "
          "the query. It is not a constant either -- the medians rise and the "
          "spread widens with the base -- which is why a single overhead ratio "
          "across systems whose base runtimes differ by orders of magnitude "
          "says nothing." % rr,
          "tab_r_overhead_by_base", "l r r r r r",
          ["Base runtime", "$n$", "Median (s)", "p25", "p75", "Max"],
          body, note=C23_NOTE)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    ax.scatter([r["direct_sql_execution_s"] for r in tp],
               [r["overhead_abs_s"] for r in tp],
               s=12, alpha=0.55, color="#2B6CB0", edgecolor="none")
    ax.set_xscale("log")
    ax.set_yscale("symlog", linthresh=1)
    ax.axhline(0, color="black", lw=0.8, ls=":")
    ax.set_xlabel("hand-written SQL runtime (s, log)")
    ax.set_ylabel("ORM overhead (s, symlog)")
    ax.set_title("Overhead in seconds neither tracks the base nor holds still "
                 "(r = %.2f)" % rr, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_overhead_by_base.pdf"))
    plt.close(fig)
    return {"pearson_r_log10base_vs_overhead_s": round(rr, 3), "bins": digest}


# -------------------------------------------------------------- figures

def figures(rows, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "figure.dpi": 150,
                         "axes.spines.top": False, "axes.spines.right": False})
    GREY, BLUE = "#5A6672", "#2B6CB0"

    # 1. the headline: workload dominates
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    data, labels = [], []
    for bkey, blabel in BENCH:
        for fkey, flabel in FRAMEWORKS:
            v = [r["overhead_percentage"] for r in rows
                 if r["benchmark"] == bkey and r["orm"] == fkey]
            if v:
                data.append(v)
                labels.append(f"{blabel}\n{flabel}")
    bp = ax.boxplot(data, labels=labels, showfliers=False, patch_artist=True,
                    widths=0.55, medianprops=dict(color="black", lw=1.4))
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(GREY if i < 2 else BLUE)
        patch.set_alpha(0.35)
    ax.axhline(0, color="black", lw=0.8, ls=":")
    ax.set_ylabel("ORM overhead over hand-written SQL (\\%)"
                  .replace("\\%", "%"))
    ax.set_title("Analytical queries hide the cost of an ORM; "
                 "transactions expose it", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_workload.pdf"))
    plt.close(fig)

    # 2. per system
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    x = np.arange(len(DBMS_ORDER))
    w = 0.2
    for i, (bkey, blabel) in enumerate(BENCH):
        for j, (fkey, flabel) in enumerate(FRAMEWORKS):
            vals = []
            for db in DBMS_ORDER:
                v = [r["overhead_percentage"] for r in rows
                     if r["dbms"] == db and r["benchmark"] == bkey
                     and r["orm"] == fkey]
                vals.append(st.median(v) if v else np.nan)
            ax.bar(x + (i * 2 + j) * w - 1.5 * w, vals, w,
                   label=f"{blabel} {flabel}",
                   color=(GREY if i == 0 else BLUE),
                   alpha=(0.55 if j == 0 else 0.9))
    ax.set_xticks(x)
    ax.set_xticklabels([dbname(d) for d in DBMS_ORDER])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("median overhead (%)")
    ax.legend(frameon=False, fontsize=7.5, ncol=2)
    ax.set_title("The pattern holds across all four systems", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_by_system.pdf"))
    plt.close(fig)

    # 3. overhead against result size — materialisation would show here
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    tp = [r for r in rows if r["benchmark"] == "tpch"
          and r["rows_returned"] and r["rows_returned"] > 0]
    ax.scatter([r["rows_returned"] for r in tp],
               [r["overhead_percentage"] for r in tp],
               s=12, alpha=0.55, color=BLUE, edgecolor="none")
    ax.set_xscale("log")
    ax.set_yscale("symlog", linthresh=10)
    ax.axhline(0, color="black", lw=0.8, ls=":")
    ax.set_xlabel("rows returned (log)")
    ax.set_ylabel("overhead (%, symlog)")
    ax.set_title("Overhead does not grow with the number of rows materialised",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_rows.pdf"))
    plt.close(fig)

    # 4. per-transaction TPC-C
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    ts = ["T1", "T2", "T3", "T4", "T5"]
    names = []
    for j, (fkey, flabel) in enumerate(FRAMEWORKS):
        vals = []
        for t in ts:
            v = [r["overhead_percentage"] for r in rows if r["query_id"] == t
                 and r["orm"] == fkey]
            vals.append(st.median(v) if v else np.nan)
        ax.bar(np.arange(len(ts)) + j * 0.38 - 0.19, vals, 0.38, label=flabel,
               color=(GREY if j == 0 else BLUE), alpha=0.8)
    for t in ts:
        m = [r["query_name"] for r in rows if r["query_id"] == t]
        names.append(m[0] if m else t)
    ax.set_xticks(np.arange(len(ts)))
    ax.set_xticklabels(names, rotation=20, ha="right")
    ax.set_ylabel("median overhead (%)")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("TPC-C: every transaction type pays, by different amounts",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_tpcc.pdf"))
    plt.close(fig)
    print("  wrote 4 figures")


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="all_results.csv")
    ap.add_argument("--outdir", default="analysis")
    ap.add_argument("--anonymise", action="store_true",
                    help="print SQL Server as 'Commercial system A'. Its licence "
                         "forbids disclosing benchmark results for the named "
                         "product without the vendor's written approval; "
                         "anonymising is the alternative to seeking that "
                         "approval, and is what Leis et al. (PVLDB 2015) did for "
                         "the same reason. Off by default so the thesis keeps "
                         "the names it currently uses; on for the paper.")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    global anonymise
    anonymise = args.anonymise
    if anonymise:
        print("  anonymised: " + ", ".join(f"{k} -> {v}" for k, v in ANON.items()))

    all_rows = load(args.results)
    rows = usable(all_rows)
    print(f"{len(all_rows)} rows in the design, {len(rows)} usable measurements")

    # The C23 disclosure, computed once and carried on every pooled TPC-H
    # caption: how many cells stand on an unverified statement, and how far the
    # pooled medians would move without them.
    global C23_NOTE
    tp = [r for r in rows if r["benchmark"] == "tpch"]
    c23 = [r for r in tp if is_c23(r)]
    deltas = []
    for fkey, _ in FRAMEWORKS:
        v_all = [r["overhead_percentage"] for r in tp if r["orm"] == fkey]
        v_ex = [r["overhead_percentage"] for r in tp if r["orm"] == fkey and not is_c23(r)]
        if v_all and v_ex:
            deltas.append(abs(st.median(v_all) - st.median(v_ex)))
    unrecorded = sorted({(r["dbms"], r["schema_config"]) for r in tp if not_recorded(r)})
    C23_NOTE = ("%d TPC-H cells carry an overhead without a passing validation "
                "(defect C23) and are included; excluding them moves the pooled "
                "TPC-H medians by at most %.1f points." % (len(c23), max(deltas) if deltas else 0.0))
    if unrecorded:
        C23_NOTE += (" No validation log survives for %s, whose cells are "
                     "unverified in the other direction."
                     % " and for ".join(f"{d} {s.lower()}" for d, s in unrecorded))
    print(f"  {len(c23)} C23 cells; pooled medians move by at most "
          f"{max(deltas) if deltas else 0.0:.1f} points without them")

    t_headline(rows, args.outdir)
    t_by_system(rows, args.outdir, all_rows)
    t_stats(rows, args.outdir)
    t_tpcc(rows, args.outdir)
    t_outliers(rows, args.outdir)
    t_faster(rows, args.outdir)
    t_complexity(rows, args.outdir)
    t_indexing(rows, args.outdir, all_rows)
    t_completeness(all_rows, args.outdir)
    t_perquery(rows, args.outdir)
    noise = t_noise(rows, args.outdir)
    base = t_base(rows, args.outdir)
    figures(rows, args.outdir)

    # a machine-readable digest, so prose can quote numbers without transcription
    digest = {"n_design": len(all_rows), "n_usable": len(rows)}
    for bkey, blabel in BENCH:
        for fkey, flabel in FRAMEWORKS:
            v = [r["overhead_percentage"] for r in rows
                 if r["benchmark"] == bkey and r["orm"] == fkey]
            if not v:
                continue
            lo, hi = boot_ci(v)
            _, p = wilcoxon(v)
            digest[f"{bkey}_{fkey.lower()}"] = {
                "n": len(v), "median": round(st.median(v), 2),
                "ci": [round(lo, 2), round(hi, 2)], "p_vs_zero": float(p),
                "min": round(min(v), 1), "max": round(max(v), 1)}
    a = [r["overhead_percentage"] for r in rows if r["benchmark"] == "tpch"]
    b = [r["overhead_percentage"] for r in rows if r["benchmark"] == "tpcc"]
    _, p = mannwhitneyu(a, b)
    digest["workload_contrast"] = {
        "tpch_median": round(st.median(a), 2), "tpcc_median": round(st.median(b), 2),
        "p": float(p), "n_tpch": len(a), "n_tpcc": len(b)}
    digest["noise_floor"] = noise
    digest["overhead_by_base"] = base
    digest["c23_cells"] = [f'{r["query_id"]} {r["dbms"]} {r["schema_config"]} {r["orm"]}'
                           for r in rows if is_c23(r)]
    digest["c23_note"] = C23_NOTE
    json.dump(digest, open(os.path.join(args.outdir, "digest.json"), "w"), indent=1)
    print("  wrote digest.json")


if __name__ == "__main__":
    main()
