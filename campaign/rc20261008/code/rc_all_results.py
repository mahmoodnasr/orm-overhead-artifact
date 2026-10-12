#!/usr/bin/env python3
"""all_results-rc20261008.csv: this campaign in the layout of the repository's
results/all_results.csv (same 48 columns, same order, same value vocabulary).

The repository file is not read, written or replaced; this is a new file in the
campaign directory. One row per (campaign, dbms, schema, query, framework),
every row always emitted - a cell without a measurement says why in
status_note. campaign_id tells the phases apart: rc20261008-A-sf1-host (the
SF1 grid, 352 rows), -C-tpcc-host (80), -G-sf1-mac (second server, 80),
-D-sf2-host (80), -E-sf1-mac-client (80). Phase F (four access paths per cell)
does not fit two-path columns and stays in results-all-phases.csv.

Differences from the repository file, stated in the columns themselves:
  overhead_ratio / overhead_percentage are the paper's paired estimand,
  exp(theta) and 100*(exp(theta)-1), theta = median over the 8 blocks of
  log(t_orm/t_sql); direct_sql_execution_s / total_orm_execution_s are the
  medians of the 8 timed executions; min/max/CV are over those 8, which use
  8 different TPC-H inputs, so CV includes input variation. Plans and q-error
  are not measured in these phases (phase F captures plans).

Generated, never hand-edited. Run on the Mac after code/rc_sync.sh:
    python3 code/rc_all_results.py
"""
import csv
import gzip
import json
import os
import math
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMP = HERE.parent
OUT_DIR = Path(os.environ.get('RC_OUT', CAMP))   # release: rebuild beside, not over, the frozen file
sys.path.insert(0, str(HERE))
import rc_analyze as R  # noqa: E402

COLS = ['benchmark', 'orm', 'orm_version', 'query_id', 'query_name', 'complexity_band', 'dbms', 'dbms_version',
        'schema_config', 'scale_factor', 'dataset_size_gb', 'direct_sql_execution_s', 'total_orm_execution_s',
        'overhead_ratio', 'overhead_percentage', 'overhead_abs_s', 'rows_returned', 'sql_min_s', 'sql_max_s',
        'sql_cv_pct', 'orm_min_s', 'orm_max_s', 'orm_cv_pct', 'repetitions_measured', 'sql_status', 'orm_status',
        'status_note', 'orm_plan_operators', 'orm_median_qerror', 'orm_max_qerror', 'orm_operators_qerror_gt_10',
        'orm_underestimate_rate_pct', 'sql_plan_operators', 'sql_median_qerror', 'sql_max_qerror',
        'sql_operators_qerror_gt_10', 'sql_underestimate_rate_pct', 'orm_plan_file', 'sql_plan_file',
        'validated_orm_path_is_orm', 'validated_results_match', 'validated_baselines_match',
        'validated_orm_equals_sql', 'validated_rows_nonzero', 'validation_source', 'timing_method', 'aggregation',
        'campaign_id']
# Query names and complexity bands exactly as in the repository's all_results.csv
TPCH = {1: ('Pricing Summary Report', 'Medium'), 2: ('Minimum Cost Supplier', 'Complex'),
        3: ('Shipping Priority', 'Medium'), 4: ('Order Priority Checking', 'Medium'),
        5: ('Local Supplier Volume', 'Complex'), 6: ('Forecasting Revenue Change', 'Simple'),
        7: ('Volume Shipping', 'Complex'), 8: ('National Market Share', 'Very Complex'),
        9: ('Product Type Profit Measure', 'Very Complex'), 10: ('Returned Item Reporting', 'Complex'),
        11: ('Important Stock Identification', 'Medium'), 12: ('Shipping Modes and Order Priority', 'Medium'),
        13: ('Customer Distribution', 'Complex'), 14: ('Promotion Effect', 'Simple'), 15: ('Top Supplier', 'Complex'),
        16: ('Parts/Supplier Relationship', 'Medium'), 17: ('Small-Quantity-Order Revenue', 'Complex'),
        18: ('Large Volume Customer', 'Complex'), 19: ('Discounted Revenue', 'Simple'),
        20: ('Potential Part Promotion', 'Complex'), 21: ('Suppliers Who Kept Orders Waiting', 'Very Complex'),
        22: ('Global Sales Opportunity', 'Very Complex')}
