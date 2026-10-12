#!/usr/bin/env python3
"""Host-side plans for phase E: put each engine in each index state for the
Mac client, with the same step kinds as the visits (rc_controller.py runs them
on the host under systemd, so a Wi-Fi drop cannot cut a step in half).

Per engine, three plans:
  E-<engine>-a  engine on (bench-host apply/verify), SF1 fingerprint against the
                source, the engine must listen on the LAN address, the first
                index state verified (the state the visits left; changed only
                where the visits left the other one) and the host preflight
  E-<engine>-b  the other index state (drop+analyze or create+analyze), verify,
                preflight
  E-<engine>-c  SF1 fingerprint again
The Mac driver (code/rc_e_driver.sh) runs the client between them.

The SF1 states the visits leave: Commercial System A indexed (visits2 rebuilt them for
the indexed Django F cells); PostgreSQL, MySQL and Oracle non-indexed (their
visits end with SF1 dropped). Each E-*-a plan verifies, and halts on, that.
"""
import json
from pathlib import Path

CAMP = Path(__file__).resolve().parent.parent
H = '<campaign>'
PORT = {'postgresql': 5432, 'mysql': 3306, 'sqlserver': 1433, 'oracle': 1521}
FIRST = {'oracle': 'non-indexed', 'sqlserver': 'indexed', 'postgresql': 'non-indexed', 'mysql': 'non-indexed'}
SRC_FP = 'sf1-duckdb-mac-generated-v2.json'


def preflight(e, s):
    return {'id': f'{e}-E-preflight-{s}', 'kind': 'shell',
            'command': f'source {H}/code/rc_env.sh {e} && cd $RC_CAMPAIGN/src && taskset -c 2,3 $RC_PY '
                       f'scripts/0-host/preflight.py --dbms {e} --schema {s}'}


def to_state(e, s):
    acts = ['drop', 'analyze', 'verify'] if s == 'non-indexed' else ['create', 'analyze', 'verify']
    return {'id': f'{e}-E-to-{s}', 'kind': 'index', 'engine': e, 'actions': acts, 'expect': s}


def main():
    out = CAMP / 'plans'
    made = []
    for e, first in FIRST.items():
        second = 'indexed' if first == 'non-indexed' else 'non-indexed'
        port = PORT[e]
        a = [
            {'id': f'{e}-E-engine', 'kind': 'engine', 'engine': e, 'settle': 90},
            {'id': f'{e}-E-fp-before', 'kind': 'fingerprint', 'engine': e, 'label': f'{e}-sf1-E-before',
             'expect_source': SRC_FP},
            # E needs the engine on the LAN address: anything bound only to
            # 127.0.0.1 / 127.0.1.1 (the host name maps there first) fails here
            {'id': f'{e}-E-listen', 'kind': 'shell',
             'command': f'ss -ltn | grep ":{port} "; ss -ltn | grep -E "(0\\.0\\.0\\.0|\\*|\\[::\\]|192\\.168\\.100\\.79):{port} "'},
            {'id': f'{e}-E-verify-{first}', 'kind': 'index', 'engine': e, 'actions': ['verify'], 'expect': first},
            preflight(e, first),
        ]
        b = [to_state(e, second), preflight(e, second)]
        c = [{'id': f'{e}-E-fp-after', 'kind': 'fingerprint', 'engine': e, 'label': f'{e}-sf1-E-after',
              'expect_source': SRC_FP}]
        for suffix, steps, purpose in (('a', a, f'engine on, SF1 {first}, LAN listener checked'),
                                       ('b', b, f'SF1 {second}'), ('c', c, 'closing SF1 fingerprint')):
            pid = f'E-{e}-{suffix}'
            p = out / f'{pid}.json'
            if p.exists():
                raise SystemExit(f'{p} exists')
            p.write_text(json.dumps({'plan_id': pid, 'purpose': f'Phase E host side, {e}: {purpose}',
                                     'first_state': first, 'second_state': second, 'steps': steps}, indent=1) + '\n')
            made.append(pid)
    print(' '.join(made))


if __name__ == '__main__':
    main()
