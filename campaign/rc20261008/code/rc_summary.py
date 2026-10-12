#!/usr/bin/env python3
"""All-phase summary of campaign rc20261008: the numbers behind 09-analysis-summary.md.

Reads only generated outputs and records, and redefines no estimate:
  - results-all-phases.csv (code/rc_collect.py);
  - the rc_analyze.py outputs of A, D and E (summary.json, sensitivity.json, cells.csv);
  - the C-tpcc records, for the per-path coefficients of variation that
    R1-3 asks for;
  - the paper's reproducibility/derived/{cells.csv,summary.json,tpcc_summary.json};
  - evidence/background-jobs/overlap-20261011b.json (code/rc_background_overlap.py).
The cross-phase comparisons (A vs paper, D vs A, E vs A, G vs A) use the same
ratio of ratios as code/rc_compare_g.py: (1 + o_new/100) / (1 + o_ref/100) per
matched cell, "within 10 %" meaning 0.9 <= ratio <= 1.1.

Usage: python code/rc_summary.py --a analysis/run-20261011T2000/A-sf1 --d analysis/run-20261011T0400/D-sf2 \
           --e analysis/run-20261011T2215/E-client --out analysis/<new-folder>/all-phases
"""
import argparse
import collections
import csv
import gzip
import json
import math
from pathlib import Path
import statistics as st
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

CAMP = HERE.parent
PAPER = CAMP.parents[1] / 'analysis' / 'reference' / 'derived'  # the release's historical outputs
SYSTEMS = ('postgresql', 'mysql', 'oracle', 'commercial_a')


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rr_summary(pairs):
    """pairs: [(label, new_pct, ref_pct)] -> median ratio of ratios, within-10 % count, outside list."""
    rr = [((1 + n / 100) / (1 + r / 100), lab) for lab, n, r in pairs]
    if not rr:
        return {'n': 0}
    return {'n': len(rr), 'median_ratio_of_ratios': st.median(v for v, _ in rr),
            'within_10pct': sum(0.9 <= v <= 1.1 for v, _ in rr),
            'outside_10pct': sorted(f'{lab} x{v:.3f}' for v, lab in rr if not 0.9 <= v <= 1.1)}


def cells_csv(d):
    out = {}
    for r in csv.DictReader(open(d / 'cells.csv')):
        out[(r['system'], r['schema'], int(r['query']), r['framework'])] = float(r['overhead_pct'])
    return out


def by_engine(pairs_by_key):
    out = {}
    for e in SYSTEMS:
        sub = [(lab, n, r) for (k, lab, n, r) in pairs_by_key if k[0] == e]
        if sub:
            s = rr_summary(sub)
            out[e] = {k: s[k] for k in ('n', 'median_ratio_of_ratios', 'within_10pct')}
    return out


def compare(new, ref):
    keyed = [(k, f'{k[0]} {k[1]} Q{k[2]:02d} {k[3]}', new[k], ref[k]) for k in sorted(new) if k in ref]
    s = rr_summary([(lab, n, r) for _, lab, n, r in keyed])
    s['by_engine'] = by_engine(keyed)
    return s


def tpcc_cvs():
    """Per path (cell x {sql, orm}) CV over the accepted blocks, from the timed records."""
    out = []
    for run in sorted(p for p in (CAMP / 'C-tpcc').iterdir() if p.is_dir() and p.name != 'oracle-non-indexed'):
        for tdir in sorted(run.glob('T[0-9]')):
            for fw in ('django', 'sqlalchemy'):
                t = {'sql': [], 'orm': []}
                for d in sorted(tdir.glob('b[0-9][0-9]/decision.json')):
                    dec = json.loads(d.read_text())
                    if not dec['frameworks'].get(fw, {}).get('accepted'):
                        continue
                    att = sorted(d.parent.glob('a*'))[-1]
                    for p in t:
                        t[p].append(C.untyped(json.load(gzip.open(att / f'timed-{fw}-{p}.json.gz')))['elapsed_s'])
                for p, ts in t.items():
                    if len(ts) >= 2:
                        out.append({'run': run.name, 'tx': tdir.name, 'framework': fw, 'path': p,
                                    'cv_pct': 100 * st.stdev(ts) / st.mean(ts), 'blocks': len(ts)})
    return out


