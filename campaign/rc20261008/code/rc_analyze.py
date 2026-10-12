#!/usr/bin/env python3
"""Offline analysis of an analytical campaign dataset (phase A, D or E).

Estimand and interval exactly as IJACSA_Paper/reproducibility/rebuild.py:
  theta(cell) = median over blocks of log(t_orm / t_sql), reported 100*expm1;
  pooled and per-framework medians of theta; 95% interval from a
  query-clustered bootstrap (2000 resamples, seed 20260907 ^ crc32(cells));
  exact two-sided Wilcoxon on per-query medians of theta, per framework.

Inputs differ in one respect that is stated, not hidden: only ACCEPTED pairs
(decision.json: both timed calls ok, ORM result accepted against its own SQL
baseline, ORM path check passed) enter a ratio. A cell enters the estimand only
with all eight blocks accepted; a cell with fewer is reported as partial and
excluded, with its count. Censored and inexpressible arms come from the
records, never from absence.

Outputs (in --out): cells.csv, coverage.csv, summary.json, sensitivity.json.
"""
import argparse
import collections
import csv
import gzip
import json
import math
from pathlib import Path
import random
import statistics as st
import sys
import zlib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

pct = lambda x: 100 * math.expm1(x)
path_cvs, censored_cells = [], []
SYSTEMS = ['postgresql', 'mysql', 'oracle', 'commercial_a']


def interval(cells):
    key = '|'.join('%s:%.12g' % (q, t) for q, t in sorted(cells))
    rng = random.Random(20260907 ^ zlib.crc32(key.encode()))
    by = collections.defaultdict(list)
    for q, t in cells:
        by[q].append(t)
    qs = list(by)
    if len(qs) < 2:
        return [None, None]
    s = sorted(st.median([t for _ in qs for t in by[qs[rng.randrange(len(qs))]]]) for _ in range(2000))
    return [pct(s[50]), pct(s[1950])]


def summarize(items):
    if not items:
        return {'n': 0}
    return {'n': len(items), 'median_pct': pct(st.median(v['theta'] for v in items)),
            'ci_pct': interval([(v['query'], v['theta']) for v in items]),
            'above100': sum(v['overhead_pct'] > 100 for v in items)}


def wilcoxon_p(cells, fw):
    # no silent fallback: a missing scipy left every p-value None, unnoticed
    # (found 2026-10-11 03:55). Run with an environment that has scipy, e.g.
    # code/orm-benchmark-reproducibility/venv (scipy 1.11.4, as the paper's rebuild.py).
    from scipy.stats import wilcoxon
    qm = [st.median(c['theta'] for c in cells if c['framework'] == fw and c['query'] == q)
          for q in sorted({c['query'] for c in cells if c['framework'] == fw})]
    if len(qm) < 2:
        return None
    return {'p': float(wilcoxon(qm, method='exact').pvalue), 'queries': len(qm)}


