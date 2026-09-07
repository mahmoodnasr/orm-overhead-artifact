#!/usr/bin/env python3
"""Regenerate the paper's and thesis's six tables from the corrected results.

Scope is deliberately unchanged from the version under review: PostgreSQL,
TPC-H SF10, both schema configurations. The table names, captions, column
layouts and labels are the ones already in the manuscript. Only the numbers
move.

    python3 regen_pg_tables.py --results all_results.csv --outdir tables
"""
import argparse, csv, os, statistics as st

import numpy as np
from scipy.stats import wilcoxon

SCHEMAS = [("Indexed", "indexed"), ("Non-Indexed", "non-indexed")]
FRAMEWORKS = [("DJANGO", "Django"), ("SQLALCHEMY", "Sqlalchemy")]
BANDS = ["Simple", "Medium", "Complex", "Very Complex"]
BAND_ABBR = {"Simple": "S", "Medium": "M", "Complex": "C", "Very Complex": "V"}
SEED = 20260801


def load(path):
    rows = []
    for r in csv.DictReader(open(path)):
        if r["dbms"] != "PostgreSQL" or r["benchmark"] != "tpch":
            continue
        for k in ("overhead_percentage", "direct_sql_execution_s",
                  "total_orm_execution_s"):
            try:
                r[k] = float(r[k])
            except (TypeError, ValueError):
                r[k] = None
        rows.append(r)
    return rows


def ok(rows):
    return [r for r in rows if r["overhead_percentage"] is not None
            and r["sql_status"] not in ("invalid",)
            and r["orm_status"] not in ("invalid",)]


def boot(v, seed=SEED):
    rng = np.random.default_rng(seed)
    b = [np.median(rng.choice(v, len(v), replace=True)) for _ in range(10000)]
    return tuple(np.percentile(b, [2.5, 97.5]))


def num(x, d=1):
    """LaTeX-safe signed number using the manuscript's existing convention."""
    s = f"{x:.{d}f}"
    return s.replace("-", "$-$")


def write(path, text):
    open(path, "w").write(text)
    print("  ", os.path.basename(path))


# ------------------------------------------------------------------ tables

def completeness(rows, out):
    body = []
    for slabel, skey in SCHEMAS:
        for fkey, flabel in FRAMEWORKS:
            for path, plabel in (("orm", "ORM"), ("sql", "SQL")):
                sub = [r for r in rows if r["schema_config"] == slabel
                       and r["orm"] == fkey]
                done = sum(1 for r in sub
                           if r[f"{path}_status"] == "ok")
                to = sum(1 for r in sub if r[f"{path}_status"] == "timeout")
                nr = len(sub) - done - to
                body.append(f"{skey} & {flabel} & {plabel} & {done} & {to} & "
                            f"{nr}\\\\ \\hline")
    write(os.path.join(out, "tab_completeness.tex"),
          "\\begin{table}[H]\n"
          "\\caption{Campaign completeness. Each cell counts the 22 TPC-H "
          "queries by outcome.}\n"
          "\\label{tab_r_completeness}\n\\centering\n"
          "\\renewcommand{\\arraystretch}{1.2}\n"
          "\\begin{tabular}{l l l r r r}\n\\hline\\hline\n"
          "\\textbf{Schema} & \\textbf{Framework} & \\textbf{Path} & "
          "\\textbf{Completed} & \\textbf{Timed out} & \\textbf{Not run}\\\\\n"
          "\\hline\\hline\n" + "\n".join(body) +
          "\n\\hline\n\\end{tabular}\n\\end{table}\n")


def overhead_summary(rows, out):
    body = []
    for slabel, skey in SCHEMAS:
        for fkey, flabel in FRAMEWORKS:
            v = [r["overhead_percentage"] for r in rows
                 if r["schema_config"] == slabel and r["orm"] == fkey]
            lo, hi = boot(v)
            body.append(f"{flabel}, {skey} & {num(st.median(v))}\\% & "
                        f"{num(st.mean(v))}\\% & [{num(lo)}, {num(hi)}] & "
                        f"{len(v)}\\\\ \\hline")
    write(os.path.join(out, "tab_overhead_summary.tex"),
          "\\begin{table}[H]\n"
          "\\caption{Median ORM overhead over the hand-written SQL baseline, "
          "TPC-H SF10 on PostgreSQL. A negative value means the ORM path was "
          "marginally faster. The interval is a 10{,}000-iteration bootstrap of "
          "the median.}\n"
          "\\label{tab_r_overhead_summary}\n\\centering\n"
          "\\renewcommand{\\arraystretch}{1.2}\n"
          "\\begin{tabular}{l r r r r}\n\\hline\\hline\n"
          "\\textbf{Configuration} & \\textbf{Median} & \\textbf{Mean} & "
          "\\textbf{95\\% CI} & \\textbf{$n$}\\\\\n\\hline\\hline\n"
          + "\n".join(body) + "\n\\hline\n\\end{tabular}\n\\end{table}\n")