def variability(cvs):
    cv = sorted(cvs)
    p90 = cv[min(len(cv) - 1, int(0.9 * len(cv)))]
    return {'paths': len(cv), 'median_cv_pct': st.median(cv), 'p90_cv_pct': p90,
            'share_above_25_pct': sum(x > 25 for x in cv) / len(cv),
            'criteria': {'median_le_5': st.median(cv) <= 5, 'p90_le_15': p90 <= 15,
                         'share_above_25_le_5pct': sum(x > 25 for x in cv) / len(cv) <= 0.05}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', type=Path, required=True)
    ap.add_argument('--d', type=Path, required=True)
    ap.add_argument('--e', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    rows = list(csv.DictReader(open(CAMP / 'results-all-phases.csv')))
    by_phase = collections.defaultdict(list)
    for r in rows:
        by_phase[r['phase']].append(r)
    paper = json.loads((PAPER / 'summary.json').read_text())
    paper_tpcc = json.loads((PAPER / 'tpcc_summary.json').read_text())
    paper_cells = {(r['system'], r['schema'], int(r['query'][1:]), r['framework']): float(r['overhead'])
                   for r in csv.DictReader(open(PAPER / 'cells.csv'))}
    S = {'generated': C.stamps(), 'inputs': {'A': str(a.a), 'D': str(a.d), 'E': str(a.e),
                                            'results': 'results-all-phases.csv', 'paper': str(PAPER)},
         'status_counts': {ph: dict(collections.Counter(r['status'] for r in v)) for ph, v in sorted(by_phase.items())}}

    # A, D, E: the rc_analyze outputs, quoted, plus the cross-phase comparisons recomputed here
    A, D, E = cells_csv(a.a), cells_csv(a.d), cells_csv(a.e)
    for ph, d in (('A', a.a), ('D', a.d), ('E', a.e)):
        S[ph] = {'summary': json.loads((d / 'summary.json').read_text()),
                 'sensitivity': json.loads((d / 'sensitivity.json').read_text())}
        S[ph]['summary'].pop('valid_cells_per_query', None) if ph != 'A' else None
    S['A']['vs_paper'] = {
        'paper': {'pooled': paper['pooled'], 'django': paper['django'], 'sqlalchemy': paper['sqlalchemy'],
                  'above100': paper['counts']['above100']},
        'cells': compare(A, paper_cells)}
    a100 = {k for k, v in A.items() if v > 100}
    p100 = {k for k, v in paper_cells.items() if v > 100}
    fmt = lambda ks: sorted(f'{k[0]} {k[1]} Q{k[2]:02d} {k[3]}' for k in ks)
    S['A']['above100_sets'] = {'campaign': len(a100), 'paper': len(p100), 'both': len(a100 & p100),
                               'campaign_only': fmt(a100 - p100), 'paper_only': fmt(p100 - a100),
                               'paper_only_status_in_A': {f'{k[0]} {k[1]} Q{k[2]:02d} {k[3]}':
                                                          next((r['status'] for r in by_phase['A']
                                                                if (r['dbms'], r['schema'], r['query'], r['framework']) ==
                                                                (k[0], k[1], f'Q{k[2]:02d}', k[3])), None)
                                                          for k in p100 - a100}}
    S['D']['vs_A_sf1'] = compare(D, A)
    S['E']['vs_A'] = compare(E, A)

    # B: lower bounds
    S['B'] = [{k: r[k] for k in ('dbms', 'schema', 'query', 'framework', 'status', 'status_note')} for r in by_phase['B']]

    # C: transactions
    cr = [r for r in by_phase['C'] if num(r['overhead_pct']) is not None]
    def med(sub):
        # median in log space, as the paper's rebuild_tpcc.py (logmedian) and rc_analyze.py: with an
        # even count the two middle cells are averaged as log ratios, not as percentages
        return {'n': len(sub), 'median_overhead_pct': 100 * math.expm1(st.median(math.log1p(num(r['overhead_pct']) / 100)
                                                                                for r in sub)),
                'median_added_ms': st.median(num(r['added_ms']) for r in sub),
                'above100': sum(num(r['overhead_pct']) > 100 for r in sub)}
    cvs = tpcc_cvs()
    S['C'] = {'pooled': med(cr), 'django': med([r for r in cr if r['framework'] == 'django']),
              'sqlalchemy': med([r for r in cr if r['framework'] == 'sqlalchemy']),
              'exclude_commercial_a': med([r for r in cr if r['dbms'] != 'commercial_a']),
              'by_transaction': {t: med([r for r in cr if r['query'] == t]) for t in ('T1', 'T2', 'T3', 'T4', 'T5')},
              'by_engine': {e: med([r for r in cr if r['dbms'] == e]) for e in SYSTEMS},
              'by_schema': {s: med([r for r in cr if r['schema'] == s]) for s in ('indexed', 'non-indexed')},
              'blocks_accepted': sum(int(r['accepted_blocks']) for r in cr), 'blocks_planned': 24 * len(cr),
              'variability': variability([x['cv_pct'] for x in cvs]),
              'variability_sql_paths': variability([x['cv_pct'] for x in cvs if x['path'] == 'sql']),
              'variability_orm_paths': variability([x['cv_pct'] for x in cvs if x['path'] == 'orm']),
              'paper': paper_tpcc}
    S['C']['vs_paper'] = rr_summary([(f"{r['dbms']} {r['schema']} {r['query']} {r['framework']}",
                                      num(r['overhead_pct']), num(r['paper_overhead_pct']))
                                     for r in cr if num(r['paper_overhead_pct']) is not None])

    # F: four-path decomposition, O vs G (client-side ORM work), G vs B (SQL formulation with the
    # ORM's own bindings), B vs L (binding against literals); dominant = largest |log| share
    fr = [r for r in by_phase['F'] if r['status'] == 'measured' and num(r['orm_vs_generated_pct']) is not None]
    comp = {'O/G client': 'orm_vs_generated_pct', 'G/B formulation': 'generated_vs_bound_pct', 'B/L binding': 'bound_vs_literal_pct'}
    def dominant(r):
        logs = {k: math.log1p(num(r[c]) / 100) for k, c in comp.items()}
        return max(logs, key=lambda k: abs(logs[k])), logs
    cells_f = []
    for r in fr:
        dom, logs = dominant(r)
        cells_f.append({'cell': f"{r['dbms']} {r['schema']} {r['query']} {r['framework']}",
                        'selection': r['status_note'].split(';')[0].split(':')[0][:60],
                        'overhead_pct': num(r['overhead_pct']), 'paper_overhead_pct': num(r['paper_overhead_pct']),
                        'orm_vs_generated_pct': num(r['orm_vs_generated_pct']),
                        'generated_vs_bound_pct': num(r['generated_vs_bound_pct']),
                        'bound_vs_literal_pct': num(r['bound_vs_literal_pct']), 'dominant': dom,
                        'dominant_share_of_log_gap': (logs[dom] / math.log1p(num(r['overhead_pct']) / 100)
                                                      if abs(num(r['overhead_pct'])) > 1 else None)})
    big = [c for c in cells_f if c['overhead_pct'] > 100]
    S['F'] = {'cells': len(by_phase['F']), 'measured': len(fr),
              'not_measured': [f"{r['dbms']} {r['schema']} {r['query']} {r['framework']}: {r['status']}"
                               for r in by_phase['F'] if r not in fr],
              'selection': dict(collections.Counter(c['selection'] for c in cells_f)),
              'above100': len(big), 'dominant_above100': dict(collections.Counter(c['dominant'] for c in big)),
              'dominant_all': dict(collections.Counter(c['dominant'] for c in cells_f)),
              'max_abs_orm_vs_generated_pct_above100': max(abs(c['orm_vs_generated_pct']) for c in big),
              'median_abs_orm_vs_generated_pct_all': st.median(abs(c['orm_vs_generated_pct']) for c in cells_f),
              'cells_detail': cells_f}

    # G: the Mac as server against the host, cell by cell
    gr = [r for r in by_phase['G'] if r['status'] == 'measured' and num(r['host_overhead_pct']) is not None]
    keyed = [((r['dbms'],), f"{r['dbms']} {r['schema']} {r['query']} {r['framework']}",
              num(r['overhead_pct']), num(r['host_overhead_pct'])) for r in gr]
    S['G'] = rr_summary([(lab, n, h) for _, lab, n, h in keyed])
    S['G']['by_engine'] = by_engine(keyed)
    S['G']['column_check_max_abs_diff'] = max(abs(num(r['mac_vs_host_ratio']) -
                                                  (1 + num(r['overhead_pct']) / 100) / (1 + num(r['host_overhead_pct']) / 100))
                                              for r in gr)

    # V: censored-cell validation
    S['V'] = [{k: r[k] for k in ('dbms', 'schema', 'query', 'framework', 'status')} for r in by_phase['V']]

    # background jobs (decision log 2026-10-11 22:30)
    bj = json.loads((CAMP / 'evidence/background-jobs/overlap-20261011b.json').read_text())
    S['background_jobs'] = {ph: {k: v for k, v in x.items() if k not in ('cells_touched', 'blocks', 'records', 'runs')}
                            for ph, x in bj['phases'].items()}

    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'summary.json').write_text(json.dumps(S, indent=1, default=str) + '\n')
    with open(a.out / 'F-decomposition.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(cells_f[0]))
        w.writeheader()
        w.writerows(cells_f)
    with open(a.out / 'C-path-cvs.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(cvs[0]))
        w.writeheader()
        w.writerows(cvs)
    print('->', a.out)


if __name__ == '__main__':
    main()
