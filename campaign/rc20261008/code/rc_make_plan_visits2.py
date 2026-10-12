#!/usr/bin/env python3
"""Plan visits2: the rest of plan `visits` with phase F under protocol F-v2.

Plan `visits` stopped on 2026-10-09 at ~21:46 Cairo, inside step 8
(commercial_a-F-non-indexed-django), after F-v1's Django Q22 block 0. Two
defects of the F-v1 runner had been found there: Django Q15's G and B could not
be compared with L, and a G or B over the limit in the cell warm-up was
repeated in every block. rc_controlled2.py corrects them under F-v2
(protocols/rc20261008-F-v2.json; 00-readiness-report.md, 2026-10-09).

visits2 = Commercial System A, still in its non-indexed state: the nine Django cells
again and the four SQLAlchemy cells, all under F-v2; indexes back; the SQL
Server indexed Django cells again; the closing fingerprint. Then steps 11-113 of
`visits` unchanged, except that every F step runs rc_controlled2.py under F-v2
in F-fourpath/v2/. Phase B, C and D steps are byte-identical.
"""
import json
from pathlib import Path

CAMP = Path(__file__).resolve().parent.parent
F2 = 'protocols/rc20261008-F-v2.json'
PRE = ('source <campaign>/code/rc_env.sh sqlserver '
       '&& cd $RC_CAMPAIGN/src && taskset -c 2,3 $RC_PY scripts/0-host/preflight.py --dbms sqlserver --schema ')


def f2(step):
    """An F step of plan visits, under F-v2."""
    s = json.loads(json.dumps(step))
    a = s['args']
    assert a['runner'] == 'rc_controlled.py' and a['protocol'] == 'protocols/rc20261008-F-v1.json', s['id']
    a['runner'], a['protocol'] = 'rc_controlled2.py', F2
    a['run_dir'] = a['run_dir'].replace('F-fourpath/', 'F-fourpath/v2/', 1)
    return s


def main():
    v = json.loads((CAMP / 'plans' / 'visits.json').read_text())
    steps = v['steps']
    ids = [s['id'] for s in steps]
    assert ids[8] == 'sqlserver-F-non-indexed-django' and ids[10] == 'sqlserver-sf1-fp-after' \
        and ids[11] == 'postgresql-engine', ids[:12]
    by = dict(zip(ids, steps))
    dj_ix = f2(by['sqlserver-F-indexed-django'])
    head = [
        {'id': 'sqlserver-sf1-verify-non-indexed', 'kind': 'index', 'engine': 'sqlserver',
         'actions': ['verify'], 'expect': 'non-indexed'},
        {'id': 'sqlserver-sf1-preflight-non-indexed-2', 'kind': 'shell', 'command': PRE + 'non-indexed'},
        f2(by['sqlserver-F-non-indexed-django']),
        f2(by['sqlserver-F-non-indexed-sqlalchemy']),
        {'id': 'sqlserver-sf1-to-indexed', 'kind': 'index', 'engine': 'sqlserver',
         'actions': ['create', 'analyze', 'verify'], 'expect': 'indexed'},
        {'id': 'sqlserver-sf1-preflight-indexed-2', 'kind': 'shell', 'command': PRE + 'indexed'},
        dj_ix,
        by['sqlserver-sf1-fp-after'],
    ]
    rest = [f2(s) if s['kind'] == 'run' and s['args'].get('runner') == 'rc_controlled.py' else s for s in steps[11:]]
    plan = {'plan_id': 'visits2',
            'purpose': 'Rest of plan visits after the F-v1 runner defects of 2026-10-09: phase F under F-v2 '
                       '(SQL Server Django cells again), then the PostgreSQL, MySQL and Oracle visits as planned.',
            'derived_from': {'plan': 'plans/visits.json', 'stopped_in_step': 'sqlserver-F-non-indexed-django'},
            'f_cells': v['f_cells'], 'steps': head + rest}
    out = CAMP / 'plans' / 'visits2.json'
    if out.exists():
        raise SystemExit(f'{out} exists')
    out.write_text(json.dumps(plan, indent=1) + '\n')
    n_f = sum(1 for s in plan['steps'] if s['kind'] == 'run' and s['args'].get('runner') == 'rc_controlled2.py')
    print(out.name, len(plan['steps']), 'steps,', n_f, 'F-v2 steps')


if __name__ == '__main__':
    main()
