#!/usr/bin/env python3
"""Rebuild the q-error CSVs from saved execution plans.

The plans are the expensive artifact; deriving q-error from them is arithmetic.
Keeping the two steps separate means a crash in the derivation costs nothing and
the aggregation can be revised without re-running a single query.

    python3 qerror_from_plans.py [--outdir ...]
"""
import argparse, csv, glob, json, os, statistics

# Derived from this file's own location, so the script runs from a clone at any
# path. The default was /home/claude/bench/results_sf10, the sandbox the campaign
# happened to run in, which exists on no reviewer's machine.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_OUTDIR = os.path.join(_REPO, "results", "corrected")

BANDS = {
    **{f"Q{q:02d}": "Simple" for q in (6, 14, 19)},
    **{f"Q{q:02d}": "Medium" for q in (1, 3, 4, 11, 12, 16)},
    **{f"Q{q:02d}": "Complex" for q in (2, 5, 7, 10, 13, 15, 17, 18, 20)},
    **{f"Q{q:02d}": "Very Complex" for q in (8, 9, 21, 22)},
}


def qerror(est, act):
    if est is None or act is None or est <= 0 or act <= 0:
        return None
    return max(est / act, act / est)


def walk(node, out, depth=0, parent=None):
    est = node.get("Plan Rows")
    loops = node.get("Actual Loops", 1) or 1
    act = node.get("Actual Rows")
    if act is not None:
        act = act * loops
    qe = qerror(est, act)
    out.append({
        "depth": depth, "operator": node.get("Node Type"),
        "parent_operator": parent, "relation": node.get("Relation Name", ""),
        "index_name": node.get("Index Name", ""),
        "join_type": node.get("Join Type", ""),
        "estimated_rows": est, "actual_rows": act, "actual_loops": loops,
        "q_error": round(qe, 4) if qe is not None else "",
        "underestimate": ("" if qe is None else (est < act)),
        "actual_total_time_ms": node.get("Actual Total Time"),
        "shared_hit_blocks": node.get("Shared Hit Blocks"),
        "shared_read_blocks": node.get("Shared Read Blocks"),
    })
    for c in node.get("Plans", []) or []:
        walk(c, out, depth + 1, node.get("Node Type"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR)
    args = ap.parse_args()

    qdir = os.path.join(args.outdir, "qerror")
    os.makedirs(qdir, exist_ok=True)

    ops_rows, agg_rows = [], []
    files = sorted(glob.glob(os.path.join(args.outdir, "execution_plans", "*", "*.json")))
    for fp in files:
        d = json.load(open(fp))
        qid, fw, path = d["query_id"], d["framework"], d["path"]
        schema, status = d["schema"], d.get("status", "ok")
        base = {"schema_config": schema, "query_id": qid,
                "complexity_band": BANDS.get(qid, ""), "framework": fw,
                "access_path": path}

        if not d.get("plan"):
            agg_rows.append({**base, "status": status, "operators": 0,
                             "mean_qerror": "", "median_qerror": "", "max_qerror": "",
                             "operators_qerror_gt_2": "", "operators_qerror_gt_10": "",
                             "underestimate_rate_pct": "",
                             "total_shared_read_blocks": "", "plan_file": os.path.basename(fp)})
            continue

        ops = []
        walk(d["plan"], ops)
        qs = [o["q_error"] for o in ops if o["q_error"] != ""]
        unders = [o["underestimate"] for o in ops if o["underestimate"] != ""]
        reads = sum(o["shared_read_blocks"] or 0 for o in ops)
        for o in ops:
            o.update(base)
            ops_rows.append(o)
        agg_rows.append({
            **base, "status": "ok", "operators": len(ops),
            "mean_qerror": round(statistics.mean(qs), 3) if qs else "",
            "median_qerror": round(statistics.median(qs), 3) if qs else "",
            "max_qerror": round(max(qs), 3) if qs else "",
            "operators_qerror_gt_2": sum(1 for q in qs if q > 2),
            "operators_qerror_gt_10": sum(1 for q in qs if q > 10),
            "underestimate_rate_pct": (round(100 * sum(unders) / len(unders), 1)
                                       if unders else ""),
            "total_shared_read_blocks": reads,
            "plan_file": os.path.basename(fp),
        })

    okeys = ["schema_config", "query_id", "complexity_band", "framework",
             "access_path", "depth", "operator", "parent_operator", "relation",
             "index_name", "join_type", "estimated_rows", "actual_rows",
             "actual_loops", "q_error", "underestimate", "actual_total_time_ms",
             "shared_hit_blocks", "shared_read_blocks"]
    with open(os.path.join(qdir, "qerror_by_operator.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=okeys, extrasaction="ignore")
        w.writeheader()
        w.writerows(ops_rows)
    with open(os.path.join(qdir, "qerror_by_query.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(agg_rows[0].keys()))
        w.writeheader()
        w.writerows(agg_rows)

    print(f"plans read      : {len(files)}")
    print(f"operator rows   : {len(ops_rows)}")
    print(f"config rows     : {len(agg_rows)}  "
          f"({sum(1 for r in agg_rows if r['status'] == 'ok')} with a plan)")


if __name__ == "__main__":
    main()