def load_run(run_dir):
    params = json.loads((run_dir / 'run-parameters.json').read_text())
    cells, coverage, numeric_cells = [], [], []
    global path_cvs, censored_cells
    for cdir in sorted(run_dir.glob('q[0-9][0-9]')):
        q = int(cdir.name[1:])
        outcome = C.load(cdir / 'cellwarm' / 'outcome.json') if (cdir / 'cellwarm' / 'outcome.json').exists() else {}
        done = C.load(cdir / 'cell-done.json') if (cdir / 'cell-done.json').exists() else {}
        for fw in ('django', 'sqlalchemy'):
            ratios, sql_t, orm_t, classes, statuses = [], [], [], collections.Counter(), collections.Counter()
            ratios_num = []   # numeric_mismatch pairs: timed, rejected, sensitivity only
            for b in range(1, 9):
                d = cdir / f'b{b}' / 'decision.json'
                if not d.exists():
                    statuses['not_decided'] += 1
                    continue
                dec = C.load(d)
                fd = dec['frameworks'][fw]
                statuses[fd['status']] += 1
                if fd['accepted']:
                    classes[fd['classification']] += 1
                    so = C.load(d.parent / dec['timed_records'][f'{fw}/sql'])
                    oo = C.load(d.parent / dec['timed_records'][f'{fw}/orm'])
                    ratios.append(math.log(oo['elapsed_s'] / so['elapsed_s']))
                    sql_t.append(so['elapsed_s'])
                    orm_t.append(oo['elapsed_s'])
                    ratios_num.append(ratios[-1])
                elif fd['status'] == 'numeric_mismatch':
                    so = C.load(d.parent / dec['timed_records'][f'{fw}/sql'])
                    oo = C.load(d.parent / dec['timed_records'][f'{fw}/orm'])
                    ratios_num.append(math.log(oo['elapsed_s'] / so['elapsed_s']))
            arms = {p: why for p, why in {**{k: 'censored' for k in outcome.get('censored', {})},
                                         **{k: 'not_expressible' for k in outcome.get('inexpressible', {})}}.items()
                    if p.startswith(fw)}
            status = ('measured' if len(ratios) == 8 else
                      'not_expressible' if 'not_expressible' in arms.values() else
                      'censored' if arms else
                      'partial' if ratios else
                      'unresolved')
            coverage.append({'dbms': params['dbms'], 'schema': params['schema'], 'scale': params['scale'],
                             'query': q, 'framework': fw, 'status': status, 'accepted_blocks': len(ratios),
                             'block_statuses': dict(statuses), 'acceptance_classes': dict(classes),
                             'arms_not_run': arms, 'cell_status': done.get('status')})
            cvs = {}
            for pname, ts in (('sql', sql_t), ('orm', orm_t)):
                if len(ts) >= 2 and st.mean(ts) > 0:
                    cvs[pname] = 100 * st.stdev(ts) / st.mean(ts)
            path_cvs.extend({'dbms': params['dbms'], 'schema': params['schema'], 'query': q, 'framework': fw,
                             'path': k, 'cv_pct': v} for k, v in cvs.items())
            if status == 'censored':
                censored_cells.append({'system': params['dbms'], 'schema': params['schema'], 'query': q,
                                       'framework': fw, 'arms': arms})
            if len(ratios) < 8 and len(ratios_num) == 8:
                numeric_cells.append({'system': params['dbms'], 'schema': params['schema'], 'scale': params['scale'],
                                      'query': q, 'framework': fw, 'theta': st.median(ratios_num),
                                      'overhead_pct': pct(st.median(ratios_num)), 'classes': {'numeric_mismatch': 8 - len(ratios)}})
            if len(ratios) == 8:
                cells.append({'system': params['dbms'], 'schema': params['schema'], 'scale': params['scale'],
                              'query': q, 'framework': fw, 'theta': st.median(ratios),
                              'overhead_pct': pct(st.median(ratios)), 'sql_s': st.median(sql_t),
                              'orm_s': st.median(orm_t), 'added_ms': 1000 * (st.median(orm_t) - st.median(sql_t)),
                              'classes': dict(classes)})
    return cells, coverage, numeric_cells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dirs', type=Path, nargs='+')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    cells, coverage, numeric_cells = [], [], []
    for r in a.run_dirs:
        c, cv, nc = load_run(r)
        cells += c
        coverage += cv
        numeric_cells += nc
    a.out.mkdir(parents=True, exist_ok=True)
    summary = {'pooled': summarize(cells)}
    for fw in ('django', 'sqlalchemy'):
        summary[fw] = summarize([c for c in cells if c['framework'] == fw])
        summary[fw]['wilcoxon'] = wilcoxon_p(cells, fw)
    for s in SYSTEMS:
        summary[s] = summarize([c for c in cells if c['system'] == s])
    for sc in ('indexed', 'non-indexed'):
        summary[sc] = summarize([c for c in cells if c['schema'] == sc])
    summary['coverage'] = dict(collections.Counter(c['status'] for c in coverage))
    summary['acceptance_classes'] = dict(sum((collections.Counter(c['classes']) for c in cells), collections.Counter()))
    sens = {'exclude_commercial_a': summarize([c for c in cells if c['system'] != 'commercial_a']),
            'exclude_oracle': summarize([c for c in cells if c['system'] != 'oracle']),
            'include_numeric_mismatch_cells': dict(summarize(cells + numeric_cells), added=len(numeric_cells)),
            'exclude_scale_equivalent_cells': summarize([c for c in cells if 'scale_equivalent' not in c['classes']]),
            'above100_by_schema': {sc: [sum(c['overhead_pct'] > 100 for c in cells if c['schema'] == sc),
                                        sum(1 for c in cells if c['schema'] == sc)] for sc in ('indexed', 'non-indexed')}}
    # R1-6: worst case for censored cells - every censored cell placed above
    # every measured cell (its true overhead is unknown but its slow arm
    # exceeded the ceiling); phase B bounds are reported separately.
    inf = [dict(c, theta=float('inf'), overhead_pct=float('inf')) for c in censored_cells]
    allc = cells + inf
    sens['censored_worst_case'] = {'n_measured': len(cells), 'n_censored': len(inf),
                                   'median_pct': pct(st.median(c['theta'] for c in allc)) if allc else None,
                                   'measured_only_median_pct': summary['pooled'].get('median_pct'),
                                   'above100_including_censored': sum(c['overhead_pct'] > 100 for c in allc)}
    # R1-5a: valid cells per query and framework, and the Wilcoxon inclusion used
    per_q = collections.defaultdict(lambda: collections.Counter())
    for c in coverage:
        per_q[(c['query'], c['framework'])][c['status']] += 1
    summary['wilcoxon_inclusion'] = 'a query enters with the median of its measured cells (at least one); ' \
                                    'counts of valid cells per query are reported beside it'
    summary['valid_cells_per_query'] = {f'Q{q:02d}:{fw}': dict(v) for (q, fw), v in sorted(per_q.items())}
    # R1-3/R2-4 variability criteria from the paper (pre-pilot): median CV <= 5 %,
    # 90th percentile <= 15 %, at most 5 % of paths above 25 %.
    cv = sorted(x['cv_pct'] for x in path_cvs)
    if cv:
        summary['variability'] = {'paths': len(cv), 'median_cv_pct': st.median(cv),
                                  'p90_cv_pct': cv[min(len(cv) - 1, int(0.9 * len(cv)))],
                                  'share_above_25_pct': sum(x > 25 for x in cv) / len(cv),
                                  'criteria': {'median_le_5': st.median(cv) <= 5,
                                               'p90_le_15': cv[min(len(cv) - 1, int(0.9 * len(cv)))] <= 15,
                                               'share_above_25_le_5pct': sum(x > 25 for x in cv) / len(cv) <= 0.05}}
    for name, rows in (('cells', cells), ('coverage', coverage), ('path_cvs', path_cvs), ('censored', censored_cells)):
        with open(a.out / f'{name}.csv', 'w', newline='') as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                for r in rows:
                    w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    (a.out / 'summary.json').write_text(json.dumps(summary, indent=1, default=str) + '\n')
    (a.out / 'sensitivity.json').write_text(json.dumps(sens, indent=1, default=str) + '\n')
    print(json.dumps({'pooled': summary['pooled'], 'coverage': summary['coverage']}, default=str))


if __name__ == '__main__':
    main()
