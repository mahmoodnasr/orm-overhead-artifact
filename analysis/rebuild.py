"""Rebuild the four-system paper directly from retained measurements.

Run with Python, NumPy, SciPy and Matplotlib. No database connection is used.
The cell estimand and query-cluster bootstrap preserve the original analysis.
"""

from pathlib import Path
from collections import defaultdict, Counter
import csv, json, math, statistics as st, random, zlib, hashlib
import numpy as np
from scipy.stats import wilcoxon
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent
PAPER = ROOT.parent / "outputs"
PAPER.mkdir(exist_ok=True)
DATA = ROOT.parent / "results/sf1/measurements"
COVERAGE = ROOT.parent / "results/sf1/all_results.csv"
(PAPER / "tables_paper").mkdir(exist_ok=True)
(PAPER / "figures").mkdir(exist_ok=True)
OUT = PAPER / "derived"
OUT.mkdir(exist_ok=True)
SYSTEMS = ["postgresql", "mysql", "oracle", "commercial_a"]
LABEL = {
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "oracle": "Oracle",
    "commercial_a": "Commercial System A",
}
FW = ["django", "sqlalchemy"]
FN = {"django": "Django", "sqlalchemy": "SQLAlchemy"}
SC = ["indexed", "non-indexed"]
pct = lambda x: 100 * math.expm1(x)


def interval(cells):
    key = "|".join("%s:%.12g" % (q, t) for q, t in sorted(cells))
    rng = random.Random(20260907 ^ zlib.crc32(key.encode()))
    by = defaultdict(list)
    for q, t in cells:
        by[q].append(t)
    qs = list(by)
    samples = []
    for _ in range(2000):
        samples.append(
            st.median([t for _ in qs for t in by[qs[rng.randrange(len(qs))]]])
        )
    samples.sort()
    return [pct(samples[50]), pct(samples[1950])]


def summarize(items):
    return {
        "n": len(items),
        "median": pct(st.median(v["theta"] for v in items)),
        "ci": interval([(v["query"], v["theta"]) for v in items]),
    }


blocks = defaultdict(dict)
paths = defaultdict(list)
counts = defaultdict(list)
for f in sorted(
    DATA.glob("*.csv"), key=lambda p: (p.name.startswith("commercial_a"), p.name)
):
    if "tpcc" in f.name or f.name == "coverage.csv":
        continue
    for r in csv.DictReader(f.open()):
        if r["is_warmup"] != "0" or r["status"] != "ok":
            continue
        assert r["dbms"] in SYSTEMS
        k = (r["dbms"], r["schema_config"], r["query_id"], r["framework"])
        bk = (*k, int(r["block"]))
        assert r["path"] not in blocks[bk], "duplicate measured path"
        blocks[bk][r["path"]] = float(r["elapsed_s"])
        paths[(*k, r["path"])].append(float(r["elapsed_s"]))
        if r["rows_returned"]:
            counts[k].append(int(r["rows_returned"]))
paired = defaultdict(list)
for (*key, b), times in blocks.items():
    if set(times) == {"orm", "sql"}:
        paired[tuple(key)].append(math.log(times["orm"] / times["sql"]))
cells = []
for k, ratios in sorted(
    paired.items(), key=lambda item: (item[0][0] == "commercial_a", item[0])
):
    assert len(ratios) == 8
    db, sc, q, fw = k
    cells.append(
        dict(
            system=db,
            schema=sc,
            query=q,
            framework=fw,
            theta=st.median(ratios),
            overhead=pct(st.median(ratios)),
            sql_s=st.median(paths[(*k, "sql")]),
            orm_s=st.median(paths[(*k, "orm")]),
            rows=max(counts[k]),
            blocks=8,
        )
    )
summary = {f: summarize([c for c in cells if c["framework"] == f]) for f in FW}
summary["pooled"] = summarize(cells)
summary["counts"] = {
    "above100": sum(c["overhead"] > 100 for c in cells),
    "negative": sum(c["overhead"] < 0 for c in cells),
    "within1": sum(abs(c["overhead"]) <= 1 for c in cells),
    "below_minus50": sum(c["overhead"] < -50 for c in cells),
}
for f in FW:
    qm = [
        st.median(c["theta"] for c in cells if c["framework"] == f and c["query"] == q)
        for q in sorted({c["query"] for c in cells})
    ]
    summary[f]["wilcoxon_p"] = float(wilcoxon(qm, method="exact").pvalue)


