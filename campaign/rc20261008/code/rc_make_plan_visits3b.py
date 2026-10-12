#!/usr/bin/env python3
"""Plan visits3b: re-measure Oracle's non-indexed TPC-C (phase C) on a quiet host.

The vault snapshot after-phase-F (rc_vault.sh, 2026-10-10) ran its host part
from 21:51:22 to 21:56:50 Cairo, at nice 19 / ionice idle. Oracle's non-indexed
TPC-C run (C-tpcc/oracle-non-indexed) started at 21:51:53, and 104 of its 120
blocks were decided inside that window. Every result check passed, but the
timings were taken beside a concurrent tar/sha256 of the campaign. That run is
kept and superseded; this plan measures the same configuration again, alone,
right after visits3 ends (Oracle still running), in C-tpcc/oracle-non-indexed-r2,
with the same protocol (C-v1), source (src-c) and steps as visits3, and puts the
TPC-C indexes back afterwards. TPC-C state is fingerprinted before and after.
"""
import json
from pathlib import Path

CAMP = Path(__file__).resolve().parent.parent
ENV = 'source <campaign>/code/rc_env.sh oracle tpcc && cd $RC_CAMPAIGN/src && '


def main():
    v = {s['id']: s for s in json.loads((CAMP / 'plans' / 'visits3.json').read_text())['steps']}
    run = json.loads(json.dumps(v['oracle-tpcc-run-non-indexed']))
    run['id'] = 'oracle-tpcc-run-non-indexed-r2'
    run['args']['run_dir'] = 'C-tpcc/oracle-non-indexed-r2'
    fp_after = ENV + ("taskset -c 2,3 $RC_PY $RC_CAMPAIGN/code/rc_fingerprint.py --dbms oracle --benchmark tpcc "
                      "--label oracle-tpcc-C-after-r2 --out $RC_CAMPAIGN/evidence/fingerprints/oracle-tpcc-C-after-r2.json && "
                      "python3 -c \"import json;a=json.load(open('$RC_CAMPAIGN/evidence/fingerprints/oracle-tpcc-C-before-r2.json'))['content_sha256'];"
                      "b=json.load(open('$RC_CAMPAIGN/evidence/fingerprints/oracle-tpcc-C-after-r2.json'))['content_sha256'];"
                      "print('before',a,'after',b);assert a==b\"")
    steps = [
        {'id': 'oracle-tpcc-fp-before-r2', 'kind': 'fingerprint', 'engine': 'oracle', 'benchmark': 'tpcc',
         'label': 'oracle-tpcc-C-before-r2'},
        dict(v['oracle-tpcc-to-non-indexed'], id='oracle-tpcc-to-non-indexed-r2'),
        dict(v['oracle-tpcc-stats-non-indexed'], id='oracle-tpcc-stats-non-indexed-r2'),
        dict(v['oracle-tpcc-verify-non-indexed'], id='oracle-tpcc-verify-non-indexed-r2'),
        run,
        {'id': 'oracle-tpcc-fp-after-r2', 'kind': 'shell', 'command': fp_after},
        dict(v['oracle-tpcc-to-indexed'], id='oracle-tpcc-to-indexed-r2'),
        dict(v['oracle-tpcc-stats-indexed'], id='oracle-tpcc-stats-indexed-r2'),
        dict(v['oracle-tpcc-verify-indexed'], id='oracle-tpcc-verify-indexed-r2'),
    ]
    out = CAMP / 'plans' / 'visits3b.json'
    if out.exists():
        raise SystemExit(f'{out} exists')
    out.write_text(json.dumps({'plan_id': 'visits3b', 'purpose': 'Re-measure Oracle non-indexed TPC-C alone '
                                '(the first run overlapped the after-phase-F vault snapshot)',
                               'derived_from': {'plan': 'plans/visits3.json'}, 'steps': steps}, indent=1) + '\n')
    print(out.name, [s['id'] for s in steps])


if __name__ == '__main__':
    main()
