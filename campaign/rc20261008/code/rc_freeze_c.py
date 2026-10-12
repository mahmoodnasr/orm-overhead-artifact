#!/usr/bin/env python3
"""Freeze protocol rc20261008-C-v1 (phase C, transactions) on the benchmark host.

The design is the transaction pilot's (rc20261008-Cpilot-v1), which passed on
Oracle: matched seeded inputs, scoped before/after capture, revert and exact
re-verification, balanced order. What changes is the scale - 24 blocks - and
the source: phase C runs from the src-c worktree (commit b8306e0) carrying the
two baseline corrections the pilot confirmed (patches/C1-C2-applied.diff).
tpcc_source_hashes pins that source, so rc_tpcc refuses to run if src-c moves.
Refuses to overwrite an existing protocol.

Usage (host): python3 code/rc_freeze_c.py --campaign-dir <campaign>
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, required=True)
    a = ap.parse_args()
    camp = a.campaign_dir.resolve()
    out = camp / 'protocols' / 'rc20261008-C-v1.json'
    if out.exists():
        raise SystemExit(f'{out} exists; protocols are frozen once')
    src = camp / 'src-c'
    commit = subprocess.run(['git', '-C', str(src), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(src), 'status', '--porcelain'], capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit(f'src-c has uncommitted changes:\n{dirty}')
    # the same file set rc_tpcc.inventory hashes
    hashes = {}
    for folder in ('django_app/tpcc_queries', 'sqlalchemy_app/tpcc_queries'):
        for p in sorted((src / folder).glob('*.py')):
            hashes[str(p.relative_to(src))] = C.file_sha256(p)
    for name in ('django_app/tpcc_models.py', 'sqlalchemy_app/tpcc_models.py', 'tpcc_config.py'):
        hashes[name] = C.file_sha256(src / name)
    pilot = json.loads((camp / 'protocols' / 'rc20261008-Cpilot-v1.json').read_text())
    proto = dict(pilot)
    proto.update({
        'protocol_id': 'rc20261008-C-v1', 'phase': 'C', 'frozen': C.stamps(),
        'purpose': ('Phase C: transaction state verification and timing (R1-3, R2-4, R2-2). 5 transaction types x 4 '
                    'DBMS x 2 index configurations x 2 frameworks = 80 cells, 24 blocks each, from src-c.'),
        'design': dict(pilot['design'], blocks=24),
        'source': {'worktree': 'src-c', 'commit': commit,
                   'corrections': 'patches/C1-C2-applied.diff (C1 Django SQL Payment h_data; C2 SQLAlchemy SQL '
                                  'Order-Status order lines), confirmed by the Oracle transaction pilot 2026-10-08',
                   'patch_sha256': C.file_sha256(camp / 'patches' / 'C1-C2-applied.diff')},
        'tpcc_source_hashes': hashes,
        'runner_code_sha256': {n: C.file_sha256(HERE / n) for n in ('rc_tpcc.py', 'rc_common.py')},
        'pilot_protocol': {'protocol_id': pilot['protocol_id'],
                           'sha256': C.file_sha256(camp / 'protocols' / 'rc20261008-Cpilot-v1.json')},
    })
    C.save(out, proto, immutable=True)
    print(out, C.file_sha256(out), commit, len(hashes), 'source files pinned')


if __name__ == '__main__':
    main()