def perquery(rows, out):
    body = []
    for q in sorted({r["query_id"] for r in rows}):
        cells = []
        band = ""
        for slabel, _ in SCHEMAS:
            for fkey, _ in FRAMEWORKS:
                m = [r for r in rows if r["query_id"] == q
                     and r["schema_config"] == slabel and r["orm"] == fkey]
                if m:
                    band = m[0]["complexity_band"]
                    cells.append(num(m[0]["overhead_percentage"], 0))
                else:
                    cells.append("--")
        # column order in the manuscript is D/S indexed, then D/S non-indexed
        body.append(f"{q} & {BAND_ABBR.get(band, '?')} & {cells[0]} & "
                    f"{cells[1]} & {cells[2]} & {cells[3]}\\\\ \\hline")
    write(os.path.join(out, "tab_overhead_perquery.tex"),
          "\\begin{longtable}{l c r r r r}\n"
          "\\caption{ORM overhead by query and schema (per cent), TPC-H SF10 on "
          "PostgreSQL. D = Django, S = SQLAlchemy.}"
          "\\label{tab_r_overhead_perquery}\\\\\n"
          "\\hline\\hline\n"
          "& & \\multicolumn{2}{c}{\\textbf{Indexed}} & "
          "\\multicolumn{2}{c}{\\textbf{Non-indexed}}\\\\\n"
          "\\textbf{Query} & \\textbf{Band} & D & S & D & S\\\\\n"
          "\\hline\\hline\n\\endfirsthead\n"
          "\\hline\\hline\n"
          "\\textbf{Query} & \\textbf{Band} & D & S & D & S\\\\\n"
          "\\hline\\hline\n\\endhead\n"
          + "\n".join(body) + "\n\\hline\\hline\n\\end{longtable}\n")


def complexity(rows, out):
    body = []
    for band in BANDS:
        sub = [r for r in rows if r["complexity_band"] == band]
        if not sub:
            continue
        n = len({r["query_id"] for r in sub})
        cells = []
        for slabel, _ in SCHEMAS:
            for fkey, _ in FRAMEWORKS:
                v = [r["total_orm_execution_s"] for r in sub
                     if r["schema_config"] == slabel and r["orm"] == fkey
                     and r["total_orm_execution_s"] is not None]
                cells.append(f"{st.median(v):.2f}" if v else "--")
        body.append(f"{band} & {n} & {cells[0]} & {cells[1]} & {cells[2]} & "
                    f"{cells[3]}\\\\ \\hline")
    write(os.path.join(out, "tab_complexity.tex"),
          "\\begin{table}[H]\n"
          "\\caption{Median ORM execution time by complexity band, seconds, "
          "TPC-H SF10 on PostgreSQL.}\n"
          "\\label{tab_r_complexity}\n\\centering\n"
          "\\renewcommand{\\arraystretch}{1.2}\n"
          "\\begin{tabular}{l l r r r r}\n\\hline\\hline\n"
          "& & \\multicolumn{2}{c}{\\textbf{Indexed}} & "
          "\\multicolumn{2}{c}{\\textbf{Non-indexed}}\\\\\n"
          "\\textbf{Band} & \\textbf{$n$} & \\textbf{Django} & "
          "\\textbf{SQLAlchemy} & \\textbf{Django} & \\textbf{SQLAlchemy}\\\\\n"
          "\\hline\\hline\n" + "\n".join(body) +
          "\n\\hline\n\\end{tabular}\n\\end{table}\n")


