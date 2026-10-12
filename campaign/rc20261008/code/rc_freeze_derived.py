#!/usr/bin/env python3
"""Freeze a protocol derived from rc20261008-A-v1 (phases B, F pilot, F).

Phases B and F subclass the frozen phase A runner, so they share A-v1's
inputs, result policy, expected row counts, dataset identities and source
snapshot; deriving the protocol from A-v1 keeps those identical by
construction. What a derived protocol adds is its own id and phase, the hashes
of every runner file its runner records (the gate compares them), and the
design text of the phase. Refuses to overwrite an existing protocol.

Usage (host):
  python3 code/rc_freeze_derived.py --campaign-dir . --id rc20261008-B-v1 --phase B \
      --runner-files rc_analytical.py rc_common.py rc_censored.py --design-file <json> --notes '...'
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, required=True)
    ap.add_argument('--base', default='rc20261008-A-v1')
    ap.add_argument('--id', required=True)
    ap.add_argument('--phase', required=True)
    ap.add_argument('--runner-files', nargs='+', required=True)
    ap.add_argument('--design-file', type=Path, required=True, help='JSON object merged into the base design')
    ap.add_argument('--notes', required=True)
    a = ap.parse_args()
    camp = a.campaign_dir.resolve()
    out = camp / 'protocols' / f'{a.id}.json'
    if out.exists():
        raise SystemExit(f'{out} exists; protocols are frozen once')
    base_path = camp / 'protocols' / f'{a.base}.json'
    base = json.loads(base_path.read_text())
    proto = dict(base)
    proto.update({'protocol_id': a.id, 'phase': a.phase, 'frozen': C.stamps(), 'notes': a.notes,
                  'derived_from': {'protocol_id': a.base, 'sha256': C.file_sha256(base_path)},
                  'runner_code_sha256': {n: C.file_sha256(HERE / n) for n in a.runner_files},
                  'design': dict(base['design'], **json.loads(a.design_file.read_text()))})
    C.save(out, proto, immutable=True)
    print(out.name, C.file_sha256(out), proto['runner_code_sha256'])


if __name__ == '__main__':
    main()
