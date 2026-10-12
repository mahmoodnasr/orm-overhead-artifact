#!/usr/bin/env python3
"""One results file for the whole campaign: every planned cell, finished or not.

results-all-phases.csv has one row per planned cell of every phase (A, G, D,
E, C, F). A row is always emitted. A cell that has no result says why in
words in status_note: not started yet (and where it sits in the schedule),
running, censored at the 900 s limit, not expressible, or not run by a recorded
rule. Absence is never silent. Measured rows carry the median path times, the
overhead 100*(exp(theta)-1) and the paper's value for the same cell, and phase G
rows also carry the host's phase A value for comparison.

Generated, never hand-edited. Run on the Mac after code/rc_sync.sh:
    python3 code/rc_collect.py
Writes results-all-phases.csv and results-all-phases-summary.json.
"""
import collections
import csv
import datetime as dt
import gzip
import json
import math
import statistics
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMP = HERE.parent
OUT_DIR = Path(os.environ.get('RC_OUT', CAMP))   # release: rebuild beside, not over, the frozen file
PAPER = CAMP.parents[1] / 'analysis' / 'reference' / 'derived'  # the release's historical outputs
sys.path.insert(0, str(HERE))
import rc_analyze as R  # noqa: E402

DBMS = ('oracle', 'mysql', 'postgresql', 'commercial_a')        # phase A order on the host
SCHEMAS = ('non-indexed', 'indexed')
FWS = ('django', 'sqlalchemy')
SUBSET = (6, 17, 18, 20, 21)                                 # phases G, D, E
HOST_CENSORED_SF1 = {('postgresql', 'non-indexed'): {17, 20, 21}, ('mysql', 'non-indexed'): {17, 20}}
SCOPE_RULE = 'evidence/G-scope-change-20261008.json'
TX = ('T1', 'T2', 'T3', 'T4', 'T5')
COLS = ['phase', 'scale', 'dbms', 'schema', 'query', 'framework', 'status', 'status_note', 'accepted_blocks',
        'acceptance', 'sql_s', 'orm_s', 'added_ms', 'overhead_pct', 'paper_overhead_pct', 'paper_sql_s', 'paper_orm_s',
        'host_overhead_pct', 'mac_vs_host_ratio', 'sf1_overhead_pct', 'generated_s', 'bound_s', 'orm_vs_generated_pct',
        'generated_vs_bound_pct', 'bound_vs_literal_pct', 'evidence']


def f(x, n=4):
    return '' if x is None else (f'{x:.{n}f}' if isinstance(x, float) else str(x))


def paper_cells():
    out = {}
    for r in csv.DictReader(open(PAPER / 'cells.csv')):
        out[(r['system'], r['schema'], int(r['query'][1:]), r['framework'])] = r
    return out


def paper_tpcc():
    return {(r['system'], r['schema'], r['transaction'], r['framework']): r
            for r in csv.DictReader(open(PAPER / 'tpcc_cells.csv'))}


def load(run_dir):
    """cell results, coverage and run parameters of one run directory, or None"""
    if not (run_dir / 'run-parameters.json').exists():
        return None
    R.path_cvs, R.censored_cells = [], []
    cells, cov, numeric = R.load_run(run_dir)
    params = json.loads((run_dir / 'run-parameters.json').read_text())
    return ({(c['query'], c['framework']): c for c in cells}, {(c['query'], c['framework']): c for c in cov},
            {(c['query'], c['framework']): c for c in numeric}, params)


