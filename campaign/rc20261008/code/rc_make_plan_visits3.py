#!/usr/bin/env python3
"""Plan visits3: the rest of plan visits2 with phase F under protocol F-v3.

A Mac test of every remaining F cell, run while visits2 measured Commercial System A,
found that F-v2's G column assembly missed Oracle's upper-case labels (Django
Q15). rc_controlled3.py corrects it under F-v3. visits2 is stopped by a hold
when it starts its closing Commercial System A fingerprint (commercial_a-sf1-fp-after), a
read-only step; visits3 starts with that fingerprint and continues with every
remaining step of visits2 unchanged, except that every F step runs
rc_controlled3.py under F-v3 in F-fourpath/v3/.
"""
import json
import sys
from pathlib import Path

CAMP = Path(__file__).resolve().parent.parent
F3 = 'protocols/rc20261008-F-v3.json'


def main():
    v = json.loads((CAMP / 'plans' / 'visits2.json').read_text())
    ids = [s['id'] for s in v['steps']]
    k = ids.index('sqlserver-sf1-fp-after')
    assert ids[k + 1] == 'postgresql-engine', ids[k:k + 2]
    steps = []
    for s in v['steps'][k:]:
        s = json.loads(json.dumps(s))
        if s['id'] in ('postgresql-sf1-verify-indexed', 'mysql-sf1-verify-indexed', 'oracle-q20-plans'):
            # Phase E (the Mac as client) needs each engine reachable on the LAN
            # address. Read-only, non-fatal: record what the engine listens on
            # while it runs here, hours before E needs it. /etc/hosts maps the
            # host name to 127.0.1.1 first, so a listener bound by host name
            # would accept local connections only (audit of 2026-10-09 23:00).
            e = s['id'].split('-')[0]
            port = {'postgresql': 5432, 'mysql': 3306, 'oracle': 1521}[e]
            steps.append({'id': f'{e}-listen-probe', 'kind': 'shell', 'command':
                          f'echo "listening on :{port}:"; ss -ltn | grep ":{port} " || echo "LISTEN-PROBE: nothing on {port}"; '
                          'true'})
        if s['id'] == 'mysql-sf1-verify-indexed':
            # Early, non-fatal probe of the root helper's MySQL grant, which has
            # never run: it needs root to log in to MySQL without a password
            # (auth_socket). The GRANT is idempotent and touches only tpch_sf2.*;
            # step mysql-root-mysql-sf2-grant repeats it before the SF2 load. A
            # failure here leaves hours to fix it (audit of 2026-10-09 22:40).
            steps.append({'id': 'mysql-root-probe', 'kind': 'shell', 'command':
                          'if sudo -n /usr/local/sbin/rc-campaign-root mysql-sf2-grant; then echo ROOT-GRANT-OK; '
                          'else echo "ROOT-GRANT-FAILED: mysql-root-mysql-sf2-grant will fail unless fixed"; fi'})
        if s['id'] == 'postgresql-sf2-fp-before':
            # tpch_sf2 gets tpch's database-level settings, and the two are shown
            # to run with equal settings, before anything is measured at SF2
            # (code/rc_pg_sf2_settings.py; audit of 2026-10-09 22:40)
            steps.append({'id': 'postgresql-sf2-settings', 'kind': 'shell', 'command':
                          'source <campaign>/code/rc_env.sh '
                          'postgresql && cd $RC_CAMPAIGN && taskset -c 2,3 $RC_PY code/rc_pg_sf2_settings.py '
                          '--target tpch_sf2 --out evidence/sf2-setup/postgresql-sf2-settings.json'})
        if s['kind'] == 'run' and s['args'].get('runner') == 'rc_censored.py':
            # phase B under B-v2 (B-v1's runner crashed after a finished probe;
            # fixed before any phase B run - decision log, 2026-10-09 22:45)
            assert s['args']['protocol'] == 'protocols/rc20261008-B-v1.json', s['id']
            s['args']['protocol'] = 'protocols/rc20261008-B-v2.json'
        if s['kind'] == 'run' and s['args'].get('runner') == 'rc_controlled2.py':
            a = s['args']
            assert a['protocol'] == 'protocols/rc20261008-F-v2.json' and a['run_dir'].startswith('F-fourpath/v2/'), s['id']
            a['runner'], a['protocol'] = 'rc_controlled3.py', F3
            a['run_dir'] = a['run_dir'].replace('F-fourpath/v2/', 'F-fourpath/v3/', 1)
        steps.append(s)
    plan = {'plan_id': 'visits3',
            'purpose': 'Rest of plan visits2 from the closing SQL Server fingerprint: the PostgreSQL, MySQL and '
                       'Oracle visits as planned, phase F under F-v3.',
            'derived_from': {'plan': 'plans/visits2.json', 'from_step': 'sqlserver-sf1-fp-after'},
            'f_cells': v['f_cells'], 'steps': steps}
    out = CAMP / 'plans' / 'visits3.json'
    # --rewrite-unused: allowed only while visits3 has never run (the host has
    # no controller/visits3-state.json; checked on the host before copying)
    if out.exists() and '--rewrite-unused' not in sys.argv:
        raise SystemExit(f'{out} exists')
    out.write_text(json.dumps(plan, indent=1) + '\n')
    n = sum(1 for s in steps if s['kind'] == 'run' and s['args'].get('runner') == 'rc_controlled3.py')
    print(out.name, len(steps), 'steps,', n, 'F-v3 steps')


if __name__ == '__main__':
    main()
