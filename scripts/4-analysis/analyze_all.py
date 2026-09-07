#!/usr/bin/env python3
"""Cross-system analysis: every DBMS, both benchmarks, both schemas.

    python3 analyze_all.py                     # writes results/analysis/
    python3 analyze_all.py --outdir somewhere

`superseded/analyze_sf10.py` reads `postgresql_{indexed,non_indexed}.csv` and stamps its
output `"dbms": "PostgreSQL 14.9"`. That was correct when PostgreSQL was the only
system measured; the study now has four, on two benchmarks, and a one-system
analysis silently answers a narrower question than the file it reads from can
support.

Everything here derives from `results/all_results.csv`, the single generated
file, so the analysis and the results cannot disagree.

Three things this deliberately does not do:

*It does not pool TPC-H and TPC-C.* Their overheads differ by an order of
magnitude — that is the study's main finding, and averaging them away would
destroy it.

*It does not compare absolute times across systems.* SQL Server runs under
x86-64 emulation, Oracle is licence-capped to 2 CPU threads and 1.5 GB, and
MySQL cannot execute a query on more than one thread. Only the ORM-versus-SQL
ratio within a row is comparable, because both arms of it share every one of
those conditions.

*It does not hide the cells that are missing.* Oracle's coverage is reported
beside its overheads, because a median over 9 cells and a median over 44 do not
carry the same weight.
"""
import argparse
import collections
import csv
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))


def load(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def overhead_rows(rows, bench):
    """-> {(dbms, schema, orm): [overhead %]} for cells with both paths measured."""
    out = collections.defaultdict(list)
    for r in rows:
        if r.get("benchmark") != bench:
            continue
        ov = num(r.get("overhead_percentage"))
        if ov is None:
            continue
        out[(r["dbms"], r["schema_config"], r["orm"])].append((ov, r["query_id"]))
    return out


def summarise(vals):
    v = [x[0] for x in vals]
    if not v:
        return None
    return {
        "n": len(v),
        "median": round(statistics.median(v), 1),
        "mean": round(statistics.mean(v), 1),
        "min": round(min(v), 1),
        "max": round(max(v), 1),
        "worst_query": max(vals)[1],
        "best_query": min(vals)[1],
    }


def coverage(rows):
    c = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = (r["dbms"], r["benchmark"], r["schema_config"])
        c[k][1] += 1
        if num(r.get("overhead_percentage")) is not None:
            c[k][0] += 1
    return c


def tex_table(title, label, header, body_rows):
    out = ["\\begin{table}[t]", "\\centering", "\\caption{%s}" % title,
           "\\label{%s}" % label,
           "\\begin{tabular}{%s}" % ("l" * (len(header) - 2) + "rr"),
           "\\hline", " & ".join(header) + " \\\\", "\\hline"]
    out += [" & ".join(str(c) for c in r) + " \\\\" for r in body_rows]
    out += ["\\hline", "\\end{tabular}", "\\end{table}"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(REPO, "results", "all_results.csv"))
    ap.add_argument("--outdir", default=os.path.join(REPO, "results", "analysis"))
    args = ap.parse_args()

    rows = load(args.results)
    os.makedirs(args.outdir, exist_ok=True)
    cov = coverage(rows)
    report = {"source": os.path.relpath(args.results, REPO), "benchmarks": {}}

    for bench, label in (("tpch", "TPC-H"), ("tpcc", "TPC-C")):
        ov = overhead_rows(rows, bench)
        block, tex = {}, []
        print("\n=== %s: median ORM overhead against the same framework's SQL ===" % label)
        print("  %-12s %-12s %-11s %8s %7s %9s %9s  %s"
              % ("dbms", "schema", "orm", "median", "n", "min", "max", "coverage"))
        for key in sorted(ov):
            s = summarise(ov[key])
            if not s:
                continue
            dbms, schema, orm = key
            done, total = cov[(dbms, bench, schema)]
            block["|".join(key)] = dict(s, measured=done, cells=total)
            print("  %-12s %-12s %-11s %+7.1f%% %7d %+8.1f%% %+8.1f%%  %d/%d"
                  % (dbms, schema, orm.lower(), s["median"], s["n"],
                     s["min"], s["max"], done, total))
            tex.append([dbms, schema, orm.title(),
                        "%+.1f\\%%" % s["median"], s["n"]])
        report["benchmarks"][bench] = block
        open(os.path.join(args.outdir, "tab_overhead_%s.tex" % bench), "w").write(
            tex_table("Median ORM overhead, %s" % label,
                      "tab:overhead_%s" % bench,
                      ["DBMS", "Schema", "ORM", "Median", "n"], tex))

    # The headline: the two benchmarks disagree by an order of magnitude.
    print("\n=== the finding the two-benchmark design exists to produce ===")
    hl = []
    for orm in ("DJANGO", "SQLALCHEMY"):
        for bench, label in (("tpch", "TPC-H"), ("tpcc", "TPC-C")):
            v = [x[0] for k, vals in overhead_rows(rows, bench).items()
                 if k[2] == orm for x in vals]
            if v:
                hl.append((orm.title(), label, round(statistics.median(v), 1), len(v)))
                print("  %-11s %-7s median %+7.1f%%  (n=%d)"
                      % (orm.title(), label, statistics.median(v), len(v)))
    report["headline"] = [{"orm": a, "benchmark": b, "median": c, "n": d}
                          for a, b, c, d in hl]
    open(os.path.join(args.outdir, "tab_headline.tex"), "w").write(
        tex_table("ORM overhead by workload type, all systems pooled",
                  "tab:headline", ["ORM", "Benchmark", "Median", "n"],
                  [[a, b, "%+.1f\\%%" % c, d] for a, b, c, d in hl]))

    # Outliers are where the mechanism lives; the medians hide them.
    print("\n=== largest single-query overheads (TPC-H) ===")
    worst = sorted(((x[0], k[0], k[1], k[2], x[1])
                    for k, vals in overhead_rows(rows, "tpch").items()
                    for x in vals), reverse=True)[:8]
    for ovp, dbms, schema, orm, q in worst:
        print("  %-6s %-12s %-12s %-11s %+9.1f%%" % (q, dbms, schema, orm.lower(), ovp))
    report["tpch_outliers"] = [{"query": q, "dbms": d, "schema": s,
                                "orm": o, "overhead": round(v, 1)}
                               for v, d, s, o, q in worst]

    with open(os.path.join(args.outdir, "analysis_all.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    print("\nwritten to %s" % os.path.relpath(args.outdir, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
