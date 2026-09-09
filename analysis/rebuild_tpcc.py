"""Rebuild TPC-C-derived latency tables/figure from all four retained systems."""

from pathlib import Path
import csv, json, statistics as st, math
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

R = Path(__file__).resolve().parent
P = R.parent / "outputs"
P.mkdir(exist_ok=True)
for name in ("derived", "tables_paper", "figures"):
    (P / name).mkdir(exist_ok=True)
FW = ["django", "sqlalchemy"]
DB = ["postgresql", "mysql", "oracle", "commercial_a"]
SC = ["indexed", "non-indexed"]
logmedian = lambda cs: 100 * math.expm1(
    st.median(math.log1p(c["overhead"] / 100) for c in cs)
)
NAME = {
    "T1": "New-Order",
    "T2": "Payment",
    "T3": "Order-Status",
    "T4": "Delivery",
    "T5": "Stock-Level",
}
FN = {"django": "Django", "sqlalchemy": "SQLAlchemy"}
DN = dict(zip(DB, ["PostgreSQL", "MySQL", "Oracle", "Commercial System A"]))
paths = {}
cvs = []
for f in sorted((R.parent / "results/sf1/measurements").glob("*_tpcc_*.csv")):
    if "throughput" in f.name:
        continue
    for r in csv.DictReader(f.open()):
        assert r["status"] == "ok" and int(r["repetitions_measured"]) == 3
        k = tuple(
            r[x] for x in ["dbms", "schema_config", "query_id", "framework", "path"]
        )
        assert k not in paths
        paths[k] = float(r["median_s"])
        cvs.append(float(r["cv_pct"]))
cells = []
for db in DB:
    for sc in SC:
        for q in NAME:
            for fw in FW:
                base = paths[(db, sc, q, fw, "sql")]
                orm = paths[(db, sc, q, fw, "orm")]
                cells.append(
                    dict(
                        system=db,
                        schema=sc,
                        transaction=q,
                        framework=fw,
                        sql_ms=base * 1000,
                        orm_ms=orm * 1000,
                        additional_ms=(orm - base) * 1000,
                        overhead=100 * (orm / base - 1),
                    )
                )
assert len(cells) == 80
summary = {
    fw: {
        "n": 40,
        "median_overhead": logmedian([c for c in cells if c["framework"] == fw]),
    }
    for fw in FW
}
summary["pooled_median"] = logmedian(cells)
summary["median_cv"] = st.median(cvs)
summary["share_cv_above25"] = 100 * sum(c > 25 for c in cvs) / len(cvs)
rows = []
for q in NAME:
    row = [NAME[q]]
    for fw in FW:
        v = [c for c in cells if c["transaction"] == q and c["framework"] == fw]
        row += [
            "%.2f" % st.median(c["sql_ms"] for c in v),
            "%.2f" % st.median(c["orm_ms"] for c in v),
            "%+.1f\\%%" % logmedian(v),
        ]
    rows.append(row)
head = r"""\begin{table*}[!t]
\caption{TPC-C-derived transaction latency across four systems and two index configurations. Each transaction/framework summary contains eight cells. Milliseconds are medians of cell latencies; overhead is the back-transformed median of within-cell log ratios and need not equal the ratio of the displayed milliseconds.}\label{tab:tpcc-latency}
\centering\small\renewcommand{\arraystretch}{1.15}
\begin{tabular}{lrrrrrr}\toprule
 & \multicolumn{3}{c}{Django} & \multicolumn{3}{c}{SQLAlchemy}\\
Transaction & SQL (ms) & ORM (ms) & Overhead & SQL (ms) & ORM (ms) & Overhead\\\midrule
"""
(P / "tables_paper/four_system_tpcc.tex").write_text(
    head
    + "\n".join(" & ".join(r) + r" \\" for r in rows)
    + "\n"
    + r"\bottomrule\end{tabular}\end{table*}"
    + "\n"
)
with (P / "derived/tpcc_cells.csv").open("w") as h:
    w = csv.DictWriter(h, fieldnames=list(cells[0]))
    w.writeheader()
    w.writerows(cells)
(P / "derived/tpcc_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
plt.rcParams.update(
    {
        "font.size": 9,
        "pdf.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
fig, axs = plt.subplots(1, 4, figsize=(11, 3.1), sharey=True)
colors = ["#2463a5", "#d56720"]
for ax, db in zip(axs, DB):
    for fi, fw in enumerate(FW):
        for si, sc in enumerate(SC):
            v = [
                next(
                    c
                    for c in cells
                    if (c["system"], c["schema"], c["framework"], c["transaction"])
                    == (db, sc, fw, q)
                )
                for q in NAME
            ]
            ax.scatter(
                [i + (fi - 0.5) * 0.25 + (si - 0.5) * 0.1 for i in range(5)],
                [c["overhead"] for c in v],
                marker="o" if si == 0 else "^",
                facecolors=colors[fi] if si == 0 else "none",
                edgecolors=colors[fi],
                s=24,
                linewidths=0.9,
            )
    ax.set_title(DN[db])
    ax.set_xticks(range(5), NAME.keys())
    ax.axhline(0, c=".5", lw=0.7)
    ax.grid(axis="y", color=".9")
    ax.set_xlabel("Transaction")
    ax.set_xlim(-0.5, 4.5)
axs[0].set_ylabel("Observed overhead (%)")
fig.legend(
    handles=[
        Line2D([], [], color=colors[i], marker="o", ls="", label=FN[f])
        for i, f in enumerate(FW)
    ]
    + [
        Line2D([], [], color=".3", marker="o", ls="", label="Indexed"),
        Line2D([], [], color=".3", marker="^", mfc="none", ls="", label="Non-indexed"),
    ],
    loc="upper center",
    ncol=4,
    frameon=False,
)
fig.tight_layout(rect=[0, 0, 1, 0.9])
fig.savefig(P / "figures/four_system_tpcc.pdf")
plt.close(fig)
# Count concurrency failures without substituting them into latency estimates.
tput = []
for f in (R.parent / "results/sf1/measurements").glob("*tpcc_throughput*.csv"):
    tput.extend(csv.DictReader(f.open()))
x = [v for v in tput if int(v["concurrency"]) == 50]
summary["throughput_50clients"] = {
    "paths": len(x),
    "paths_with_aborts": sum(int(v["aborted"]) > 0 for v in x),
    "max_abort_pct": max(float(v["abort_pct"]) for v in x),
}
(P / "derived/tpcc_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