def indexing(rows, out):
    """Total runtime under each schema, over queries complete under both."""
    body = []
    for fkey, flabel in FRAMEWORKS:
        for path, plabel, col in (("orm", "ORM", "total_orm_execution_s"),
                                  ("sql", "SQL", "direct_sql_execution_s")):
            by_q = {}
            for r in rows:
                if r["orm"] != fkey or r[col] is None:
                    continue
                if r[f"{path}_status"] != "ok":
                    continue
                by_q.setdefault(r["query_id"], {})[r["schema_config"]] = r[col]
            both = {q: v for q, v in by_q.items() if len(v) == 2}
            ni = sum(v["Non-Indexed"] for v in both.values())
            ix = sum(v["Indexed"] for v in both.values())
            impact = (ni - ix) / ni * 100 if ni else 0.0
            body.append(f"{flabel} & {plabel} & {ni:.1f} & {ix:.1f} & "
                        f"{num(impact)}\\% & {len(both)}\\\\ \\hline")
    write(os.path.join(out, "tab_indexing.tex"),
          "\\begin{table}[H]\n"
          "\\caption{Effect of indexing on total TPC-H runtime, seconds, summed "
          "over the queries that completed under both schemas. Positive impact "
          "is an improvement.}\n"
          "\\label{tab_r_indexing}\n\\centering\n"
          "\\renewcommand{\\arraystretch}{1.2}\n"
          "\\begin{tabular}{l l r r r r}\n\\hline\\hline\n"
          "\\textbf{Framework} & \\textbf{Path} & \\textbf{Non-indexed} & "
          "\\textbf{Indexed} & \\textbf{Impact} & \\textbf{$n$}\\\\\n"
          "\\hline\\hline\n" + "\n".join(body) +
          "\n\\hline\n\\end{tabular}\n\\end{table}\n")


def stats(rows, out):
    body = []
    for slabel, skey in SCHEMAS:
        d = {}
        for r in rows:
            if r["schema_config"] != slabel:
                continue
            d.setdefault(r["query_id"], {})[r["orm"]] = r["overhead_percentage"]
        pairs = [(v["DJANGO"], v["SQLALCHEMY"]) for v in d.values()
                 if len(v) == 2]
        dj = np.array([a for a, _ in pairs])
        sa = np.array([b for _, b in pairs])
        _, p = wilcoxon(dj, sa)
        diff = dj - sa
        cd = float(np.mean(diff) / np.std(diff, ddof=1))
        body.append(f"Django vs SQLAlchemy overhead & {skey} & {len(pairs)} & "
                    f"{p:.3f} & {num(cd, 2)}\\\\ \\hline")
    for fkey, flabel in FRAMEWORKS:
        col_o, col_s = "total_orm_execution_s", "direct_sql_execution_s"
        for slabel, skey in SCHEMAS:
            sub = [r for r in rows if r["orm"] == fkey
                   and r["schema_config"] == slabel
                   and r[col_o] is not None and r[col_s] is not None]
            o = np.array([r[col_o] for r in sub])
            s_ = np.array([r[col_s] for r in sub])
            if len(o) < 3:
                continue
            _, p = wilcoxon(o, s_)
            diff = o - s_
            cd = float(np.mean(diff) / np.std(diff, ddof=1))
            body.append(f"{flabel} ORM vs raw SQL & {skey} & {len(o)} & "
                        f"{p:.3f} & {num(cd, 2)}\\\\ \\hline")
    write(os.path.join(out, "tab_stats.tex"),
          "\\begin{table}[H]\n"
          "\\caption{Statistical comparison of the two frameworks. Paired "
          "Wilcoxon signed-rank on per-query values; Cohen's $d$ on the same "
          "pairs.}\n"
          "\\label{tab_r_stats}\n\\centering\n"
          "\\renewcommand{\\arraystretch}{1.2}\n"
          "\\begin{tabular}{l l r r r}\n\\hline\\hline\n"
          "\\textbf{Comparison} & \\textbf{Schema} & \\textbf{$n$} & "
          "\\textbf{$p$} & \\textbf{Cohen's $d$}\\\\\n\\hline\\hline\n"
          + "\n".join(body) + "\n\\hline\n\\end{tabular}\n\\end{table}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="all_results.csv")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    allr = load(args.results)
    rows = ok(allr)
    print(f"PostgreSQL TPC-H: {len(rows)} of {len(allr)} cells complete")
    completeness(allr, args.outdir)
    overhead_summary(rows, args.outdir)
    perquery(rows, args.outdir)
    complexity(rows, args.outdir)
    indexing(rows, args.outdir)
    stats(rows, args.outdir)


if __name__ == "__main__":
    main()