TPCC = {'T1': ('New-Order', 'Write-heavy'), 'T2': ('Payment', 'Write-heavy'), 'T3': ('Order-Status', 'Read-only'),
        'T4': ('Delivery', 'Write-heavy'), 'T5': ('Stock-Level', 'Read-only')}
DBMS = {'postgresql': 'PostgreSQL', 'mysql': 'MySQL', 'commercial_a': 'Commercial System A', 'oracle': 'Oracle'}
SCHEMA = {'indexed': 'Indexed', 'non-indexed': 'Non-Indexed'}
FW = {'django': 'DJANGO', 'sqlalchemy': 'SQLALCHEMY'}
SUBSET = (6, 17, 18, 20, 21)
HOST_CENSORED_SF1 = {('postgresql', 'non-indexed'): {17, 20, 21}, ('mysql', 'non-indexed'): {17, 20}}
NOT_MEASURED = 'not measured in this phase'
TIMING = 'time.perf_counter, client-side end-to-end (query-module call, all rows fetched)'
AGG = ('paired: overhead = exp(median over 8 blocks of log(t_orm/t_sql)); path times = median of the 8 timed '
       'executions; 8 blocks = 8 TPC-H inputs in Williams order, one warm-up sequence per cell and per block')
SOURCES = {}


def versions(e):
    """server and package versions from the first run of this engine with an inventory (host or Mac)"""
    if e in SOURCES:
        return SOURCES[e]
    out = {'dbms_version': 'not recorded yet (no run of this engine)', 'django': '6.0.8', 'sqlalchemy': '2.0.52'}
    for inv in sorted(CAMP.glob(f'A-sf1/{e}-*/inventory-before-*.json')) + sorted(CAMP.glob(f'G-mac-server/v2/{e}-*/inventory-before-*.json')) \
            + sorted(CAMP.glob(f'pilot/{e}-*/inventory-before-*.json')):
        d = json.loads(inv.read_text())
        srv = (d.get('server') or [{}])[0] if isinstance(d.get('server'), list) else {}
        v = srv.get('product_version') or srv.get('version') or srv.get('banner_full', '')
        if e == 'oracle':
            v = '23ai Free ' + v.split('Version')[-1].strip()
        elif e == 'postgresql':
            v = v.split(' on ')[0].replace('PostgreSQL ', '')
        elif e == 'commercial_a':
            v = 'withheld'                 # the release does not carry this system's version
        out = {'dbms_version': v, 'django': d['packages']['Django'], 'sqlalchemy': d['packages']['SQLAlchemy']}
        break
    SOURCES[e] = out
    return out


def block_detail(cdir, fw):
    """per-block timings and checks for one framework of one cell"""
    sql_t, orm_t, rows, checks = [], [], set(), {'orm?': [], 'match': [], 'sql=': [], 'orm=sql': [], 'rows>0': []}
    for b in range(1, 9):
        p = cdir / f'b{b}' / 'decision.json'
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        ct = d['comparisons_timed']
        own = ct.get(fw, {})

        def acc(cmp):
            # 'unavailable': one side never ran (e.g. Django Q13 ORM, C17) -
            # nothing was compared, which is not_checked, not a failure
            return None if not cmp or cmp.get('classification') == 'unavailable' else cmp.get('accepted')
        checks['orm?'].append((own.get('orm_path_check') or {}).get('passed'))
        checks['match'].append(acc(ct.get('cross_orm')))
        checks['sql='].append(acc(ct.get('cross_sql')))
        checks['orm=sql'].append(acc(own))
        if own.get('rows'):
            rows.add(own['rows'][1])
            checks['rows>0'].append(own['rows'][1] > 0)
        if d['frameworks'][fw].get('accepted'):
            for path, lst in ((f'{fw}/sql', sql_t), (f'{fw}/orm', orm_t)):
                r = json.load(gzip.open(p.parent / d['timed_records'][path]))
                lst.append(float(r['elapsed_s']['value']))
    return sql_t, orm_t, rows, checks


def verdict(vals):
    known = [v for v in vals if v is not None]
    if not known:
        return 'not_checked'
    bad = sum(1 for v in known if not v)
    return 'pass' if not bad and len(known) == 8 else (f'fail ({bad}/{len(known)} blocks)' if bad else f'pass ({len(known)}/8 blocks)')