def cell_row(phase, scale, e, s, q, fw, run_dir, run, not_started_note):
    row = {'phase': phase, 'scale': scale, 'dbms': e, 'schema': s, 'query': f'Q{q:02d}', 'framework': fw,
           'evidence': str(run_dir.relative_to(CAMP) / f'q{q:02d}')}
    if run is None:
        return {**row, 'status': 'pending', 'status_note': not_started_note, 'evidence': ''}
    cells, cov, numeric, params = run
    if q not in params.get('queries', []):
        return {**row, 'status': 'not_in_run', 'status_note': f'not in the query list of {run_dir.relative_to(CAMP)}'}
    cdir = run_dir / f'q{q:02d}'
    if not cdir.exists():
        order = params['queries']
        return {**row, 'status': 'pending', 'evidence': '',
                'status_note': f'run in progress; this query is {order.index(q) + 1} of {len(order)} in its order'}
    c, v = cells.get((q, fw)), cov.get((q, fw))
    done = (cdir / 'cell-done.json').exists()
    if not done:
        return {**row, 'status': 'running', 'accepted_blocks': v['accepted_blocks'] if v else '',
                'status_note': 'being measured now' + (f" ({v['accepted_blocks']}/8 blocks accepted so far)" if v else '')}
    row['accepted_blocks'] = v['accepted_blocks']
    row['acceptance'] = ';'.join(f'{k}={n}' for k, n in sorted(v['acceptance_classes'].items()))
    if c:
        return {**row, 'status': 'measured', 'status_note': 'all 8 blocks accepted', 'sql_s': c['sql_s'],
                'orm_s': c['orm_s'], 'added_ms': c['added_ms'], 'overhead_pct': c['overhead_pct'], '_theta': c['theta']}
    if (q, fw) in numeric:
        n = numeric[(q, fw)]
        return {**row, 'status': 'numeric_mismatch', 'overhead_pct': n['overhead_pct'],
                'status_note': 'results differ only numerically (policy v3 numeric_mismatch): timed, not accepted; '
                               'overhead shown is the sensitivity value over all 8 blocks'}
    arms = v['arms_not_run']
    if v['status'] == 'not_expressible':
        return {**row, 'status': 'not_expressible', 'status_note': 'the ORM cannot express this query: ' + ', '.join(arms)}
    if v['status'] == 'censored':
        return {**row, 'status': 'censored', 'status_note': 'exceeded the 900 s limit at the cell warm-up on '
                + ', '.join(sorted(arms)) + '; no ratio exists (phase B bounds it where one path completes)'}
    bs = v['block_statuses']
    nr = cdir / 'needs-review.json'
    if nr.exists() and not any(k in bs for k in ('mismatch', 'schema_error')):
        # this framework was accepted in every decided block; the cell stopped
        # because the other framework's result differed (a cell is one block
        # design for both frameworks)
        other = json.loads(nr.read_text())
        why = {k: x.get('classification') for k, x in (other.get('frameworks') or {}).items() if k != fw}
        return {**row, 'status': v['status'], 'status_note':
                f"blocks: {bs}; every decided block accepted; the cell stopped at block {other.get('block')} "
                f"(input {other.get('input_id')}) because the other framework's result was {why}"}
    return {**row, 'status': v['status'], 'status_note': f"blocks: {bs}; needs review"}


def october(run_dir):
    """The October four-path diagnostics (R1-4), reused by the campaign: per
    query, blocks 0-7 on inputs s0-s7 (block -1 is the warm-up), paths orm / generated / bound /
    literal. Same paired estimand as everywhere: median over blocks of the log
    ratio. Acceptance comes from the run's own completion verification."""
    import glob
    import statistics as st
    ver = json.loads((run_dir / 'completion-verification.json').read_text())
    by = collections.defaultdict(dict)
    for f in glob.glob(str(run_dir / 'q*-block*-*.json')):
        r = json.loads(Path(f).read_text())
        if int(r['block']) < 0 or r.get('status') != 'ok':      # block -1 is the warm-up; 0-7 are timed
            continue
        el = r['elapsed_s']
        by[(int(r['query']), int(r['block']))][r['path']] = float(el['value']) if isinstance(el, dict) else float(el)
    out = {}
    for q in sorted({q for q, _ in by}):
        blocks = [v for (qq, _), v in by.items() if qq == q and len(v) == 4]
        def med(path): return st.median(b[path] for b in blocks)
        def ratio(a, b): return 100 * math.expm1(st.median(math.log(x[a] / x[b]) for x in blocks))
        out[q] = {'blocks': len(blocks), 'orm_s': med('orm'), 'generated_s': med('generated'), 'bound_s': med('bound'),
                  'literal_s': med('literal'), 'overhead_pct': ratio('orm', 'literal'),
                  'orm_vs_generated_pct': ratio('orm', 'generated'), 'generated_vs_bound_pct': ratio('generated', 'bound'),
                  'bound_vs_literal_pct': ratio('bound', 'literal'),
                  'accepted': f"{ver.get('timed_executions_accepted')}/{ver.get('timed_executions_completed')} timed executions accepted "
                              f"(exact named, ordered result checks; completion-verification.json)"}
    return out


