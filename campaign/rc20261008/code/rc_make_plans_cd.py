#!/usr/bin/env python3
"""Controller plans for phase C (transactions) and phase D (SF2 subset).

Phase C, per engine: switch; TPC-C content fingerprint; primary-key-only TPC-C
state (drop the nine TPC-C secondary indexes, refresh statistics, verify); the
transaction runner over the five types, 24 blocks; indexes created and
verified; the runner again; a closing fingerprint that must equal the opening
one, because every transaction was reverted and re-verified.

Phase D, per engine: switch; create the SF2 database beside SF1 and load it
from the hash-verified DuckDB file (no timing runs during this); schema
compared column for column with SF1; content fingerprint against the SF2
source; primary-key-only state; preflight; Q6/Q17/Q18/Q20 at SF2; indexes;
preflight; indexed run; closing fingerprint.
"""
import argparse
import json
from pathlib import Path

CAMP = '<campaign>'
D_QUERIES = [6, 17, 18, 20, 21]   # Q21 added 2026-10-08: R1 cites System A non-indexed Q21 (1620 %) as a headline example
# Cells censored on the host at SF1 (all four paths > 900 s) are not run at SF2:
# a larger scale cannot bring them under the ceiling, and there is no SF1 ratio
# to compare (same rule as phase G, evidence/G-scope-change-20261008.json).
HOST_CENSORED_SF1 = {('postgresql', 'non-indexed'): {17, 20, 21}, ('mysql', 'non-indexed'): {17, 20}}


def d_queries(e, schema):
    return [q for q in D_QUERIES if q not in HOST_CENSORED_SF1.get((e, schema), set())]


def tpcc_stats(e, state):
    return {"id": f"{e}-tpcc-stats-{state}", "kind": "shell",
            "command": f"source {CAMP}/code/rc_env.sh {e} tpcc && cd $RC_CAMPAIGN/src && taskset -c 2,3 $RC_PY $RC_CAMPAIGN/code/rc_tpcc_stats.py"}


def plan_c(engines, protocol):
    # "src": "src-c" is required: without it the controller runs rc_tpcc from
    # src, which lacks the two baseline corrections (patches/C1-C2-applied.diff)
    steps = []
    for e in engines:
        steps += [
            {"id": f"{e}-engine", "kind": "engine", "engine": e, "settle": 90},
            {"id": f"{e}-tpcc-fp-before", "kind": "fingerprint", "engine": e, "benchmark": "tpcc",
             "label": f"{e}-tpcc-C-before"},
            # manage_indexes' statistics step leaves ORDER unquoted on Commercial System A and
            # MySQL and fails there (2026-10-09); code/rc_tpcc_stats.py does the same
            # refresh with the script's own quote_table(), on every engine alike
            {"id": f"{e}-tpcc-to-non-indexed", "kind": "index", "engine": e, "benchmark": "tpcc",
             "actions": ["drop"], "expect": "non-indexed"},
            tpcc_stats(e, 'non-indexed'),
            {"id": f"{e}-tpcc-verify-non-indexed", "kind": "index", "engine": e, "benchmark": "tpcc",
             "actions": ["verify"], "expect": "non-indexed"},
            {"id": f"{e}-tpcc-run-non-indexed", "kind": "tpcc", "engine": e,
             "args": {"run_dir": f"C-tpcc/{e}-non-indexed", "protocol": protocol, "phase": "C", "src": "src-c",
                      "schema": "non-indexed", "mode": "main", "blocks": 24}},
            # create ends with the same unquoted statistics call: accept only that
            # warning, require "0 failed", then the quoted refresh and verify
            {"id": f"{e}-tpcc-to-indexed", "kind": "shell",
             "command": (f"source {CAMP}/code/rc_env.sh {e} tpcc && cd $RC_CAMPAIGN/src && "
                         f"out=$(taskset -c 2,3 $RC_PY scripts/1-setup/manage_indexes.py --database default --benchmark tpcc "
                         f"--action create 2>&1); echo \"$out\"; echo \"$out\" | grep -q 'Summary: .* 0 failed'")},
            tpcc_stats(e, 'indexed'),
            {"id": f"{e}-tpcc-verify-indexed", "kind": "index", "engine": e, "benchmark": "tpcc",
             "actions": ["verify"], "expect": "indexed"},
            {"id": f"{e}-tpcc-run-indexed", "kind": "tpcc", "engine": e,
             "args": {"run_dir": f"C-tpcc/{e}-indexed", "protocol": protocol, "phase": "C", "src": "src-c",
                      "schema": "indexed", "mode": "main", "blocks": 24}},
            {"id": f"{e}-tpcc-fp-after", "kind": "shell",
             "command": (f"source {CAMP}/code/rc_env.sh {e} tpcc && cd $RC_CAMPAIGN/src && taskset -c 2,3 $RC_PY "
                         f"$RC_CAMPAIGN/code/rc_fingerprint.py --dbms {e} --benchmark tpcc --label {e}-tpcc-C-after "
                         f"--out $RC_CAMPAIGN/evidence/fingerprints/{e}-tpcc-C-after.json && python3 -c \"import json;"
                         f"a=json.load(open('$RC_CAMPAIGN/evidence/fingerprints/{e}-tpcc-C-before.json'))['content_sha256'];"
                         f"b=json.load(open('$RC_CAMPAIGN/evidence/fingerprints/{e}-tpcc-C-after.json'))['content_sha256'];"
                         f"print('before',a,'after',b);assert a==b\"")},
        ]
    return {"plan_id": "C-tpcc", "purpose": "Phase C: transaction state verification and timing, 80 cells.",
            "protocol": protocol, "steps": steps}