def base(bench, e, s, scale, qid, fw, campaign):
    v = versions(e)
    name, band = (TPCH[int(qid[1:])] if bench == 'tpch' else TPCC[qid])
    row = {c: NOT_MEASURED for c in COLS[27:39]}
    row.update(benchmark=bench, orm=FW[fw], orm_version=v[fw] if fw in v else v['django' if fw == 'django' else 'sqlalchemy'],
               query_id=qid, query_name=name, complexity_band=band, dbms=DBMS[e], dbms_version=v['dbms_version'],
               schema_config=SCHEMA[s], scale_factor=scale,
               dataset_size_gb=(f'not recorded; TPC-H SF{scale} content-verified' if bench == 'tpch'
                                else 'not recorded; TPC-C 10 warehouses (tpcc_config.py)'),
               timing_method=TIMING, aggregation=AGG, campaign_id=campaign)
    return row


def not_run(row, note):
    for c in ('direct_sql_execution_s', 'total_orm_execution_s', 'overhead_ratio', 'overhead_percentage', 'overhead_abs_s',
              'rows_returned', 'sql_min_s', 'sql_max_s', 'sql_cv_pct', 'orm_min_s', 'orm_max_s', 'orm_cv_pct'):
        row[c] = 'not_run'
    for c in COLS[39:44]:
        row[c] = 'not_checked'
    row.update(repetitions_measured=0, sql_status='not_run', orm_status='not_run', status_note=note,
               validation_source='none (not run)')
    return row


def cell(e, s, scale, q, fw, run_dir, loaded, campaign, pending_note):
    row = base('tpch', e, s, scale, f'Q{q:02d}', fw, campaign)
    if loaded is None:
        return not_run(row, pending_note)
    cells, cov, numeric, params = loaded
    cdir = run_dir / f'q{q:02d}'
    if not cdir.exists():
        return not_run(row, f'run in progress; query {params["queries"].index(q) + 1} of {len(params["queries"])} in its order')
    if not (cdir / 'cell-done.json').exists():
        return not_run(row, 'being measured now')
    sql_t, orm_t, rows, checks = block_detail(cdir, fw)
    row.update({f'validated_{k}': verdict(checks[c]) for k, c in (
        ('orm_path_is_orm', 'orm?'), ('results_match', 'match'), ('baselines_match', 'sql='),
        ('orm_equals_sql', 'orm=sql'), ('rows_nonzero', 'rows>0'))})
    row['validation_source'] = (f'results captured from the timed executions, checked per block '
                                f'(policy rc20261008-results-v3): {cdir.relative_to(CAMP)}/b*/decision.json')
    v, c = cov[(q, fw)], cells.get((q, fw))
    arms = v['arms_not_run']
    row['sql_status'] = 'timeout' if arms.get(f'{fw}/sql') == 'censored' else 'ok'
    row['orm_status'] = {'censored': 'timeout', 'not_expressible': 'error'}.get(arms.get(f'{fw}/orm'), 'ok')
    row['repetitions_measured'] = len(sql_t)
    row['rows_returned'] = (str(min(rows)) if len(rows) == 1 else f'{min(rows)}-{max(rows)} (varies by input)') if rows else 'not_run'

    def spread(ts):
        return (min(ts), max(ts), 100 * st.stdev(ts) / st.mean(ts)) if len(ts) >= 2 else ('not_run',) * 3
    if c:
        row.update(direct_sql_execution_s=round(c['sql_s'], 4), total_orm_execution_s=round(c['orm_s'], 4),
                   overhead_ratio=round(math.exp(c['theta']), 4), overhead_percentage=round(c['overhead_pct'], 2),
                   overhead_abs_s=round(c['orm_s'] - c['sql_s'], 4), status_note='')
        (a, b, cv), (d, e2, cv2) = spread(sql_t), spread(orm_t)
        row.update(sql_min_s=round(a, 4), sql_max_s=round(b, 4), sql_cv_pct=round(cv, 1),
                   orm_min_s=round(d, 4), orm_max_s=round(e2, 4), orm_cv_pct=round(cv2, 1))
        return row
    for k in ('direct_sql_execution_s', 'total_orm_execution_s', 'overhead_ratio', 'overhead_percentage', 'overhead_abs_s',
              'sql_min_s', 'sql_max_s', 'sql_cv_pct', 'orm_min_s', 'orm_max_s', 'orm_cv_pct'):
        row[k] = 'not_run'
    if (q, fw) in numeric:
        n = numeric[(q, fw)]
        row['overhead_percentage'] = round(n['overhead_pct'], 2)
        row['status_note'] = ('results differ only numerically (numeric_mismatch): timed, not accepted; '
                              'overhead_percentage is the sensitivity value over all 8 blocks')
    elif v['status'] == 'not_expressible':
        row['status_note'] = 'the ORM cannot express this query (C17): ' + ', '.join(arms)
    elif v['status'] == 'censored':
        row['status_note'] = ('exceeded the 900 s limit at the cell warm-up on ' + ', '.join(sorted(arms))
                              + '; no ratio exists (phase B bounds it where one path completes)')
    else:
        row['status_note'] = f"{v['status']}: blocks {v['block_statuses']}; needs review"
    return row


