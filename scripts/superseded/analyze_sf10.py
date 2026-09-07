#!/usr/bin/env python3
"""Analyse the SF10 campaign and emit every table and figure the write-up needs.

Reads results/corrected/measurements/postgresql_{indexed,non_indexed}.csv, which
carry one row per (query, framework, path) with a median over the measured
repetitions.

Produces, in results/analysis/:
    tab_overhead_summary.tex     median ORM overhead by framework and schema
    tab_overhead_perquery.tex    per-query overhead, both frameworks, both schemas
    tab_complexity.tex           median ORM time by complexity band
    tab_indexing.tex             effect of indexing per framework and path
    tab_stats.tex                paired tests, effect sizes, confidence intervals
    fig_overhead.pdf             overhead distribution by framework and schema
    fig_complexity.pdf           ORM time by complexity band
    fig_indexing.pdf             indexed vs non-indexed per query
    fig_orm_vs_sql.pdf           ORM time against raw SQL time, all configurations
    summary.json                 every headline number, for the prose
"""
import csv, json, math, os, statistics
from collections import defaultdict

# Derived from this file's own location rather than written down, so the script
# runs from a clone at any path. It previously pointed at /home/claude/bench,
# which was the sandbox the campaign happened to run in and exists on no
# reviewer's machine. Same derivation as make_all_results.py.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RES = os.environ.get("RESULTS_DIR", os.path.join(ROOT, "results", "corrected", "measurements"))
OUT = os.environ.get("ANALYSIS_DIR", os.path.join(ROOT, "results", "analysis"))
os.makedirs(OUT, exist_ok=True)

BANDS = {
    **{f"Q{q:02d}": "Simple" for q in (6, 14, 19)},
    **{f"Q{q:02d}": "Medium" for q in (1, 3, 4, 11, 12, 16)},
    **{f"Q{q:02d}": "Complex" for q in (2, 5, 7, 10, 13, 15, 17, 18, 20)},
    **{f"Q{q:02d}": "Very Complex" for q in (8, 9, 21, 22)},
}
BAND_ORDER = ["Simple", "Medium", "Complex", "Very Complex"]
FRAMEWORKS = ["django", "sqlalchemy"]
SCHEMAS = ["indexed", "non-indexed"]


def load():
    """rows[(schema, query, framework, path)] = record"""
    rows = {}
    for fn, schema in (("postgresql_indexed.csv", "indexed"),
                       ("postgresql_non_indexed.csv", "non-indexed")):
        p = os.path.join(RES, fn)
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p)):
            key = (schema, r["query_id"], r["framework"], r["path"])
            rows[key] = r
    return rows


def med(r):
    if r is None or r.get("status") != "ok" or r.get("median_s") in ("", None):
        return None
    return float(r["median_s"])


def overhead(rows, schema, q, fw):
    o = med(rows.get((schema, q, fw, "orm")))
    s = med(rows.get((schema, q, fw, "sql")))
    if o is None or s is None or s == 0:
        return None
    return (o - s) / s * 100


def status(rows, schema, q, fw, path):
    r = rows.get((schema, q, fw, path))
    return r["status"] if r else "missing"


# ----------------------------------------------------------------- statistics
def bootstrap_ci(xs, n=10000, seed=20260727):
    if len(xs) < 2:
        return (None, None)
    import random
    rng = random.Random(seed)
    meds = []
    for _ in range(n):
        s = [xs[rng.randrange(len(xs))] for _ in xs]
        meds.append(statistics.median(s))
    meds.sort()
    return (meds[int(0.025 * n)], meds[int(0.975 * n)])


def wilcoxon(a, b):
    """Paired signed-rank test. Returns (W, p) via normal approximation."""
    d = [x - y for x, y in zip(a, b) if x is not None and y is not None and x != y]
    n = len(d)
    if n < 6:
        return (None, None)
    ranks = sorted(range(n), key=lambda i: abs(d[i]))
    rank_of = [0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[ranks[j + 1]]) == abs(d[ranks[i]]):
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rank_of[ranks[k]] = avg
        i = j + 1
    wp = sum(rank_of[i] for i in range(n) if d[i] > 0)
    wm = sum(rank_of[i] for i in range(n) if d[i] < 0)
    W = min(wp, wm)
    mu = n * (n + 1) / 4
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (W - mu) / sd if sd else 0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return (W, p)


