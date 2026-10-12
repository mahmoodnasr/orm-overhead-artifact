#!/usr/bin/env python3
"""Write the phase A controller plan (SF1 analytical grid, all four engines).

Per engine: switch, fingerprint against the SF1 source, primary-key-only state
(drop the 15 secondary indexes, refresh statistics, verify), the historical
preflight probe, the 22-query non-indexed phase, verification; then create the
indexes (which refreshes statistics), verify, preflight, the indexed phase,
verification, and a closing fingerprint. Queries run in ascending order of
their historical SF1 cell time, so known-completing work comes first and the
historically censored cells come last.
"""
import argparse
import json
from pathlib import Path

CAMP = '<campaign>'


def tpcc_pilot(e):
    fp = lambda tag: (f"taskset -c 2,3 $RC_PY $RC_CAMPAIGN/code/rc_fingerprint.py --dbms {e} --benchmark tpcc "
                      f"--label {e}-tpcc-Cpilot-{tag} --out $RC_CAMPAIGN/evidence/fingerprints/{e}-tpcc-Cpilot-{tag}.json")
    mi = lambda act: f"taskset -c 2,3 $RC_PY scripts/1-setup/manage_indexes.py --database default --benchmark tpcc --action {act}"
    return ("( set -x; source " + CAMP + f"/code/rc_env.sh {e} tpcc && cd $RC_CAMPAIGN/src && "
            + mi('list') + " ; " + mi('create') + " && " + mi('verify --expect indexed') + " && " + fp('before') + " && "
            + f"taskset -c 2,3 $RC_PY $RC_CAMPAIGN/code/rc_tpcc.py --campaign-dir $RC_CAMPAIGN --run-dir $RC_CAMPAIGN/pilot-tpcc/{e}-indexed "
              f"--protocol $RC_CAMPAIGN/protocols/rc20261008-Cpilot-v1.json --phase Cpilot --dbms {e} --schema indexed --blocks 2 --mode pilot ; "
            + fp('after') + " ; echo TPCC_PILOT_DONE ) ; true")


def order(pred, key):
    p = pred.get(key, {})
    val = lambda x: float(x['value']) if isinstance(x, dict) else float(x)
    return sorted(range(1, 23), key=lambda q: (val(p.get(str(q), 0)), q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--protocol', required=True, help='protocols/<id>.json relative to the campaign dir')
    ap.add_argument('--protocol-file', required=True, type=Path, help='local copy to read predictions from')
    ap.add_argument('--engines', nargs='+', default=['oracle', 'mysql', 'postgresql', 'sqlserver'])
    ap.add_argument('--plan-id', default='A-sf1')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    pred = json.loads(a.protocol_file.read_text())['predicted_cell_seconds']
    steps = []
    for e in a.engines:
        pre = lambda s: {"id": f"{e}-preflight-{s}", "kind": "shell",
                         "command": f"source {CAMP}/code/rc_env.sh {e} && cd $RC_CAMPAIGN/src && taskset -c 2,3 $RC_PY scripts/0-host/preflight.py --dbms {e} --schema {s}"}
        steps += [
            {"id": f"{e}-engine", "kind": "engine", "engine": e, "settle": 90},
            {"id": f"{e}-fp-before", "kind": "fingerprint", "engine": e, "label": f"{e}-sf1-A-before",
             "expect_source": "sf1-duckdb-mac-generated-v2.json"},
            {"id": f"{e}-to-non-indexed", "kind": "index", "engine": e, "actions": ["drop", "analyze", "verify"],
             "expect": "non-indexed"},
            pre('non-indexed'),
            {"id": f"{e}-run-non-indexed", "kind": "run", "engine": e, "resumable": True,
             "args": {"run_dir": f"A-sf1/{e}-non-indexed", "protocol": a.protocol, "phase": "A", "schema": "non-indexed",
                      "mode": "main", "queries": order(pred, f'{e}:non-indexed')}},
            {"id": f"{e}-verify-non-indexed", "kind": "verify", "run_dir": f"A-sf1/{e}-non-indexed"},
            {"id": f"{e}-to-indexed", "kind": "index", "engine": e, "actions": ["create", "verify"], "expect": "indexed"},
            pre('indexed'),
            {"id": f"{e}-run-indexed", "kind": "run", "engine": e, "resumable": True,
             "args": {"run_dir": f"A-sf1/{e}-indexed", "protocol": a.protocol, "phase": "A", "schema": "indexed",
                      "mode": "main", "queries": order(pred, f'{e}:indexed')}},
            {"id": f"{e}-verify-indexed", "kind": "verify", "run_dir": f"A-sf1/{e}-indexed"},
            {"id": f"{e}-fp-after", "kind": "fingerprint", "engine": e, "label": f"{e}-sf1-A-after",
             "expect_source": "sf1-duckdb-mac-generated-v2.json"},
            # Non-blocking: pilot evidence for the transaction runner on this
            # engine, gathered while the engine is up anyway. Never halts phase A.
            {"id": f"{e}-tpcc-pilot", "kind": "shell", "command": tpcc_pilot(e)},
        ]
    a.out.write_text(json.dumps({"plan_id": a.plan_id, "purpose": "Phase A: SF1 analytical grid, 352 comparison cells.",
                                 "protocol": a.protocol, "steps": steps}, indent=1) + '\n')
    print(a.out, len(steps), 'steps')


if __name__ == '__main__':
    main()
