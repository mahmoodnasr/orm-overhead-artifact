#!/usr/bin/env python3
"""Bind each phase V validation (Mac) to the host cell it validates.

A validation on the second server stands for the host's censored cell only if
the two executed the same statements against the same data on the same
software. Data and software are bound by the content fingerprints and the
inventories. This script binds the statements: for every path of every
validated cell it compares the SQL text and parameters the Mac executed with
those the host's phase A cell-warmup call issued before it timed out (the
runner captures a statement before executing it, so a censored record still
holds it). Equal means byte-identical SQL and identical typed parameters.

Second binding, on the host alone (the "indexed twin"): the ORM and the
handwritten SQL are the same text with or without secondary indexes, so the
censored non-indexed cell-warmup call and the indexed cell-warmup call of the
same cell send byte-identical statements on the same input against the same
data. Indexes change the plan, not the result. Phase A checked the indexed
call's result against its baseline (cellwarm/outcome.json comparisons), so an
identical statement whose twin was accepted is validated on the host itself.

Usage (Mac, after code/rc_sync.sh):
    python3 code/rc_bind_v.py --out evidence/V-binding.json
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMP = HERE.parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

PATHS = ('django/sql', 'django/orm', 'sqlalchemy/sql', 'sqlalchemy/orm')


def statements(rec):
    return [{'sql': s['sql'], 'params': s.get('params')} for s in rec.get('statements', [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path)
    a = ap.parse_args()
    out = []
    for vf in sorted((CAMP / 'V-censored' / 'v2').glob('*-non-indexed/q*/validation.json')):
        run = vf.parent.parent.name                       # e.g. postgresql-non-indexed
        q = vf.parent.name
        v = json.loads(vf.read_text())
        host_cw = sorted((CAMP / 'A-sf1' / run / q / 'cellwarm').glob('a*'))
        for p in PATHS:
            mac = json.load(gzip.open(vf.parent / v['records'][p]))
            row = {'run': run, 'query': q, 'path': p, 'mac_status': mac['status']}
            if not host_cw:
                row.update(binding='pending', reason='host phase A cell warm-up not recorded yet')
            else:
                hf = host_cw[-1] / f'{p.replace("/", "-")}.json.gz'
                host = json.load(gzip.open(hf))
                same = C.digest(statements(host)) == C.digest(statements(mac))
                row.update(host_status=host['status'], host_record=str(hf.relative_to(CAMP)),
                           host_parameters_equal=C.digest(host['parameters']) == C.digest(mac['parameters']),
                           statements_identical=same, binding='bound' if same else 'differs')
            out.append(row)
            print(f"{run:24s} {q} {p:15s} {row['binding']:8s} host={row.get('host_status', '-'):8s} mac={row['mac_status']}")
    twins = []
    cells = {('postgresql', 13): ('django',), ('postgresql', 17): ('django', 'sqlalchemy'),
             ('postgresql', 20): ('django', 'sqlalchemy'), ('postgresql', 21): ('django', 'sqlalchemy'),
             ('mysql', 13): ('django',), ('mysql', 17): ('django', 'sqlalchemy'), ('mysql', 20): ('django', 'sqlalchemy')}
    for (e, qn), fws in cells.items():
        q = f'q{qn:02d}'
        ni = sorted((CAMP / 'A-sf1' / f'{e}-non-indexed' / q / 'cellwarm').glob('a*'))
        ix = CAMP / 'A-sf1' / f'{e}-indexed' / q / 'cellwarm'
        for fw in fws:
            row = {'cell': f'{e}/non-indexed/{q}/{fw}'}
            if not ni or not (ix / 'outcome.json').exists():
                row.update(binding='pending', reason='phase A has not recorded both cell warm-ups yet')
            else:
                same = {}
                for p in (f'{fw}/sql', f'{fw}/orm'):
                    f = p.replace('/', '-') + '.json.gz'
                    h = json.load(gzip.open(ni[-1] / f))
                    t = json.load(gzip.open(sorted(ix.glob('a*'))[-1] / f))
                    same[p] = (C.digest(statements(h)) == C.digest(statements(t))
                               and C.digest(h['parameters']) == C.digest(t['parameters']))
                cmp_ = C.load(ix / 'outcome.json')['comparisons'][fw]
                ok = bool(cmp_.get('accepted')) and bool((cmp_.get('orm_path_check') or {}).get('passed'))
                row.update(statements_identical=same, twin_classification=cmp_.get('classification'),
                           twin_accepted=ok, binding='validated_by_twin' if ok and all(same.values()) else 'not_bound')
            twins.append(row)
            print(f"twin {row['cell']:36s} {row['binding']}")
    if a.out:
        a.out.write_text(json.dumps({'generated': C.stamps(), 'rows': out, 'indexed_twin': twins},
                                    indent=1, default=str) + '\n')


if __name__ == '__main__':
    main()