def cohens_d(a, b):
    a = [x for x in a if x is not None]
    b = [x for x in b if x is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    na, nb = len(a), len(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return (statistics.mean(a) - statistics.mean(b)) / sp if sp else None


# --------------------------------------------------------------------- tables
def fmt(x, nd=1, dash="--"):
    return dash if x is None else f"{x:,.{nd}f}".replace(",", "{,}")


def t_overhead_summary(rows, S):
    L = [r"\begin{table}[H]",
         r"\caption{Median ORM overhead over the hand-written SQL baseline, "
         r"TPC-H SF10 on PostgreSQL. A negative value means the ORM path was "
         r"marginally faster.}",
         r"\label{tab_r_overhead_summary}", r"\centering",
         r"\renewcommand{\arraystretch}{1.2}",
         r"\begin{tabular}{l r r r r}", r"\hline\hline",
         r"\textbf{Configuration} & \textbf{Median} & \textbf{Mean} & "
         r"\textbf{95\% CI} & \textbf{$n$}\\", r"\hline\hline"]
    for schema in SCHEMAS:
        for fw in FRAMEWORKS:
            xs = [overhead(rows, schema, q, fw) for q in sorted(BANDS)]
            xs = [x for x in xs if x is not None]
            if not xs:
                continue
            lo, hi = bootstrap_ci(xs)
            L.append(f"{fw.capitalize()}, {schema} & {fmt(statistics.median(xs))}\\% & "
                     f"{fmt(statistics.mean(xs))}\\% & "
                     f"[{fmt(lo)}, {fmt(hi)}] & {len(xs)}\\\\ \\hline")
    L += [r"\hline", r"\end{tabular}", r"\end{table}"]
    open(f"{OUT}/tab_overhead_summary.tex", "w").write("\n".join(L) + "\n")


def t_overhead_perquery(rows, S):
    L = [r"\begin{longtable}{l c r r r r}",
         r"\caption{ORM overhead by query and schema (per cent), TPC-H SF10 on "
         r"PostgreSQL. D = Django, S = SQLAlchemy.}"
         r"\label{tab_r_overhead_perquery}\\", r"\hline\hline",
         r"& & \multicolumn{2}{c}{\textbf{Indexed}} & "
         r"\multicolumn{2}{c}{\textbf{Non-indexed}}\\",
         r"\textbf{Query} & \textbf{Band} & D & S & D & S\\",
         r"\hline\hline", r"\endfirsthead", r"\hline\hline",
         r"\textbf{Query} & \textbf{Band} & D & S & D & S\\",
         r"\hline\hline", r"\endhead"]
    for q in sorted(BANDS):
        band = "VC" if BANDS[q] == "Very Complex" else BANDS[q][0]
        cells = []
        for schema in SCHEMAS:
            for fw in FRAMEWORKS:
                v = overhead(rows, schema, q, fw)
                if v is None:
                    st = status(rows, schema, q, fw, "orm")
                    cells.append("t/o" if st == "timeout" else "--")
                else:
                    cells.append(f"{v:,.0f}".replace(",", "{,}"))
        L.append(f"{q} & {band} & " + " & ".join(cells) + r"\\ \hline")
    L += [r"\hline", r"\end{longtable}"]
    open(f"{OUT}/tab_overhead_perquery.tex", "w").write("\n".join(L) + "\n")


def t_complexity(rows, S):
    L = [r"\begin{table}[H]",
         r"\caption{Median ORM execution time by complexity band, seconds, "
         r"TPC-H SF10 on PostgreSQL.}",
         r"\label{tab_r_complexity}", r"\centering",
         r"\renewcommand{\arraystretch}{1.2}",
         r"\begin{tabular}{l l r r r r}", r"\hline\hline",
         r"& & \multicolumn{2}{c}{\textbf{Indexed}} & "
         r"\multicolumn{2}{c}{\textbf{Non-indexed}}\\",
         r"\textbf{Band} & \textbf{$n$} & \textbf{Django} & \textbf{SQLAlchemy} "
         r"& \textbf{Django} & \textbf{SQLAlchemy}\\", r"\hline\hline"]
    for band in BAND_ORDER:
        qs = [q for q in sorted(BANDS) if BANDS[q] == band]
        cells = []
        for schema in SCHEMAS:
            for fw in FRAMEWORKS:
                xs = [med(rows.get((schema, q, fw, "orm"))) for q in qs]
                xs = [x for x in xs if x is not None]
                cells.append(fmt(statistics.median(xs), 2) if xs else "--")
        L.append(f"{band} & {len(qs)} & " + " & ".join(cells) + r"\\ \hline")
    L += [r"\hline", r"\end{tabular}", r"\end{table}"]
    open(f"{OUT}/tab_complexity.tex", "w").write("\n".join(L) + "\n")


def t_indexing(rows, S):
    L = [r"\begin{table}[H]",
         r"\caption{Effect of indexing on total TPC-H runtime, seconds, summed "
         r"over the queries that completed under both schemas. Positive impact "
         r"is an improvement.}",
         r"\label{tab_r_indexing}", r"\centering",
         r"\renewcommand{\arraystretch}{1.2}",
         r"\begin{tabular}{l l r r r r}", r"\hline\hline",
         r"\textbf{Framework} & \textbf{Path} & \textbf{Non-indexed} & "
         r"\textbf{Indexed} & \textbf{Impact} & \textbf{$n$}\\", r"\hline\hline"]
    for fw in FRAMEWORKS:
        for path in ("orm", "sql"):
            pairs = []
            for q in sorted(BANDS):
                a = med(rows.get(("non-indexed", q, fw, path)))
                b = med(rows.get(("indexed", q, fw, path)))
                if a is not None and b is not None:
                    pairs.append((a, b))
            if not pairs:
                continue
            ni = sum(a for a, _ in pairs)
            ix = sum(b for _, b in pairs)
            imp = (ni - ix) / ni * 100 if ni else None
            sign = "$+$" if (imp or 0) >= 0 else "$-$"
            L.append(f"{fw.capitalize()} & {path.upper()} & {fmt(ni, 1)} & "
                     f"{fmt(ix, 1)} & {sign}{fmt(abs(imp) if imp is not None else None)}\\% & "
                     f"{len(pairs)}\\\\ \\hline")
    L += [r"\hline", r"\end{tabular}", r"\end{table}"]
    open(f"{OUT}/tab_indexing.tex", "w").write("\n".join(L) + "\n")


def t_stats(rows, S):
    L = [r"\begin{table}[H]",
         r"\caption{Statistical comparison of the two frameworks. Paired "
         r"Wilcoxon signed-rank on per-query values; Cohen's $d$ on the same "
         r"pairs.}",
         r"\label{tab_r_stats}", r"\centering",
         r"\renewcommand{\arraystretch}{1.2}",
         r"\begin{tabular}{l l r r r}", r"\hline\hline",
         r"\textbf{Comparison} & \textbf{Schema} & \textbf{$n$} & "
         r"\textbf{$p$} & \textbf{Cohen's $d$}\\", r"\hline\hline"]
    for schema in SCHEMAS:
        dj = [overhead(rows, schema, q, "django") for q in sorted(BANDS)]
        sa = [overhead(rows, schema, q, "sqlalchemy") for q in sorted(BANDS)]
        pairs = [(a, b) for a, b in zip(dj, sa) if a is not None and b is not None]
        if len(pairs) < 6:
            continue
        a = [x for x, _ in pairs]
        b = [y for _, y in pairs]
        _, p = wilcoxon(a, b)
        d = cohens_d(a, b)
        L.append(f"Django vs SQLAlchemy overhead & {schema} & {len(pairs)} & "
                 f"{'--' if p is None else f'{p:.3f}'} & {fmt(d, 2)}\\\\ \\hline")
    for fw in FRAMEWORKS:
        for schema in SCHEMAS:
            orm = [med(rows.get((schema, q, fw, "orm"))) for q in sorted(BANDS)]
            sql = [med(rows.get((schema, q, fw, "sql"))) for q in sorted(BANDS)]
            pairs = [(a, b) for a, b in zip(orm, sql) if a is not None and b is not None]
            if len(pairs) < 6:
                continue
            _, p = wilcoxon([x for x, _ in pairs], [y for _, y in pairs])
            d = cohens_d([x for x, _ in pairs], [y for _, y in pairs])
            L.append(f"{fw.capitalize()} ORM vs raw SQL & {schema} & {len(pairs)} & "
                     f"{'--' if p is None else f'{p:.3f}'} & {fmt(d, 2)}\\\\ \\hline")
    L += [r"\hline", r"\end{tabular}", r"\end{table}"]
    open(f"{OUT}/tab_stats.tex", "w").write("\n".join(L) + "\n")




def t_completeness(rows, S):
    """How many configurations completed, timed out, or are missing."""
    L = [r"\begin{table}[H]",
         r"\caption{Campaign completeness. Each cell counts the 22 TPC-H "
         r"queries by outcome.}",
         r"\label{tab_r_completeness}", r"\centering",
         r"\renewcommand{\arraystretch}{1.2}",
         r"\begin{tabular}{l l l r r r}", r"\hline\hline",
         r"\textbf{Schema} & \textbf{Framework} & \textbf{Path} & "
         r"\textbf{Completed} & \textbf{Timed out} & \textbf{Not run}\\",
         r"\hline\hline"]
    for schema in SCHEMAS:
        for fw in FRAMEWORKS:
            for path in ("orm", "sql"):
                ok = to = ms = 0
                for q in sorted(BANDS):
                    r = rows.get((schema, q, fw, path))
                    if r is None:
                        ms += 1
                    elif r["status"] == "ok":
                        ok += 1
                    else:
                        to += 1
                L.append(f"{schema} & {fw.capitalize()} & {path.upper()} & "
                         f"{ok} & {to} & {ms}\\\\ \\hline")
    L += [r"\hline", r"\end{tabular}", r"\end{table}"]
    open(f"{OUT}/tab_completeness.tex", "w").write("\n".join(L) + "\n")

# -------------------------------------------------------------------- figures
def figures(rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print("matplotlib unavailable, skipping figures:", e)
        return

    GREY = "#4a4a4a"
    C = {"django": "#8c6d3f", "sqlalchemy": "#5b4b8a"}

    def style(ax):
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(colors=GREY, labelsize=9)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GREY)

    # 1. overhead distribution
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, schema in zip(axes, SCHEMAS):
        data, labels, colors = [], [], []
        for fw in FRAMEWORKS:
            xs = [overhead(rows, schema, q, fw) for q in sorted(BANDS)]
            xs = [x for x in xs if x is not None]
            if xs:
                data.append(xs)
                labels.append(fw.capitalize())
                colors.append(C[fw])
        if data:
            bp = ax.boxplot(data, labels=labels, patch_artist=True, widths=0.5)
            for patch, c in zip(bp["boxes"], colors):
                patch.set_facecolor(c)
                patch.set_alpha(0.55)
                patch.set_edgecolor(c)
            for m in bp["medians"]:
                m.set_color("black")
        ax.axhline(0, color=GREY, lw=0.8, ls=":")
        ax.set_title(schema, fontsize=10, color=GREY)
        style(ax)
    axes[0].set_ylabel("ORM overhead (%)", fontsize=9, color=GREY)
    fig.suptitle("ORM overhead over hand-written SQL, TPC-H SF10 on PostgreSQL",
                 fontsize=11, color=GREY)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_overhead.pdf", bbox_inches="tight")
    plt.close(fig)

    # 2. complexity bands
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, schema in zip(axes, SCHEMAS):
        x = range(len(BAND_ORDER))
        for i, fw in enumerate(FRAMEWORKS):
            ys = []
            for band in BAND_ORDER:
                qs = [q for q in sorted(BANDS) if BANDS[q] == band]
                v = [med(rows.get((schema, q, fw, "orm"))) for q in qs]
                v = [y for y in v if y is not None]
                ys.append(statistics.median(v) if v else float("nan"))
            ax.bar([xi + (i - 0.5) * 0.36 for xi in x], ys, width=0.36,
                   color=C[fw], alpha=0.8, label=fw.capitalize())
        ax.set_xticks(list(x))
        ax.set_xticklabels(["S", "M", "C", "VC"])
        ax.set_yscale("log")
        ax.set_title(schema, fontsize=10, color=GREY)
        style(ax)
    axes[0].set_ylabel("median ORM time (s, log)", fontsize=9, color=GREY)
    axes[1].legend(frameon=False, fontsize=9)
    fig.suptitle("ORM execution time by query complexity", fontsize=11, color=GREY)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_complexity.pdf", bbox_inches="tight")
    plt.close(fig)

    # 3. ORM against raw SQL, scatter
    fig, ax = plt.subplots(figsize=(5.2, 5))
    lim = 0.01
    for fw in FRAMEWORKS:
        xs, ys = [], []
        for schema in SCHEMAS:
            for q in sorted(BANDS):
                a = med(rows.get((schema, q, fw, "sql")))
                b = med(rows.get((schema, q, fw, "orm")))
                if a and b:
                    xs.append(a)
                    ys.append(b)
                    lim = max(lim, a, b)
        ax.scatter(xs, ys, s=26, alpha=0.7, color=C[fw], label=fw.capitalize(),
                   edgecolors="none")
    ax.plot([0.01, lim * 1.2], [0.01, lim * 1.2], color=GREY, lw=0.8, ls="--")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("hand-written SQL (s)", fontsize=9, color=GREY)
    ax.set_ylabel("ORM (s)", fontsize=9, color=GREY)
    ax.set_title("ORM against raw SQL, all configurations", fontsize=11, color=GREY)
    ax.legend(frameon=False, fontsize=9)
    style(ax)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_orm_vs_sql.pdf", bbox_inches="tight")
    plt.close(fig)

    # 4. indexing effect per query
    fig, ax = plt.subplots(figsize=(9, 3.4))
    qs = sorted(BANDS)
    width = 0.38
    for i, fw in enumerate(FRAMEWORKS):
        ys = []
        for q in qs:
            a = med(rows.get(("non-indexed", q, fw, "orm")))
            b = med(rows.get(("indexed", q, fw, "orm")))
            ys.append(((a - b) / a * 100) if (a and b) else float("nan"))
        ax.bar([j + (i - 0.5) * width for j in range(len(qs))], ys, width=width,
               color=C[fw], alpha=0.8, label=fw.capitalize())
    ax.axhline(0, color=GREY, lw=0.8)
    ax.set_xticks(range(len(qs)))
    ax.set_xticklabels([q[1:] for q in qs], fontsize=7)
    ax.set_ylabel("improvement from indexing (%)", fontsize=9, color=GREY)
    ax.set_xlabel("TPC-H query", fontsize=9, color=GREY)
    ax.legend(frameon=False, fontsize=9)
    ax.set_title("Effect of indexing on ORM execution time", fontsize=11, color=GREY)
    style(ax)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_indexing.pdf", bbox_inches="tight")
    plt.close(fig)
    print("figures written")


# --------------------------------------------------------------------- summary
def summary(rows):
    S = {"scale_factor": 10, "dbms": "PostgreSQL 14.9", "queries": 22}
    for schema in SCHEMAS:
        for fw in FRAMEWORKS:
            xs = [overhead(rows, schema, q, fw) for q in sorted(BANDS)]
            xs = [x for x in xs if x is not None]
            if xs:
                lo, hi = bootstrap_ci(xs)
                S[f"{fw}_{schema}_overhead"] = {
                    "median": round(statistics.median(xs), 2),
                    "mean": round(statistics.mean(xs), 2),
                    "min": round(min(xs), 2), "max": round(max(xs), 2),
                    "ci95": [round(lo, 2) if lo else None, round(hi, 2) if hi else None],
                    "n": len(xs),
                }
            tot = [med(rows.get((schema, q, fw, "orm"))) for q in sorted(BANDS)]
            tot = [x for x in tot if x is not None]
            S[f"{fw}_{schema}_total_orm_s"] = round(sum(tot), 1) if tot else None
    for schema in SCHEMAS:
        dj = [overhead(rows, schema, q, "django") for q in sorted(BANDS)]
        sa = [overhead(rows, schema, q, "sqlalchemy") for q in sorted(BANDS)]
        pairs = [(a, b) for a, b in zip(dj, sa) if a is not None and b is not None]
        if len(pairs) >= 6:
            _, p = wilcoxon([x for x, _ in pairs], [y for _, y in pairs])
            S[f"framework_test_{schema}"] = {
                "n": len(pairs),
                "p": round(p, 4) if p is not None else None,
                "cohens_d": round(cohens_d([x for x, _ in pairs],
                                           [y for _, y in pairs]) or 0, 3),
            }
    S["timeouts"] = [
        {"schema": s, "query": q, "framework": f, "path": p}
        for (s, q, f, p), r in sorted(rows.items())
        if r.get("status") == "timeout"
    ]
    S["missing"] = sorted({
        f"{s}/{q}/{f}/{p}" for s in SCHEMAS for q in sorted(BANDS)
        for f in FRAMEWORKS for p in ("orm", "sql")
        if (s, q, f, p) not in rows
    })
    json.dump(S, open(f"{OUT}/summary.json", "w"), indent=2)
    return S


def main():
    rows = load()
    print(f"loaded {len(rows)} records")
    S = summary(rows)
    t_completeness(rows, S)
    t_overhead_summary(rows, S)
    t_overhead_perquery(rows, S)
    t_complexity(rows, S)
    t_indexing(rows, S)
    t_stats(rows, S)
    figures(rows)
    print(json.dumps({k: v for k, v in S.items()
                      if k not in ("timeouts", "missing")}, indent=2))
    print(f"timeouts: {len(S['timeouts'])}   missing: {len(S['missing'])}")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