def table(name, caption, label, columns, headers, rows, wide=True):
    kind = "table*" if wide else "table"
    body = "\n".join(" & ".join(map(str, r)) + r" \\" for r in rows)
    text = (
        rf"\begin{{{kind}}}[!t]"
        + "\n"
        + rf"\caption{{{caption}}}\label{{{label}}}"
        + "\n"
        + r"\centering\small\renewcommand{\arraystretch}{1.15}"
        + "\n"
        + rf"\begin{{tabular}}{{{columns}}}\toprule"
        + "\n"
        + " & ".join(headers)
        + r" \\\midrule"
        + "\n"
        + body
        + "\n"
        + rf"\bottomrule\end{{tabular}}\end{{{kind}}}"
        + "\n"
    )
    (PAPER / "tables_paper" / name).write_text(text)


ci = lambda a: "[%.2f, %.2f]" % tuple(a)
table(
    "four_system_headline.tex",
    "Analytical paired overhead. Intervals resample the 22 query clusters; all retained cells have eight paired blocks.",
    "tab:headline",
    "lrrr",
    ["Framework", "Cells", "Median (\\%)", "95\\% interval"],
    [
        [FN[f], summary[f]["n"], "%.2f" % summary[f]["median"], ci(summary[f]["ci"])]
        for f in FW
    ],
    False,
)
coverage = list(csv.DictReader(COVERAGE.open()))
cr = []
for db in SYSTEMS:
    rows = [
        r
        for r in coverage
        if r["dbms"]
        .lower()
        .replace(" ", "")
        .replace("commercialsystema", "commercial_a")
        == db
        and r["benchmark"] == "tpch"
    ]
    statuses = Counter(r["orm_status"] for r in rows)
    assert len(rows) == 88, (db, len(rows))
    cr.append(
        [
            "System A" if db == "commercial_a" else LABEL[db],
            len(rows),
            statuses["ok"],
            statuses["timeout"],
            statuses["not_expressible"],
        ]
    )
table(
    "four_system_coverage.tex",
    "Coverage of the 352-cell analytical design. System A denotes Commercial System A. The TPC-C-derived transaction dataset contains 80 measured cells.",
    "tab:coverage",
    "lrrrr",
    ["System", "Planned", "Measured", "Censored", "Inexpressible"],
    cr,
    False,
)
system = []
for db in SYSTEMS:
    for sc in SC:
        for f in FW:
            v = summarize(
                [
                    c
                    for c in cells
                    if (c["system"], c["schema"], c["framework"]) == (db, sc, f)
                ]
            )
            system.append(dict(system=db, schema=sc, framework=f, **v))
cases = [
    ("Q15", "postgresql", "indexed", "django"),
    ("Q15", "oracle", "indexed", "django"),
    ("Q15", "oracle", "indexed", "sqlalchemy"),
    ("Q17", "postgresql", "indexed", "django"),
    ("Q17", "oracle", "indexed", "django"),
    ("Q17", "oracle", "non-indexed", "django"),
    ("Q20", "oracle", "indexed", "django"),
    ("Q20", "oracle", "non-indexed", "django"),
    ("Q15", "commercial_a", "indexed", "sqlalchemy"),
    ("Q17", "commercial_a", "indexed", "django"),
    ("Q18", "commercial_a", "indexed", "django"),
    ("Q21", "commercial_a", "non-indexed", "django"),
]
selected = []
for q, db, sc, f in cases:
    c = next(
        c
        for c in cells
        if (c["query"], c["system"], c["schema"], c["framework"]) == (q, db, sc, f)
    )
    selected.append(c)
table(
    "four_system_cases.tex",
    "Selected analytical cases. Seconds are marginal path medians; the ratio is the paired estimate and need not equal the quotient of the displayed seconds.",
    "tab:cases",
    "llllrrr",
    ["Query", "System", "Indexes", "Framework", "SQL (s)", "ORM (s)", "Paired ratio"],
    [
        [
            c["query"],
            LABEL[c["system"]],
            "yes" if c["schema"] == "indexed" else "no",
            FN[c["framework"]],
            "%.3f" % c["sql_s"],
            "%.3f" % c["orm_s"],
            "%.2f" % math.exp(c["theta"]) + r"$\times$",
        ]
        for c in selected
    ],
)
sensitivity = []
for name, pred in [
    ("All measured cells", lambda c: True),
    ("Exclude Oracle", lambda c: c["system"] != "oracle"),
    ("Three-system subset", lambda c: c["system"] != "commercial_a"),
    ("Exclude Q15", lambda c: c["query"] != "Q15"),
    ("Exclude Q18", lambda c: c["query"] != "Q18"),
    ("Exclude overhead above 100\\%", lambda c: c["overhead"] <= 100),
    ("Indexed only", lambda c: c["schema"] == "indexed"),
    ("Non-indexed only", lambda c: c["schema"] == "non-indexed"),
]:
    row = [name]
    for f in FW:
        v = summarize([c for c in cells if c["framework"] == f and pred(c)])
        row.extend(["%.2f" % v["median"], ci(v["ci"]), v["n"]])
    sensitivity.append(row)
