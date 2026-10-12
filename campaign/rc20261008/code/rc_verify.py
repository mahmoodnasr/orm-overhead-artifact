#!/usr/bin/env python3
"""Offline re-verification of an analytical run directory. No database access.

Re-reads every immutable record, recomputes every comparison and acceptance
from the saved results, and checks the bookkeeping the runner claimed:
  * each record's result hash matches its saved rows;
  * each record names a protocol, environment and run that exist;
  * each decision references timed records of its own attempt, and its
    classifications and acceptance reproduce exactly from the saved rows;
  * no block has more than one decision; no timed record is accepted unless a
    decision accepts it; attempts without a decision are counted as incomplete;
  * the Williams plan is reproducible from its seed text and balanced.
Writes verification-<utc>.json in the run directory and prints a summary.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402


def verify(run_dir, campaign_dir):
    run_dir = Path(run_dir)
    params = json.loads((run_dir / 'run-parameters.json').read_text())
    proto_path = Path(campaign_dir) / 'protocols' / f"{params['protocol_id']}.json"
    proto_sha = C.file_sha256(proto_path)
    problems = []
    if proto_sha != params['protocol_sha256']:
        problems.append('protocol file hash differs from run-parameters')
    envs = {}
    for f in run_dir.glob('inventory-*.json'):
        inv = C.load(f)
        if inv.get('environment_id'):
            envs.setdefault(inv['environment_id'], []).append(f.name)
    counts = Counter()
    cells = {}
    ratios = defaultdict(list)
    for cdir in sorted(run_dir.glob('q[0-9][0-9]')):
        q = int(cdir.name[1:])
        cell = {'blocks': {}, 'incomplete_attempts': 0}
        plan = json.loads((cdir / 'plan.json').read_text()) if (cdir / 'plan.json').exists() else None
        if plan:
            seed, seqs = C.block_plan(f"{params['protocol_id']}:{params['dbms']}:{params['schema']}:"
                                      f"sf{params['scale']}:{params['database_label']}:q{q}")
            if seed != plan['seed'] or seqs[:len(plan['block_sequences'])] != plan['block_sequences']:
                problems.append(f'Q{q}: plan not reproducible from its seed text')
        # every record
        for f in sorted(cdir.rglob('*.json.gz')):
            rec = C.load(f)
            counts[f"saved_{rec['kind']}"] += 1
            counts[f"status_{rec['kind']}_{rec['status']}"] += 1
            if rec.get('rows') is not None and C.digest(rec['rows']) != rec.get('result_sha256'):
                problems.append(f'{f}: result hash mismatch')
            if rec['environment_id'] not in envs:
                problems.append(f'{f}: unknown environment id')
            if rec['protocol_sha256'] != proto_sha:
                problems.append(f'{f}: protocol hash differs')
        for bdir in sorted(cdir.glob('b[0-9]*')):
            b = int(bdir.name[1:])
            atts = sorted(int(x.name[1:]) for x in bdir.glob('a[0-9]*'))
            dpath = bdir / 'decision.json'
            if not dpath.exists():
                cell['incomplete_attempts'] += len(atts)
                continue
            dec = C.load(dpath)
            cell['incomplete_attempts'] += len([x for x in atts if x != dec['attempt']])
            recs = {}
            for path, rel in dec['timed_records'].items():
                rp = bdir / rel
                if not rp.exists() or not rel.startswith(f"a{dec['attempt']}/"):
                    problems.append(f'Q{q} b{b}: decision references {rel} outside its attempt')
                    continue
                recs[path] = C.load(rp)
                if recs[path]['block'] != b or recs[path]['kind'] != 'timed':
                    problems.append(f'Q{q} b{b}: {rel} is not a timed record of this block')
            for fw in ('django', 'sqlalchemy'):
                fd = dec['frameworks'][fw]
                sp, op = f'{fw}/sql', f'{fw}/orm'
                if sp in recs and op in recs and recs[sp]['status'] == 'ok' and recs[op]['status'] == 'ok':
                    c = C.compare(q, recs[sp]['rows'], recs[op]['rows'],
                                  recs[sp].get('output_columns'), recs[op].get('output_columns'),
                                  policy=dec.get('policy') or C.POLICY_V1)
                    oc = C.orm_path_check(recs[op], recs[sp])
                    acc = c['accepted'] and oc['passed']
                    if acc != fd['accepted'] or c['classification'] != fd.get('classification'):
                        problems.append(f'Q{q} b{b} {fw}: decision does not reproduce '
                                        f'({fd} vs {c["classification"]}/{acc})')
                    if acc:
                        ratios[(q, fw)].append(math.log(recs[op]['elapsed_s'] / recs[sp]['elapsed_s']))
                        counts['accepted_pairs'] += 1
                        counts[f"accepted_{c['classification']}"] += 1
                    else:
                        counts['rejected_pairs'] += 1
                elif fd['accepted']:
                    problems.append(f'Q{q} b{b} {fw}: accepted without two ok timed records')
                else:
                    counts[f"pairs_{fd['status']}"] += 1
            for k in ('cross_sql', 'cross_orm'):
                counts[f"{k}_{dec['comparisons_timed'][k]['classification']}"] += 1
            cell['blocks'][b] = {f: dec['frameworks'][f]['status'] for f in ('django', 'sqlalchemy')}
            seq = C.WILLIAMS[dec['sequence_id']]
            for path, r in recs.items():
                if r['position'] != seq.index(path):
                    problems.append(f'Q{q} b{b}: {path} ran at position {r["position"]}, plan says {seq.index(path)}')
        done = cdir / 'cell-done.json'
        cell['status'] = C.load(done)['status'] if done.exists() else 'in_progress'
        counts['incomplete_attempts'] += cell['incomplete_attempts']
        cells[q] = cell
    summary = {}
    for (q, fw), v in sorted(ratios.items()):
        summary[f'Q{q:02d}:{fw}'] = {'n': len(v), 'median_ratio': round(math.exp(statistics.median(v)), 5)}
    counts['accepted_timed'] = counts['accepted_pairs'] * 2
    return {'run_dir': str(run_dir), 'parameters': params, 'protocol_sha256': proto_sha,
            'environments': envs, 'counts': dict(sorted(counts.items())), 'cells': cells,
            'paired_median_ratios': summary, 'problems': problems, 'passed': not problems, **C.stamps()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir', type=Path)
    ap.add_argument('--campaign-dir', type=Path, required=True)
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    res = verify(a.run_dir, a.campaign_dir)
    if a.write:
        C.save(a.run_dir / f"verification-{res['utc'].replace(':', '')[:17]}.json", res)
    print(json.dumps({k: res[k] for k in ('counts', 'problems', 'passed', 'paired_median_ratios')},
                     indent=1, default=str)[:6000])
    sys.exit(0 if res['passed'] else 1)


if __name__ == '__main__':
    main()