def add_paper(row, pc, e, s, q, fw):
    p = pc.get((e, s, q, fw))
    if p:
        row.update(paper_overhead_pct=float(p['overhead']), paper_sql_s=float(p['sql_s']), paper_orm_s=float(p['orm_s']))
    else:
        row['paper_overhead_pct'] = 'none (censored or inexpressible in the paper)'
    return row


def main():
    pc, pt = paper_cells(), paper_tpcc()
    rows = []
    # phase A: SF1 grid on the host
    a_runs = {}
    for e in DBMS:
        for s in SCHEMAS:
            d = CAMP / 'A-sf1' / f'{e}-{s}'
            a_runs[(e, s)] = load(d)
            for q in range(1, 23):
                for fw in FWS:
                    rows.append(add_paper(cell_row('A', 1, e, s, q, fw, d, a_runs[(e, s)],
                                                   'phase A not reached yet (host order: Oracle, MySQL, PostgreSQL, Commercial System A; '
                                                   'non-indexed then indexed)'), pc, e, s, q, fw))
    a_index = {(r['dbms'], r['schema'], r['query'], r['framework']): r for r in rows}
    # phase G: second server (Mac), SF1 subset
    for e in DBMS:
        for s in SCHEMAS:
            d = CAMP / 'G-mac-server' / 'v2' / f'{e}-{s}'
            run = load(d)
            for q in SUBSET:
                for fw in FWS:
                    if q in HOST_CENSORED_SF1.get((e, s), set()):
                        rows.append({'phase': 'G', 'scale': 1, 'dbms': e, 'schema': s, 'query': f'Q{q:02d}', 'framework': fw,
                                     'status': 'skipped_censored_on_host', 'evidence': SCOPE_RULE,
                                     'status_note': 'skipped: already over the 900 s limit on the host at SF1 (all paths), so no host ratio to compare with'})
                        continue
                    r = add_paper(cell_row('G', 1, e, s, q, fw, d, run, 'phase G not started'), pc, e, s, q, fw)
                    h = a_index.get((e, s, f'Q{q:02d}', fw))
                    if h and h['status'] == 'measured':
                        r['host_overhead_pct'] = h['overhead_pct']
                        if r.get('_theta') is not None:
                            r['mac_vs_host_ratio'] = math.exp(r['_theta'] - h['_theta'])
                    elif r['status'] == 'measured':
                        r['host_overhead_pct'] = 'host phase A cell not measured yet'
                    rows.append(r)
    # phases D (SF2, host) and E (Mac client over Wi-Fi), same subset
    for ph, root, scale, note in (('D', 'D-sf2', 2, 'phase D: after phase A, in the per-engine visit (Commercial System A first)'),
                                  ('E', 'E-client', 1, 'phase E: last, Mac as client over Wi-Fi with desktop-app closed')):
        for e in DBMS:
            for s in SCHEMAS:
                d = CAMP / root / f'{e}-{s}'
                superseded = ''
                if (ph, e, s) == ('E', 'commercial_a', 'non-indexed') and (CAMP / root / f'{e}-{s}-r2').exists():
                    # the first run followed E's 2.5 h indexed workload on the same
                    # instance: lock-manager memory shrank the buffer pool and the
                    # full scans read from disk (reproduced, evidence/commercial_a-repro/);
                    # re-measured on a freshly started engine, as phase A
                    d, superseded = CAMP / root / f'{e}-{s}-r2', ('re-measured on a freshly started engine (E-client/commercial_a-non-indexed-r2); '
                                                                 'the first run (E-client/commercial_a-non-indexed, memory-starved buffer pool) is kept, superseded; ')
                run = load(d)
                for q in SUBSET:
                    for fw in FWS:
                        if q in HOST_CENSORED_SF1.get((e, s), set()):
                            rows.append({'phase': ph, 'scale': scale, 'dbms': e, 'schema': s, 'query': f'Q{q:02d}',
                                         'framework': fw, 'status': 'skipped_censored_on_host', 'evidence': SCOPE_RULE,
                                         'status_note': 'skipped: already over the 900 s limit on the host at SF1 (all paths); a larger scale or a remote client cannot bring it under'})
                        else:
                            r = cell_row(ph, scale, e, s, q, fw, d, run, note)
                            if superseded:
                                r['status_note'] = superseded + r['status_note']
                            # the same cell at SF1 on the host (phase A): the scale
                            # comparison for D, the same-host control for E
                            h = a_index.get((e, s, f'Q{q:02d}', fw))
                            r['sf1_overhead_pct'] = (h['overhead_pct'] if h and h['status'] == 'measured'
                                                     else (h['status'] if h else ''))
                            rows.append(add_paper(r, pc, e, s, q, fw) if ph == 'E' else r)
    # phase V: result validation of the 12 censored framework cells (R1-2), Mac, no 900 s ceiling
    bind = CAMP / 'evidence' / 'V-binding.json'
    twins = {r['cell']: r for r in json.loads(bind.read_text())['indexed_twin']} if bind.exists() else {}
    for e, qs in (('postgresql', {13: ('django',), 17: FWS, 20: FWS, 21: FWS}), ('mysql', {13: ('django',), 17: FWS, 20: FWS})):
        d = CAMP / 'V-censored' / 'v2' / f'{e}-non-indexed'
        for q, fws in qs.items():
            vf = d / f'q{q:02d}' / 'validation.json'
            for fw in fws:
                row = {'phase': 'V', 'scale': 1, 'dbms': e, 'schema': 'non-indexed', 'query': f'Q{q:02d}', 'framework': fw}
                twin = twins.get(f'{e}/non-indexed/q{q:02d}/{fw}', {})
                if vf.exists() and json.loads(vf.read_text())['verdicts'][fw]['validated']:
                    v = json.loads(vf.read_text())
                    row.update(status='validated', status_note='Mac, 239-min ceiling (V-v2, 14340 s), not the 900 s one: ' + v['verdicts'][fw]['reason'],
                               evidence=str(vf.relative_to(CAMP)))
                elif twin.get('binding') == 'validated_by_twin':
                    row.update(status='validated_by_twin', evidence='evidence/V-binding.json',
                               status_note=('host: byte-identical statements to the indexed twin on the same input and data; '
                                            f"twin result {twin.get('twin_classification')}" +
                                            ('; Mac run hit the 239-min cap' if vf.exists() else '')))
                elif vf.exists():
                    v = json.loads(vf.read_text())
                    row.update(status='not_validated', status_note=v['verdicts'][fw]['reason'] + '; indexed-twin check pending',
                               evidence=str(vf.relative_to(CAMP)))
                elif (d / f'q{q:02d}').exists():
                    row.update(status='running', status_note='validation executing (239 min cap per call)', evidence='')
                else:
                    row.update(status='pending', status_note='validation queued (PostgreSQL first, then MySQL)', evidence='')
                if vf.exists():
                    # single executions on the Mac, recorded for reference only:
                    # not measurements under the eight-block design, never overheads
                    v = json.loads(vf.read_text())
                    el = {k: (float(x['value']) if isinstance(x, dict) else float(x)) for k, x in v['elapsed_s'].items()}
                    st_ = v['statuses']
                    row['sql_s'] = el[f'{fw}/sql']
                    row['orm_s'] = el[f'{fw}/orm']
                    row['status_note'] += (f"; Mac single executions (not measurements): {fw}/sql {el[f'{fw}/sql']:.1f} s "
                                           f"({st_[f'{fw}/sql']}), {fw}/orm {el[f'{fw}/orm']:.1f} s ({st_[f'{fw}/orm']})")
                rows.append(row)
    # phase C: transactions (C-tpcc/<dbms>-<schema>/T<n>/bNN/decision.json, 24 blocks)
    for e in DBMS:
        for s in SCHEMAS:
            d = CAMP / 'C-tpcc' / f'{e}-{s}'
            superseded = ''
            if (e, s) == ('oracle', 'non-indexed'):
                # the first run overlapped the after-phase-F vault snapshot
                # (104 of 120 blocks, 21:51:59-21:56:50 Cairo); plan visits3b
                # measures it again alone in -r2 (decision log, 2026-10-10)
                r2 = CAMP / 'C-tpcc' / 'oracle-non-indexed-r2'
                if r2.exists():
                    d, superseded = r2, 'C-tpcc/oracle-non-indexed (overlapped the vault snapshot) kept, superseded; '
                else:
                    superseded = 'PENDING RE-MEASUREMENT (plan visits3b): this run overlapped the vault snapshot; '
            done_run = (d / 'completion.json').exists()
            for t in TX:
                for fw in FWS:
                    p = pt.get((e, s, t, fw))
                    row = {'phase': 'C', 'scale': '', 'dbms': e, 'schema': s, 'query': t, 'framework': fw,
                           'paper_overhead_pct': float(p['overhead']) if p else 'none',
                           'paper_sql_s': float(p['sql_ms']) / 1000 if p else '',
                           'paper_orm_s': float(p['orm_ms']) / 1000 if p else ''}
                    tdir = d / t
                    if not tdir.exists():
                        row.update(status='pending', evidence='', status_note=(
                            'phase C run in progress; this transaction not reached yet' if d.exists() else
                            'phase C: in this engine\'s visit, from src-c (both baseline corrections applied)'))
                        rows.append(row)
                        continue
                    decided, ratios, sql_t, orm_t, classes, rejects = 0, [], [], [], collections.Counter(), collections.Counter()
                    for dec_f in sorted(tdir.glob('b[0-9][0-9]/decision.json')):
                        dec = json.loads(dec_f.read_text())
                        fd = dec['frameworks'].get(fw, {})
                        decided += 1
                        if fd.get('accepted'):
                            classes[fd.get('classification')] += 1
                            att = sorted(dec_f.parent.glob('a*'))[-1]
                            def el(path):
                                r = json.load(gzip.open(att / f'timed-{fw}-{path}.json.gz'))
                                v = r['elapsed_s']
                                return float(v['value']) if isinstance(v, dict) else float(v)
                            sq, orm = el('sql'), el('orm')
                            sql_t.append(sq); orm_t.append(orm); ratios.append(math.log(orm / sq))
                        else:
                            rejects[fd.get('classification') or fd.get('status') or 'rejected'] += 1
                    planned = 24
                    row.update(evidence=str(tdir.relative_to(CAMP)), accepted_blocks=len(ratios),
                               acceptance=';'.join(f'{k}={n}' for k, n in sorted(classes.items())))
                    if ratios:
                        row.update(sql_s=statistics.median(sql_t), orm_s=statistics.median(orm_t),
                                   added_ms=1000 * (statistics.median(orm_t) - statistics.median(sql_t)),
                                   overhead_pct=100 * math.expm1(statistics.median(ratios)))
                    rej = ', '.join(f'{k} {n}' for k, n in rejects.items())
                    if decided >= planned and superseded.startswith('PENDING'):
                        row.update(status='pending_rerun', sql_s=None, orm_s=None, added_ms=None, overhead_pct=None,
                                   status_note=superseded + f'{len(ratios)}/{planned} blocks accepted in the overlapped run')
                    elif decided >= planned:
                        row.update(status='measured' if len(ratios) == planned else 'measured_with_rejections',
                                   status_note=superseded + f'{len(ratios)}/{planned} blocks accepted' + (f'; rejected: {rej}' if rej else ''))
                    else:
                        row.update(status='running', status_note=f'{decided}/{planned} blocks decided, {len(ratios)} accepted' +
                                   (f'; rejected: {rej}' if rej else '') + ('' if not done_run else '; run ended early'))
                    rows.append(row)
    # phase F: four-path decomposition (F-fourpath/<dbms>-<schema>-<framework>/qNN), the final
    # cell list once fixed (F-cells-final.json), else the paper's > +100 % cells
    final = CAMP / 'F-cells-final.json'
    fc_final = json.loads(final.read_text()) if final.exists() else None
    fc = json.loads((CAMP / 'F-cells-from-paper.json').read_text())
    groups = fc_final['groups'] if fc_final else fc['groups']
    reasons = fc_final['cells'] if fc_final else {}
    for g in groups:
        for q in g['queries']:
            e, s, fw = g['dbms'], g['schema'], g['framework']
            why = reasons.get(f'{e}/{s}/Q{q:02d}/{fw}', 'paper > +100 %')
            row = {'phase': 'F', 'scale': 1, 'dbms': e, 'schema': s, 'query': f'Q{q:02d}', 'framework': fw}
            # the newest protocol that has this cell: F-v3 (F-fourpath/v3), F-v2 (v2), F-v1
            tries = [(v, CAMP / 'F-fourpath' / sub / f'{e}-{s}-{fw}' / f'q{q:02d}')
                     for v, sub in (('F-v3', 'v3'), ('F-v2', 'v2'), ('F-v1', '.'))]
            proto, cdir = next(((v, d) for v, d in tries if d.exists()), tries[-1])
            older = [str(d.relative_to(CAMP)) for v, d in tries if d.exists() and d != cdir]
            if older:
                why += f"; {proto}; superseded runs kept: {', '.join(older)}"
            elif cdir.exists():
                why += f'; {proto}'
            done = cdir / 'cell-done.json'
            if proto == 'F-v1' and fw == 'django' and e == 'commercial_a' and cdir.exists():
                # F-v1's Django cells on Commercial System A are superseded: B bound dates
                # as datetime.date where the ORM binds strings, and plans of
                # DECLARE-form statements were taken in parameterised batch form
                # (F-v2 corrections 3 and 4); Q15 and Q22 could not complete
                row.update(status='pending_rerun', evidence=str(cdir.relative_to(CAMP)),
                           status_note=f'{why}; F-v1 run kept but superseded (F-v2 corrections 1-5); '
                                       're-measured under F-v2 in plan visits2')
                rows.append(add_paper(row, pc, e, s, q, fw))
                continue
            if done.exists() and json.loads(done.read_text()).get('status') == 'censored':
                cd = json.loads(done.read_text())
                row.update(status='censored', accepted_blocks=0, evidence=str(cdir.relative_to(CAMP)),
                           status_note=f"{why}; {'/'.join(cd['censored_paths'])} over {cd['limit_s']} s in the cell "
                                       f"warm-up, cell censored (F-v2 rule 5); warm-up times in b0")
            elif done.exists():
                cd = json.loads(done.read_text())
                pm = {k: (float(v['value']) if isinstance(v, dict) else float(v)) for k, v in (cd.get('paired_median') or {}).items()}
                times = collections.defaultdict(list)
                for dec_f in sorted(cdir.glob('b[1-9]*/decision.json')):
                    dec = json.loads(dec_f.read_text())
                    if not dec.get('accepted'):
                        continue
                    for path, rel in (dec.get('records') or {}).items():
                        r = json.load(gzip.open(dec_f.parent / rel))
                        v = r['elapsed_s']
                        times[path].append(float(v['value']) if isinstance(v, dict) else float(v))
                med = {k: statistics.median(v) for k, v in times.items() if v}
                row.update(status='measured' if pm else 'partial', accepted_blocks=cd.get('accepted_blocks'),
                           evidence=str(cdir.relative_to(CAMP)),
                           status_note=f"{why}; {cd.get('accepted_blocks')}/8 blocks accepted; sql_s = L (literal), orm_s = O",
                           sql_s=med.get('L'), orm_s=med.get('O'), generated_s=med.get('G'), bound_s=med.get('B'))
                if pm:
                    row.update(overhead_pct=100 * (pm['O/L'] - 1), orm_vs_generated_pct=100 * (pm['O/G'] - 1),
                               generated_vs_bound_pct=100 * (pm['G/B'] - 1), bound_vs_literal_pct=100 * (pm['B/L'] - 1),
                               added_ms=1000 * (med['O'] - med['L']) if 'O' in med and 'L' in med else None)
            elif cdir.exists():
                row.update(status='running', evidence=str(cdir.relative_to(CAMP)), status_note=f'{why}; being measured')
            else:
                row.update(status='pending', evidence='', status_note=f'{why}; phase F, four paths (O, G, B, L), in this engine\'s visit')
            rows.append(add_paper(row, pc, e, s, q, fw))
    oct_dirs = {('oracle', 'non-indexed'): 'oracle-clean-20261007-v2', ('commercial_a', 'indexed'): 'system-a-clean-20261007-v3'}
    oct_res = {k: october(CAMP.parent / d) for k, d in oct_dirs.items() if (CAMP.parent / d).exists()}
    for k in fc['reused_october']:
        e, s, q, fw = k.split('/')
        res = oct_res.get((e, s), {}).get(int(q[1:]))
        row = {'phase': 'F', 'scale': 1, 'dbms': e, 'schema': s, 'query': q, 'framework': fw,
               'evidence': f"../{oct_dirs.get((e, s), '?')}"}
        if res:
            row.update(status='measured', sql_s=res['literal_s'], orm_s=res['orm_s'], added_ms=1000 * (res['orm_s'] - res['literal_s']),
                       overhead_pct=res['overhead_pct'], accepted_blocks=res['blocks'], acceptance='exact',
                       generated_s=res['generated_s'], bound_s=res['bound_s'], orm_vs_generated_pct=res['orm_vs_generated_pct'],
                       generated_vs_bound_pct=res['generated_vs_bound_pct'], bound_vs_literal_pct=res['bound_vs_literal_pct'],
                       status_note='October four-path diagnostic, reused (R1-4): ' + res['accepted'] + '; sql_s = literal handwritten SQL')
        else:
            row.update(status='reused_october', status_note='October diagnostic records not found at ' + row['evidence'])
        rows.append(add_paper(row, pc, e, s, int(q[1:]), fw))
    # phase B: matched-input probes of the censored framework cells where the
    # other arm completes (B-censored/<dbms>-<schema>-<framework>/qNN); a lower
    # bound on ORM/SQL when the ORM arm runs past the limit
    for e, s, q, fw, arm in (('postgresql', 'non-indexed', 13, 'django', 'django/orm'),
                             ('mysql', 'non-indexed', 13, 'django', 'django/orm')):
        cdir = CAMP / 'B-censored' / f'{e}-{s}-{fw}' / f'q{q:02d}'
        row = {'phase': 'B', 'scale': 1, 'dbms': e, 'schema': s, 'query': f'Q{q:02d}', 'framework': fw}
        decs = [json.loads(f.read_text()) for f in sorted(cdir.glob('b[1-9]*/decision.json'))]
        sql = [float(d['sql_elapsed_s']['value']) if isinstance(d.get('sql_elapsed_s'), dict) else d.get('sql_elapsed_s')
               for d in decs if d.get('sql_elapsed_s') is not None]
        kinds = collections.Counter(d['kind'] for d in decs)
        if (cdir / 'cell-done.json').exists():
            cd = json.loads((cdir / 'cell-done.json').read_text())
            lo, hi = cd.get('median_ratio_at_least'), cd.get('median_ratio_at_most')
            lo = float(lo['value']) if isinstance(lo, dict) else lo
            hi = float(hi['value']) if isinstance(hi, dict) else hi
            row.update(status='lower_bound' if lo else 'upper_bound' if hi else 'no_bound',
                       accepted_blocks=len(decs), sql_s=statistics.median(sql) if sql else None,
                       overhead_pct=None, evidence=str(cdir.relative_to(CAMP)),
                       status_note=(f'{arm} censored at 900 s in phase A; 8 matched inputs, both arms: '
                                    + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items())) + '; '
                                    + (f'median ORM/SQL >= {lo:.1f}x (overhead >= {100 * (lo - 1):.0f} %)' if lo else
                                       f'median ORM/SQL <= {hi:.2f}x' if hi else 'no bound identifiable')))
        elif cdir.exists():
            row.update(status='running', accepted_blocks=len(decs), evidence=str(cdir.relative_to(CAMP)),
                       status_note=f'{arm} censored in phase A; matched-input probes running: {len(decs)}/8 inputs decided ('
                                   + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items())) + ')')
        else:
            row.update(status='pending', evidence='', status_note=f'{arm} censored in phase A; probes in the {e} visit')
        rows.append(add_paper(row, pc, e, s, q, fw))
    for r in rows:
        r.pop('_theta', None)
        r.setdefault('status_note', '')
    for r in rows:
        assert r['status'] and r['status_note'], r      # a row without a status or a reason is a bug
    with open(OUT_DIR / 'results-all-phases.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: f(r.get(k)) if isinstance(r.get(k), float) else r.get(k, '') for k in COLS})
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[r['phase']][r['status']] += 1
    summary = {'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'rows': len(rows),
               'by_phase': {p: dict(c) for p, c in by.items()},
               'not_yet_listed': [],
               'note': 'generated by code/rc_collect.py from the synced campaign records; never hand-edit'}
    (OUT_DIR / 'results-all-phases-summary.json').write_text(json.dumps(summary, indent=1) + '\n')
    print(f"{len(rows)} rows -> results-all-phases.csv")
    for p, c in by.items():
        print(f"  {p}: " + ', '.join(f'{k} {n}' for k, n in sorted(c.items())))


if __name__ == '__main__':
    main()