def load(run_dir):
    if not (run_dir / 'run-parameters.json').exists():
        return None
    R.path_cvs, R.censored_cells = [], []
    cells, cov, numeric = R.load_run(run_dir)
    return ({(c['query'], c['framework']): c for c in cells}, {(c['query'], c['framework']): c for c in cov},
            {(c['query'], c['framework']): c for c in numeric}, json.loads((run_dir / 'run-parameters.json').read_text()))


def main():
    rows = []
    order = ('postgresql', 'mysql', 'commercial_a', 'oracle')
    # A: the SF1 grid on the benchmark host
    for e in order:
        for s in ('indexed', 'non-indexed'):
            d = CAMP / 'A-sf1' / f'{e}-{s}'
            ld = load(d)
            for q in range(1, 23):
                for fw in ('django', 'sqlalchemy'):
                    rows.append(cell(e, s, 1, q, fw, d, ld, 'rc20261008-A-sf1-host',
                                     'phase A not reached yet (host order: Oracle, MySQL, PostgreSQL, Commercial System A)'))
    # C: transactions on the host
    for e in order:
        for s in ('indexed', 'non-indexed'):
            for t in TPCC:
                for fw in ('django', 'sqlalchemy'):
                    started = (CAMP / 'C-tpcc' / f'{e}-{s}').exists()
                    rows.append(not_run(base('tpcc', e, s, 10, t, fw, 'rc20261008-C-tpcc-host'),
                                        f'phase C started: see C-tpcc/{e}-{s} (rows not yet tabulated here)' if started else
                                        'phase C not started (after phase A; from src-c with both baseline corrections)'))
    # G, D, E: the Q6/Q17/Q18/Q20/Q21 subset
    for campaign, root, scale, pending in (
            ('rc20261008-G-sf1-mac', 'G-mac-server/v2', 1, 'phase G not started'),
            ('rc20261008-D-sf2-host', 'D-sf2', 2, 'phase D not started (after phase A, per-engine visit)'),
            ('rc20261008-E-sf1-mac-client', 'E-client', 1, 'phase E not started (last; Mac as client over Wi-Fi)')):
        for e in order:
            for s in ('indexed', 'non-indexed'):
                d = CAMP / root / f'{e}-{s}'
                ld = load(d)
                for q in SUBSET:
                    for fw in ('django', 'sqlalchemy'):
                        if q in HOST_CENSORED_SF1.get((e, s), set()):
                            rows.append(not_run(base('tpch', e, s, scale, f'Q{q:02d}', fw, campaign),
                                                'skipped: already over the 900 s limit on the host at SF1 (all paths), so no '
                                                'ratio to compare (evidence/G-scope-change-20261008.json)'))
                        else:
                            rows.append(cell(e, s, scale, q, fw, d, ld, campaign, pending))
    for r in rows:
        blank = [c for c in COLS if r.get(c) in (None, '') and not (c == 'status_note' and r['sql_status'] == r['orm_status'] == 'ok')
]
        assert not blank, (r['campaign_id'], r['dbms'], r['query_id'], r['orm'], blank)   # a blank cell is a bug
    out = OUT_DIR / 'all_results.csv'
    with open(out, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    import collections
    cnt = collections.Counter((r['campaign_id'], r['sql_status'] + '/' + r['orm_status']) for r in rows)
    print(out.name, len(rows), 'rows')
    for k, n in sorted(cnt.items()):
        print(f'  {k[0]:30s} {k[1]:20s} {n}')


if __name__ == '__main__':
    main()
