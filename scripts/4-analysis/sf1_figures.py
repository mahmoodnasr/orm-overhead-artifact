#!/usr/bin/env python3
"""Figures for the SF1 campaign, from the same estimand the tables report.

    python3 scripts/4-analysis/sf1_figures.py --scale 1

Every figure is built from `overhead_by_query.csv` and `overhead_summary.csv`,
which sf1_analysis.py writes from the block measurements. Nothing here
recomputes an overhead, so a figure cannot disagree with the table beside it.

Four figures:

  fig1_overhead_by_system   the headline, with query-clustered bootstrap CIs
  fig2_by_query             every cell, on a symmetric log scale, because the
                            per-query values span four orders of magnitude and
                            a linear axis shows one bar and 87 slivers
  fig3_distribution         where the mass actually sits, per framework
  fig4_tpcc_throughput      the concurrency curves

Output is PDF (vector, for the paper) and PNG (for reading on screen).
"""
import argparse
import collections
import csv
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "utils"))
import anonymise                                              # noqa: E402

DBMS_ORDER = ["PostgreSQL", "MySQL", anonymise.public("SQL Server"), "Oracle"]
# The anonymised name is three words, and eight of them across one column width
# overprint into each other. Every axis carrying one label per system-framework
# pair uses the short form; the caption and the note carry the full one.
DBMS_SHORT = {anonymise.public("SQL Server"): "Comm. A"}
FRAMEWORKS = ["django", "sqlalchemy"]
FW_LABEL = {"django": "Django", "sqlalchemy": "SQLAlchemy"}
# Colour-blind safe, and distinguishable in greyscale by lightness.
FW_COLOR = {"django": "#4C72B0", "sqlalchemy": "#DD8452"}
SCHEMA_HATCH = {"indexed": "", "non-indexed": "///"}

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 130, "savefig.bbox": "tight",
})


def save(fig, outdir, name):
    # Stated on the figure itself. A reader who cannot tell a system has been
    # renamed cannot judge what the comparison is worth.
    fig.text(0.005, -0.02, anonymise.NOTE, fontsize=6, color="0.4", va="top")
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(outdir, f"{name}.{ext}"))
    plt.close(fig)
    print(f"  wrote {name}.pdf / .png")


def symlog_pct(ax):
    """A symmetric log axis labelled in percent.

    Overheads here run from -76% to +75800%. On a linear axis the four extreme
    cells are the figure and the other 84 are a line at zero; on a plain log
    axis the negative half cannot be drawn at all.
    """
    ax.set_yscale("symlog", linthresh=10)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}%"))
    ax.axhline(0, color="0.3", lw=0.8, zorder=1)


def fig1_overhead_by_system(summary, outdir):
    """Sixteen point estimates with their query-clustered intervals.

    This was a bar chart. A bar encodes a magnitude measured from zero, and its
    length is the thing the eye reads; what these sixteen numbers are is a point
    estimate with an interval around it, and half of them sit close enough to
    zero that the bar was a hairline while the whisker carried everything. Dots
    and whiskers put the weight on the estimate and its uncertainty, which is
    what the figure is for.

    Framework is colour and schema configuration is marker fill, so the four
    series inside a system stay separable without a hatch pattern that a
    symmetric-log axis renders at four different apparent densities.
    """
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x, labels, ticks = 0, [], []
    for dbms in DBMS_ORDER:
        start = x
        for schema in ("indexed", "non-indexed"):
            for fw in FRAMEWORKS:
                row = next((r for r in summary if r["dbms"] == dbms
                            and r["schema_config"] == schema and r["framework"] == fw), None)
                if row is None:
                    continue
                v = float(row["overhead_pct"])
                lo = float(row["ci_low_pct"]) if row["ci_low_pct"] else v
                hi = float(row["ci_high_pct"]) if row["ci_high_pct"] else v
                ax.errorbar(x, v, yerr=[[max(0, v - lo)], [max(0, hi - v)]],
                            fmt="o", markersize=5.5, color=FW_COLOR[fw],
                            markerfacecolor=(FW_COLOR[fw] if schema == "indexed"
                                             else "white"),
                            markeredgewidth=1.2, ecolor=FW_COLOR[fw],
                            elinewidth=1.1, capsize=2.5, zorder=3)
                x += 1
            x += 0.35
        ticks.append((start + x - 1.35) / 2); labels.append(dbms)
        x += 1.1
    ax.set_xticks(ticks); ax.set_xticklabels(labels)
    ax.set_xlim(-1.0, x - 0.6)
    symlog_pct(ax)
    ax.set_ylabel("ORM overhead vs hand-written SQL")
    ax.set_title("Median within-block paired overhead, scale factor 1", loc="left")
    handles = [Line2D([], [], marker="o", linestyle="none", markersize=5.5,
                      color=FW_COLOR[f], markerfacecolor=FW_COLOR[f])
               for f in FRAMEWORKS]
    handles += [Line2D([], [], marker="o", linestyle="none", markersize=5.5,
                       color="0.35", markerfacecolor=fc, markeredgewidth=1.2)
                for fc in ("0.35", "white")]
    ax.legend(handles, [FW_LABEL[f] for f in FRAMEWORKS] + ["indexed", "non-indexed"],
              ncol=4, frameon=False, loc="upper left")
    ax.grid(axis="y", color="0.9", zorder=0)
    save(fig, outdir, "fig1_overhead_by_system")


