#!/usr/bin/env python3
"""Phase F cell list (R2-3), fixed by rule before any phase F run.

  1. the paper's cells above +100 % (F-cells-from-paper.json), less the three
     October four-path diagnostics, which are reused (R1-4);
  2. every phase A cell above +100 % not already in 1;
  3. a seeded random sample of two further cells per engine x index state
     (16 cells), so RQ2 is not answered only from cells selected by outcome.
     Eligible: phase A cells measured with all 8 blocks accepted, not in 1-2,
     not an October cell. Order: sha256("rc20261008-F-random-sample-v1:" +
     "<dbms>/<schema>/Q<nn>/<framework>"), the two smallest per configuration.
     Anyone can redraw it from the phase A records.

Runs after phase A (refuses while a phase A run lacks completion.json, unless
--allow-partial, which never writes the campaign file).
Writes F-cells-final.json.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMP = HERE.parent
sys.path.insert(0, str(HERE))
import rc_analyze as R  # noqa: E402
import rc_common as C  # noqa: E402

SEED_TEXT = 'rc20261008-F-random-sample-v1'
CONFIGS = [(e, s) for e in ('sqlserver', 'postgresql', 'mysql', 'oracle') for s in ('indexed', 'non-indexed')]


def key(e, s, q, fw):
    return f'{e}/{s}/Q{q:02d}/{fw}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--allow-partial', action='store_true')
    ap.add_argument('--out', type=Path, default=CAMP / 'F-cells-final.json')
    a = ap.parse_args()
    paper = json.loads((CAMP / 'F-cells-from-paper.json').read_text())
    october = set(paper['reused_october'])
    missing = [f'{e}-{s}' for e, s in CONFIGS if not (CAMP / 'A-sf1' / f'{e}-{s}' / 'completion.json').exists()]
    if missing and not a.allow_partial:
        raise SystemExit(f'phase A not complete: {missing}')
    cells = {}       # key -> reason
    for g in paper['groups']:
        for q in g['queries']:
            cells[key(g['dbms'], g['schema'], q, g['framework'])] = 'paper > +100 %'
    measured = {}
    for e, s in CONFIGS:
        d = CAMP / 'A-sf1' / f'{e}-{s}'
        if not (d / 'run-parameters.json').exists():
            continue
        R.path_cvs, R.censored_cells = [], []
        for c in R.load_run(d)[0]:
            measured[key(e, s, c['query'], c['framework'])] = c['overhead_pct']
    for k, ov in sorted(measured.items()):
        if ov > 100 and k not in cells and k not in october:
            cells[k] = f'phase A > +100 % ({ov:.0f} %)'
    random_cells = {}
    for e, s in CONFIGS:
        elig = [k for k in measured if k.startswith(f'{e}/{s}/') and k not in cells and k not in october]
        elig.sort(key=lambda k: hashlib.sha256(f'{SEED_TEXT}:{k}'.encode()).hexdigest())
        for k in elig[:2]:
            random_cells[k] = 'seeded random sample'
    cells.update(random_cells)
    groups = {}
    for k in cells:
        e, s, q, fw = k.split('/')
        groups.setdefault((e, s, fw), []).append(int(q[1:]))
    out = {'rule': __doc__.split('\n\n')[1].strip(), 'seed_text': SEED_TEXT,
           'phase_a_complete': not missing, 'phase_a_missing': missing,
           'reused_october': sorted(october), 'cells': dict(sorted(cells.items())),
           'counts': {'paper': sum(v == 'paper > +100 %' for v in cells.values()),
                      'phase_a_added': sum(v.startswith('phase A') for v in cells.values()),
                      'random': len(random_cells), 'total': len(cells)},
           'groups': [{'dbms': e, 'schema': s, 'framework': fw, 'queries': sorted(qs)}
                      for (e, s, fw), qs in sorted(groups.items())],
           'source_hashes': {'F-cells-from-paper.json': C.file_sha256(CAMP / 'F-cells-from-paper.json')},
           **C.stamps()}
    if missing:
        print(json.dumps(out['counts']), 'PARTIAL - not written'); return
    C.save(a.out, out, immutable=True)
    print(a.out.name, json.dumps(out['counts']))


if __name__ == '__main__':
    main()
