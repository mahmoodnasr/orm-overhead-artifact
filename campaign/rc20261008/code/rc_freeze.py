#!/usr/bin/env python3
"""Freeze the inputs and an analytical protocol before any execution that uses them.

Writes, once (refuses to overwrite):
  inputs-tpch.json     the warmup instance and the eight saved parameter sets of
                       every TPC-H query, exactly as tpch_paramsets generates
                       them; set 0 is the qualification instance (Q18: 300),
                       sets 1-7 the seeded substitutions (Q18: 312-315).
  protocols/<id>.json  the protocol: design, ceilings, acceptance policy,
                       expected counts, the source snapshot and the predicted
                       per-cell wall time from the historical SF1 rows (for the
                       ETA only - never for acceptance).
"""
import argparse
import ast
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

SF_COUNTS = {
    '1': {'region': 5, 'nation': 25, 'supplier': 10000, 'customer': 150000, 'part': 200000,
          'partsupp': 800000, 'orders': 1500000, 'lineitem': 6001215},
}


def secondary_indexes(src):
    tree = ast.parse((src / 'scripts/1-setup/manage_indexes.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'INDEXES' for t in node.targets):
            d = ast.literal_eval(node.value)
            return sorted(i.lower() for v in d.values() for i in v)
    raise SystemExit('INDEXES not found')


def predicted(hist_dir):
    out = defaultdict(dict)
    for f in sorted(Path(hist_dir).glob('*_indexed.csv')) + sorted(Path(hist_dir).glob('*_non_indexed.csv')):
        if 'tpcc' in f.name:
            continue
        acc = defaultdict(float)
        with open(f) as fh:
            for r in csv.DictReader(fh):
                try:
                    acc[(r['dbms'], r['schema_config'], int(r['query_id'][1:]))] += float(r['elapsed_s'])
                except (ValueError, KeyError):
                    pass
        for (d, s, q), v in acc.items():
            out[f'{d}:{s}'][str(q)] = round(v, 1)
    return dict(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, required=True)
    ap.add_argument('--protocol-id', required=True)
    ap.add_argument('--phase', required=True)
    ap.add_argument('--historical-measurements', type=Path, required=True)
    ap.add_argument('--fingerprint', type=Path, action='append', default=[],
                    help='source-data fingerprint JSON(s); scale label taken from its label')
    ap.add_argument('--notes', default='')
    ap.add_argument('--policy', default=C.POLICY_VERSION)
    ap.add_argument('--runner-files', nargs='+', default=['rc_analytical.py', 'rc_common.py'])
    a = ap.parse_args()
    camp = a.campaign_dir.resolve()
    src = camp / 'src'
    sys.path.insert(0, str(src))
    import tpch_paramsets as tp
    inputs_path = camp / 'inputs-tpch.json'
    inputs = {'generator': 'tpch_paramsets', 'seed': tp.SEED, 'n_sets': tp.N_SETS,
              'generator_sha256': C.file_sha256(src / 'tpch_paramsets.py'),
              'note': 'Set 0 is the TPC-H qualification instance; sets 1-7 seeded substitutions. '
                      'Q18 set 0 = 300 (qualification), sets 1-7 drawn from 312-315.',
              'queries': {str(q): {'warmup': tp.warmup_params(q),
                                   'sets': [tp.params_of(q, i) for i in range(8)],
                                   'set_ids': [tp.set_id(q, i) for i in range(8)]} for q in range(1, 23)}}
    if not inputs_path.exists():
        C.save(inputs_path, inputs, immutable=True)
    else:
        assert C.digest(C.load(inputs_path)) == C.digest(inputs), 'inputs-tpch.json differs from generator'
    fps = {}
    for f in a.fingerprint:
        j = json.loads(f.read_text())
        fps[j['label']] = {'content_sha256': j['content_sha256'], 'file': f.name,
                           'rows': {t: v['rows'] for t, v in j['tables'].items()}}
    hashes = {}
    for folder in ('django_app', 'sqlalchemy_app'):
        for p in sorted((src / folder).rglob('*.py')):
            hashes[str(p.relative_to(src))] = C.file_sha256(p)
    for name in ('tpch_paramsets.py', 'tpch_params.py', 'tpch_domains.py', 'settings_mysql.py', 'settings_oracle.py',
                 'settings_sqlserver.py', 'odbc_driver.py', 'mssql_decimal_fix.py', 'scripts/1-setup/manage_indexes.py'):
        if (src / name).exists():
            hashes[name] = C.file_sha256(src / name)
    counts = dict(SF_COUNTS)
    for label, v in fps.items():
        if label.startswith('sf'):
            counts[label[2:]] = v['rows']
    dataset_ids = {}
    for d in ('postgresql', 'mysql', 'oracle', 'sqlserver'):
        for label, v in fps.items():
            if label.startswith('sf'):
                dataset_ids[f'{d}:{label}'] = f'tpch-{label}:{v["content_sha256"]}'
    proto = {
        'campaign_id': 'rc20261008', 'protocol_id': a.protocol_id, 'phase': a.phase,
        'frozen': C.stamps(), 'notes': a.notes,
        'inputs_file': inputs_path.name, 'inputs_sha256': C.file_sha256(inputs_path),
        'expected_row_counts': counts, 'secondary_indexes': secondary_indexes(src),
        'runner_code_sha256': {n: C.file_sha256(HERE / n) for n in a.runner_files},
        'source_hashes': hashes, 'source_commit': 'revision-campaign-20261008 @ 5080006 (worktree src/)',
        'dataset_ids': dataset_ids, 'source_fingerprints': fps,
        'predicted_cell_seconds': predicted(a.historical_measurements),
        'design': {
            'paths': list(C.PATHS), 'williams': C.WILLIAMS, 'blocks': 8,
            'block_plan': 'two seeded permutations of the four Williams sequences; seed = first 64 bits of '
                          'sha256("<protocol_id>:<dbms>:<schema>:sf<scale>:<database_label>:q<n>")',
            'cell_warmup': 'one sequence (Williams seed mod 4) on the ninth parameter instance; recorded, never timed',
            'block_warmup': 'each non-skipped path once on the block parameters before the timed sequence; recorded',
            'censoring': 'a path that times out in the cell warmup is skipped for the cell and recorded as '
                         'censored_in_cell_warmup on every block; a timed-call timeout is recorded and the '
                         'next block tries again (historical behaviour)',
            'no_2700s_retry': 'Historical campaigns retried a censored cell once at 2700 s. Not repeated here '
                              'within the main phase; censored cells are handled in phase B with an explicit budget.',
        },
        'ceilings': {'per_call_s': 900, 'postgresql': 'SET statement_timeout, read back',
                     'mysql': 'SET SESSION max_execution_time, read back',
                     'sqlserver': 'pyodbc connection.timeout on both connections, read back',
                     'oracle': 'oracledb call_timeout on both connections, read back'},
        'timer': 'time.perf_counter around run_query_sql/run_query_orm, which return the complete '
                 'materialised list of rows; statement-capture hooks (one list append per statement) are '
                 'inside the timer for all four paths; typing, hashing, comparison and disk writes are outside.',
        'after_failure': 'rollback, close both frameworks connections, poll the server until the old session '
                         'shows no running request (60 s), kill if needed, re-arm and read back the ceiling; '
                         'stop the run if stopping cannot be shown.',
        'result_policy': {'version': a.policy, 'text': C.__doc__,
                          'accepted_classes': list(C.ACCEPTED_CLASSES),
                          'order_keys': C.ORDER_KEYS, 'limits': C.LIMITS, 'expected_columns': C.EXPECTED,
                          'aliases': C.ALIASES},
        'acceptance': 'Per block and framework: both timed calls ok, the ORM result accepted against the same '
                      'framework SQL result under the result policy, and the ORM path check passed (ORM-built '
                      'statement, no text() literal, not the handwritten statement). Written once as decision.json '
                      'after the block. Cross-framework comparisons (Django SQL vs SQLAlchemy SQL, ORM vs ORM) '
                      'are recorded and reviewed, not acceptance conditions. A hard mismatch stops the cell for '
                      'diagnosis; limit_boundary_tie is held for review without stopping.',
        'expected_counts_per_query_cell': {'timed_calls': 32, 'block_warmups': 32, 'cell_warmups': 4,
                                           'framework_pairs': 16},
    }
    out = camp / 'protocols' / f'{a.protocol_id}.json'
    if out.exists():
        sys.exit(f'{out} exists; a changed protocol needs a new id')
    C.save(out, proto, immutable=True)
    print(out, C.file_sha256(out))


if __name__ == '__main__':
    main()
