#!/usr/bin/env python3
"""Second server against the benchmark host, cell by cell (reviewer item R2-6).

For every (run, query, framework) cell that both phase A (host) and phase G
(Mac) measured with all 8 blocks accepted: median path times on each machine,
the speed-up of each path, both overhead figures, and the ratio of ratios
(Mac ratio / host ratio). A uniformly faster machine leaves that ratio of
ratios at 1; it moves only where client and server parts speed up unequally or
where a plan differs. Feeds 05-mac-speed-justification.md.

Usage: python3 code/rc_compare_g.py [--out evidence/G-vs-A-comparison.json]
"""
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_analyze as R  # noqa: E402

RUNS = [f'{e}-{s}' for e in ('postgresql', 'mysql', 'oracle', 'sqlserver') for s in ('non-indexed', 'indexed')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, default=HERE.parent)
    ap.add_argument('--out', type=Path)
    a = ap.parse_args()
    R.path_cvs, R.censored_cells = [], []
    rows = []
    for run in RUNS:
        ad, gd = a.campaign_dir / 'A-sf1' / run, a.campaign_dir / 'G-mac-server' / 'v2' / run
        if not (ad.exists() and gd.exists()):
            continue
        ca = {(c['query'], c['framework']): c for c in R.load_run(ad)[0]}
        cg = {(c['query'], c['framework']): c for c in R.load_run(gd)[0]}
        for q, fw in sorted(set(ca) & set(cg)):
            h, m = ca[(q, fw)], cg[(q, fw)]
            rows.append({'run': run, 'query': q, 'framework': fw,
                         'host_sql_s': h['sql_s'], 'mac_sql_s': m['sql_s'], 'host_orm_s': h['orm_s'], 'mac_orm_s': m['orm_s'],
                         'sql_speedup': h['sql_s'] / m['sql_s'], 'orm_speedup': h['orm_s'] / m['orm_s'],
                         'host_overhead_pct': h['overhead_pct'], 'mac_overhead_pct': m['overhead_pct'],
                         'ratio_of_ratios': math.exp(m['theta'] - h['theta'])})
    cls = lambda v: 'above_100' if v > 100 else 'positive' if v > 0 else 'negative'
    rr = [r['ratio_of_ratios'] for r in rows]
    summary = {'cells': len(rows)}
    if rows:
        summary.update({
            'sql_speedup_median': st.median(r['sql_speedup'] for r in rows),
            'sql_speedup_range': [min(r['sql_speedup'] for r in rows), max(r['sql_speedup'] for r in rows)],
            'orm_speedup_median': st.median(r['orm_speedup'] for r in rows),
            'orm_speedup_range': [min(r['orm_speedup'] for r in rows), max(r['orm_speedup'] for r in rows)],
            'ratio_of_ratios_median': st.median(rr),
            'within_10pct': sum(0.9 <= v <= 1.1 for v in rr),
            'outside_10pct': [f"{r['run']} q{r['query']:02d} {r['framework']}" for r in rows if not 0.9 <= r['ratio_of_ratios'] <= 1.1],
            'same_class': sum(cls(r['host_overhead_pct']) == cls(r['mac_overhead_pct']) for r in rows),
            'same_above_100': sum((r['host_overhead_pct'] > 100) == (r['mac_overhead_pct'] > 100) for r in rows)})
    print('| run | Q | framework | host SQL | Mac SQL | SQL × | ORM × | host overhead % | Mac overhead % |')
    print('|---|---|---|---|---|---|---|---|---|')
    for r in rows:
        print(f"| {r['run']} | {r['query']} | {r['framework']} | {r['host_sql_s']:.3f} | {r['mac_sql_s']:.3f} | "
              f"{r['sql_speedup']:.2f} | {r['orm_speedup']:.2f} | {r['host_overhead_pct']:.1f} | {r['mac_overhead_pct']:.1f} |")
    print(json.dumps(summary, indent=1))
    if a.out:
        a.out.write_text(json.dumps({'summary': summary, 'cells': rows}, indent=1) + '\n')


if __name__ == '__main__':
    main()