def plan_d(engines, protocol):
    steps = []
    for e in engines:
        pre = lambda s: {"id": f"{e}-sf2-preflight-{s}", "kind": "shell",
                         "command": f"source {CAMP}/code/rc_env.sh {e} tpch 2 && cd $RC_CAMPAIGN/src && taskset -c 2,3 $RC_PY scripts/0-host/preflight.py --dbms {e} --schema {s}"}
        root = {'mysql': ['mysql-sf2-grant'], 'oracle': ['oracle-sf2-user']}.get(e, [])
        steps += [{"id": f"{e}-engine", "kind": "engine", "engine": e, "settle": 90}]
        # Root-only preparation through the fixed-action helper, while this
        # engine is up and nothing is timing (see root-helper/rc-campaign-root).
        steps += [{"id": f"{e}-root-{act}", "kind": "shell",
                   "command": f"sudo -n /usr/local/sbin/rc-campaign-root {act}"} for act in root]
        steps += [
            {"id": f"{e}-sf2-load", "kind": "shell",
             "command": (f"source {CAMP}/code/rc_env.sh {e} tpch 1 && cd $RC_CAMPAIGN/src && taskset -c 2,3 $RC_PY "
                         f"$RC_CAMPAIGN/code/rc_sf2_setup.py --engine {e} --duckdb $RC_CAMPAIGN/datasets/tpch2.duckdb "
                         f"--out $RC_CAMPAIGN/evidence/sf2-setup --create --load --check")},
            {"id": f"{e}-sf2-fp-before", "kind": "fingerprint", "engine": e, "scale": 2, "label": f"{e}-sf2-D-before",
             "expect_source": "sf2-duckdb-source-v2.json"},
            {"id": f"{e}-sf2-to-non-indexed", "kind": "index", "engine": e, "scale": 2,
             "actions": ["analyze", "verify"], "expect": "non-indexed"},
            pre('non-indexed'),
            {"id": f"{e}-sf2-run-non-indexed", "kind": "run", "engine": e, "resumable": True,
             "args": {"run_dir": f"D-sf2/{e}-non-indexed", "protocol": protocol, "phase": "D", "schema": "non-indexed",
                      "scale": 2, "database_label": "tpch_sf2", "mode": "main", "queries": d_queries(e, 'non-indexed')}},
            {"id": f"{e}-sf2-verify-non-indexed", "kind": "verify", "run_dir": f"D-sf2/{e}-non-indexed"},
            {"id": f"{e}-sf2-to-indexed", "kind": "index", "engine": e, "scale": 2, "actions": ["create", "verify"],
             "expect": "indexed"},
            pre('indexed'),
            {"id": f"{e}-sf2-run-indexed", "kind": "run", "engine": e, "resumable": True,
             "args": {"run_dir": f"D-sf2/{e}-indexed", "protocol": protocol, "phase": "D", "schema": "indexed",
                      "scale": 2, "database_label": "tpch_sf2", "mode": "main", "queries": d_queries(e, 'indexed')}},
            {"id": f"{e}-sf2-verify-indexed", "kind": "verify", "run_dir": f"D-sf2/{e}-indexed"},
            {"id": f"{e}-sf2-fp-after", "kind": "fingerprint", "engine": e, "scale": 2, "label": f"{e}-sf2-D-after",
             "expect_source": "sf2-duckdb-source-v2.json"},
        ]
    return {"plan_id": "D-sf2", "purpose": "Phase D: SF2 subset Q6/Q17/Q18/Q20/Q21 except SF1 host-censored cells, 70 cells.", "protocol": protocol,
            "steps": steps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['C', 'D'])
    ap.add_argument('--protocol', required=True)
    ap.add_argument('--engines', nargs='+', default=['sqlserver', 'postgresql', 'mysql', 'oracle'])
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    p = plan_c(a.engines, a.protocol) if a.phase == 'C' else plan_d(a.engines, a.protocol)
    a.out.write_text(json.dumps(p, indent=1) + '\n')
    print(a.out, len(p['steps']), 'steps')


if __name__ == '__main__':
    main()
