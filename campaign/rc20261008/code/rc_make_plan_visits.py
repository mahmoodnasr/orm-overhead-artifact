#!/usr/bin/env python3
"""Controller plan for the per-engine visits after phase A: F, B, C, D.

One visit per engine (Commercial System A first - it is up when phase A ends - then
PostgreSQL, MySQL, Oracle), so each engine is started, fingerprinted and
switched between index states once:

  engine -> SF1 fingerprint
  [Oracle: Q20 plan capture on SF1 indexed, EXPLAIN only]
  SF1 indexed: preflight -> F cells (indexed), one run per framework
  SF1 primary keys only -> preflight -> F cells (non-indexed) -> B probes
  SF1 closing fingerprint
  C (TPC-C, from src-c) -> D (SF2 subset), as rc_make_plans_cd generates them

F's cell list comes from F-cells-final.json (rc_select_f.py, after phase A);
B's from the phase A cells censored on one arm. Phase E (separate client) is a
separate plan, run last with the Mac as client.

Usage: python3 code/rc_make_plan_visits.py --f-protocol protocols/rc20261008-F-v1.json --out plans/visits.json
       (--f-cells <file> to plan from a draft list; the plan records which)
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_make_plans_cd as CD  # noqa: E402
import rc_common as C  # noqa: E402

CAMP = CD.CAMP          # host path, as in every plan
LOCAL = HERE.parent
ENGINES = ('sqlserver', 'postgresql', 'mysql', 'oracle')
SF1_SOURCE = 'sf1-duckdb-mac-generated-v2.json'
# SF1 cells censored on the host (historical SF1 and phase A): plans recorded
CENSORED_SF1 = {'postgresql': [13, 17, 20, 21], 'mysql': [13, 17, 20]}
# censored on one arm in phase A (and historically): matched-input probes
B_CELLS = {('postgresql', 'non-indexed'): [(13, 'django', 'django/orm')],
           ('mysql', 'non-indexed'): [(13, 'django', 'django/orm')]}


def shell(sid, e, cmd):
    return {"id": sid, "kind": "shell",
            "command": f"source {CAMP}/code/rc_env.sh {e} && cd $RC_CAMPAIGN/src && {cmd}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--f-protocol', required=True)
    ap.add_argument('--b-protocol', default='protocols/rc20261008-B-v1.json')
    ap.add_argument('--c-protocol', default='protocols/rc20261008-C-v1.json')
    ap.add_argument('--d-protocol', default='protocols/rc20261008-A-v1.json')
    ap.add_argument('--f-cells', type=Path, default=LOCAL / 'F-cells-final.json')
    ap.add_argument('--engines', nargs='+', default=list(ENGINES))
    ap.add_argument('--skip-cd', nargs='*', default=[], help='engines whose C and D already ran in an earlier plan')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    fc = json.loads(a.f_cells.read_text())
    steps = []
    for e in a.engines:
        steps += [{"id": f"{e}-engine", "kind": "engine", "engine": e, "settle": 90},
                  {"id": f"{e}-sf1-fp-before", "kind": "fingerprint", "engine": e,
                   "label": f"{e}-sf1-visit-before", "expect_source": SF1_SOURCE}]
        if e == 'oracle':
            steps.append(shell("oracle-q20-plans", e,
                               "cd $RC_CAMPAIGN && taskset -c 2,3 $RC_PY code/rc_explain_g.py --run-dir A-sf1/oracle-indexed "
                               "--query 20 --out evidence/G-plans/oracle-indexed-q20-host.json"))
        for schema in ('indexed', 'non-indexed'):
            if schema == 'indexed':
                steps.append({"id": f"{e}-sf1-verify-indexed", "kind": "index", "engine": e,
                              "actions": ["verify"], "expect": "indexed"})
            else:
                steps.append({"id": f"{e}-sf1-to-non-indexed", "kind": "index", "engine": e,
                              "actions": ["drop", "analyze", "verify"], "expect": "non-indexed"})
            if schema == 'non-indexed' and e in CENSORED_SF1:
                # why the censored cells cannot finish: plans of their recorded
                # statements in the state the timed calls faced (EXPLAIN only)
                steps.append(shell(f"{e}-censored-plans", e,
                                   f"cd $RC_CAMPAIGN && taskset -c 2,3 $RC_PY code/rc_explain_censored.py "
                                   f"--run-dir A-sf1/{e}-non-indexed --queries {' '.join(map(str, CENSORED_SF1[e]))} "
                                   f"--out evidence/censored-plans/{e}-non-indexed.json"))
            steps.append(shell(f"{e}-sf1-preflight-{schema}", e,
                               f"taskset -c 2,3 $RC_PY scripts/0-host/preflight.py --dbms {e} --schema {schema}"))
            for g in fc['groups']:
                if (g['dbms'], g['schema']) != (e, schema):
                    continue
                fw = g['framework']
                steps.append({"id": f"{e}-F-{schema}-{fw}", "kind": "run", "engine": e, "resumable": True,
                              "args": {"runner": "rc_controlled.py", "run_dir": f"F-fourpath/{e}-{schema}-{fw}",
                                       "protocol": a.f_protocol, "phase": "F", "schema": schema, "mode": "main",
                                       "queries": g['queries'], "extra": ["--framework", fw]}})
            for q, fw, path in B_CELLS.get((e, schema), []):
                steps.append({"id": f"{e}-B-{schema}-q{q:02d}-{fw}", "kind": "run", "engine": e, "resumable": True,
                              "args": {"runner": "rc_censored.py", "run_dir": f"B-censored/{e}-{schema}-{fw}",
                                       "protocol": a.b_protocol, "phase": "B", "schema": schema, "mode": "main",
                                       "queries": [q], "extra": ["--framework", fw, "--censored-path", path]}})
        steps.append({"id": f"{e}-sf1-fp-after", "kind": "fingerprint", "engine": e,
                      "label": f"{e}-sf1-visit-after", "expect_source": SF1_SOURCE})
        if e not in a.skip_cd:
            steps += [s for s in CD.plan_c([e], a.c_protocol)['steps'] if s['kind'] != 'engine']
            steps += [s for s in CD.plan_d([e], a.d_protocol)['steps'] if s['kind'] != 'engine']
    ids = [s['id'] for s in steps]
    assert len(ids) == len(set(ids)), 'duplicate step ids'
    plan = {"plan_id": "visits", "purpose": "Per-engine visits after phase A: F (four paths), B (censored bounds), "
                                            "C (transactions), D (SF2 subset).",
            "f_cells": {'file': a.f_cells.name, 'sha256': C.file_sha256(a.f_cells),
                        'final': a.f_cells.name == 'F-cells-final.json'},
            "steps": steps}
    a.out.write_text(json.dumps(plan, indent=1) + '\n')
    print(a.out, len(steps), 'steps')


if __name__ == '__main__':
    main()