def fig2_by_query(perq, outdir):
    fig, axes = plt.subplots(2, 2, figsize=(11, 6), sharey=True)
    queries = sorted({r["query_id"] for r in perq})
    for ax, dbms in zip(axes.flat, DBMS_ORDER):
        for i, fw in enumerate(FRAMEWORKS):
            xs, ys = [], []
            for j, q in enumerate(queries):
                rows = [r for r in perq if r["dbms"] == dbms and r["query_id"] == q
                        and r["framework"] == fw]
                for r in rows:
                    xs.append(j + (i - 0.5) * 0.3
                              + (0.08 if r["schema_config"] == "non-indexed" else -0.08))
                    ys.append(float(r["overhead_pct"]))
            ax.scatter(xs, ys, s=13, color=FW_COLOR[fw], label=FW_LABEL[fw],
                       alpha=0.85, edgecolors="none", zorder=3)
        symlog_pct(ax)
        ax.set_title(dbms, loc="left")
        ax.set_xticks(range(len(queries)))
        ax.set_xticklabels([q.replace("Q", "") for q in queries], fontsize=6.5)
        ax.grid(axis="y", color="0.93", zorder=0)
    axes[0, 0].legend(frameon=False, loc="upper left", ncol=2)
    for ax in axes[1]:
        ax.set_xlabel("TPC-H query")
    for ax in axes[:, 0]:
        ax.set_ylabel("overhead")
    fig.suptitle("Per-query ORM overhead, both configurations, scale factor 1",
                 x=0.02, ha="left")
    save(fig, outdir, "fig2_by_query")


def fig3_distribution(perq, outdir):
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    data, labels, colors = [], [], []
    for dbms in DBMS_ORDER:
        for fw in FRAMEWORKS:
            vals = [float(r["overhead_pct"]) for r in perq
                    if r["dbms"] == dbms and r["framework"] == fw]
            if vals:
                data.append(vals)
                labels.append(f"{DBMS_SHORT.get(dbms, dbms)}\n{FW_LABEL[fw]}")
                colors.append(FW_COLOR[fw])
    bp = ax.boxplot(data, patch_artist=True, widths=0.6, showfliers=True,
                    flierprops=dict(marker=".", markersize=3, alpha=0.6),
                    medianprops=dict(color="0.15", lw=1.2))
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c); patch.set_alpha(0.75); patch.set_edgecolor("white")
    ax.set_xticklabels(labels, fontsize=7.5)
    symlog_pct(ax)
    ax.set_ylabel("overhead per query")
    ax.set_title("Distribution of per-query overhead, both configurations pooled",
                 loc="left")
    ax.grid(axis="y", color="0.93", zorder=0)
    save(fig, outdir, "fig3_distribution")


def fig4_tpcc_throughput(meas, outdir):
    curves = collections.defaultdict(lambda: collections.defaultdict(list))
    for fn in sorted(os.listdir(meas)):
        if "tpcc_throughput" not in fn or not fn.endswith(".csv"):
            continue
        for r in csv.DictReader(open(os.path.join(meas, fn))):
            try:
                c = int(r["concurrency"]); qpm = float(r["qpm"])
            except (KeyError, ValueError):
                continue
            key = (r["dbms"], r["schema_config"], r["framework"], r["path"])
            curves[key][c].append(qpm)
    if not curves:
        print("  no throughput data found")
        return
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.1), sharey=True)
    for ax, dbms in zip(axes, ["postgresql", "mysql", "sqlserver", "oracle"]):
        for fw in FRAMEWORKS:
            for path, ls in (("orm", "-"), ("sql", "--")):
                pts = collections.defaultdict(list)
                for (d, s, f, p), byc in curves.items():
                    if d != dbms or f != fw or p != path or s != "indexed":
                        continue
                    for c, v in byc.items():
                        pts[c].append(sum(v))
                if not pts:
                    continue
                xs = sorted(pts)
                ys = [sum(pts[c]) for c in xs]
                ax.plot(xs, ys, ls, color=FW_COLOR[fw], marker="o", ms=3, lw=1.3,
                        label=f"{FW_LABEL[fw]} {path.upper()}")
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 4, 8, 16, 32, 50])
        ax.set_xticklabels([1, 4, 8, 16, 32, 50])
        ax.set_title(anonymise.public({"postgresql": "PostgreSQL", "mysql": "MySQL",
                                       "sqlserver": "SQL Server",
                                       "oracle": "Oracle"}[dbms]), loc="left")
        ax.set_xlabel("clients")
        ax.grid(color="0.93")
    axes[0].set_ylabel("committed transactions / minute")
    axes[0].legend(frameon=False, fontsize=7)
    fig.suptitle("TPC-C throughput against concurrency, indexed configuration",
                 x=0.02, ha="left")
    save(fig, outdir, "fig4_tpcc_throughput")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="1")
    args = ap.parse_args()
    base = os.path.join(REPO, "results", "sf%s" % args.scale)
    andir = os.path.join(base, "analysis")
    figdir = os.path.join(base, "figures")
    os.makedirs(figdir, exist_ok=True)

    need = os.path.join(andir, "overhead_by_query.csv")
    if not os.path.exists(need):
        print("run sf1_analysis.py first - %s is missing" % need, file=sys.stderr)
        return 2
    perq = list(csv.DictReader(open(need)))
    summary = list(csv.DictReader(open(os.path.join(andir, "overhead_summary.csv"))))

    print("figures -> %s" % figdir)
    fig1_overhead_by_system(summary, figdir)
    fig2_by_query(perq, figdir)
    fig3_distribution(perq, figdir)
    fig4_tpcc_throughput(os.path.join(base, "measurements"), figdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