table(
    "four_system_sensitivity.tex",
    "Sensitivity of analytical median overhead (percent) with query-clustered 95\\% intervals.",
    "tab:sensitivity",
    "lrr rrrr",
    [
        "Subset",
        "Django",
        "95\\% interval",
        "$n$",
        "SQLAlchemy",
        "95\\% interval",
        "$n$",
    ],
    sensitivity,
)
txn = {}
for f in FW:
    rows = [r for r in coverage if r["benchmark"] == "tpcc" and r["orm"].lower() == f]
    txn[f] = {
        "n": len(rows),
        "median": st.median(float(r["overhead_percentage"]) for r in rows),
    }
summary["transactional"] = txn
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
for name, rows in [("cells", cells), ("systems", system), ("cases", selected)]:
    with (OUT / (name + ".csv")).open("w") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

# Each configuration has a visible marker. The zoom is additional, not a replacement for the full range.
colors = {"django": "#2463a5", "sqlalchemy": "#d56720"}
plt.rcParams.update(
    {
        "font.size": 9,
        "pdf.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
fig, axs = plt.subplots(2, 4, figsize=(12.5, 5.5), sharex=True)
for j, db in enumerate(SYSTEMS):
    for i in range(2):
        ax = axs[i, j]
        for fi, f in enumerate(FW):
            for si, sc in enumerate(SC):
                data = [
                    c
                    for c in cells
                    if (c["system"], c["framework"], c["schema"]) == (db, f, sc)
                ]
                x = [
                    int(c["query"][1:]) + (fi - 0.5) * 0.32 + (si - 0.5) * 0.13
                    for c in data
                ]
                ax.scatter(
                    x,
                    [c["overhead"] for c in data],
                    s=15,
                    marker="o" if sc == "indexed" else "^",
                    facecolors=colors[f] if sc == "indexed" else "none",
                    edgecolors=colors[f],
                    linewidths=0.7,
                    zorder=3,
                )
        ax.axhline(0, color=".5", lw=0.6)
        ax.grid(axis="y", color=".9")
        ax.set_xlim(0.4, 22.6)
        ax.set_xticks([1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21])
        ax.tick_params(labelsize=7)
        if i == 0:
            ax.set_yscale("symlog", linthresh=1)
            ax.set_title(LABEL[db])
            ax.set_ylim(-100, 120000)
        else:
            ax.set_ylim(-3, 3)
            ax.set_xlabel("Query")
            ax.set_yticks([-3, -1, 0, 1, 3])
axs[0, 0].set_ylabel("Full range: overhead (%)")
axs[1, 0].set_ylabel("Detail: overhead (%)")
handles = [Line2D([], [], color=colors[f], marker="o", ls="", label=FN[f]) for f in FW]
handles += [
    Line2D([], [], color=".3", marker="o", ls="", label="Indexed"),
    Line2D([], [], color=".3", marker="^", mfc="none", ls="", label="Non-indexed"),
]
fig.legend(handles=handles, loc="upper center", ncol=4, frameon=False)
fig.tight_layout(rect=[0, 0, 1, 0.92])
fig.savefig(PAPER / "figures/four_system_query_distribution.pdf")
plt.close(fig)
fig, ax = plt.subplots(figsize=(5.8, 2.7))
for i, v in enumerate(system):
    x = (
        SYSTEMS.index(v["system"])
        + (FW.index(v["framework"]) - 0.5) * 0.2
        + (SC.index(v["schema"]) - 0.5) * 0.075
    )
    lo, hi = v["ci"]
    color = colors[v["framework"]]
    ax.errorbar(
        x,
        v["median"],
        yerr=[[v["median"] - lo], [hi - v["median"]]],
        fmt="o" if v["schema"] == "indexed" else "^",
        mfc=color if v["schema"] == "indexed" else "white",
        color=color,
        ms=4,
        capsize=2,
        lw=0.8,
    )
ax.set_yscale("symlog", linthresh=1)
ax.set_xticks(range(4), [LABEL[d] for d in SYSTEMS])
ax.set_ylabel("Median overhead (%)")
ax.axhline(0, color=".5", lw=0.6)
ax.grid(axis="y", color=".9")
fig.tight_layout()
fig.savefig(PAPER / "figures/four_system_systems.pdf")
plt.close(fig)
manifest = {
    str(f.relative_to(ROOT.parent)): hashlib.sha256(f.read_bytes()).hexdigest()
    for f in sorted([COVERAGE, *DATA.glob("*.csv")])
}
(OUT / "input-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(summary, indent=2))

# TPC-C is a main workload; rebuild its dedicated outputs as part of this entrypoint.
import runpy

tpcc_result = runpy.run_path(str(ROOT / "rebuild_tpcc.py"), run_name="__main__")[
    "summary"
]
summary["transactional"] = {
    fw: {"n": tpcc_result[fw]["n"], "median": tpcc_result[fw]["median_overhead"]}
    for fw in FW
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
