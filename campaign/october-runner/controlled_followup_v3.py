"""Fresh four-path diagnostic: preserve historical sources and all returned values.

Run from the benchmark checkout with Python 3.12 and its retained packages.
This is a follow-up on the current OS, never a replacement for historical rows.
"""
import argparse
import csv
from collections import Counter
import datetime as dt
from decimal import Decimal
import hashlib
import fcntl
import json
import os
from pathlib import Path
import random
import runpy
import subprocess
import sys
import time
import traceback
import uuid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dbms', choices=['oracle', 'sqlserver'], required=True)
    ap.add_argument('--schema', choices=['indexed', 'non-indexed'], required=True)
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--collector', type=Path, required=True)
    ap.add_argument('--prepare-only', action='store_true')
    args = ap.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise RuntimeError('Use a fresh output directory; existing evidence must be preserved')
    args.out.mkdir(parents=True, exist_ok=True)
    run_lock = (args.out.parent / 'controlled-followup.lock').open('a+')
    fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.environ['TPCH_SF'] = '1'
    # The current Oracle instance uses a lowercase process suffix after reboot.
    os.environ['ORACLE_SID'] = 'free'
    original_argv = sys.argv[:]
    sys.argv = [str(args.collector), '--dbms', args.dbms, '--schema', args.schema,
                '--out', str(args.out / 'inventory'), '--inventory']
    helper = runpy.run_path(str(args.collector))
    sys.argv = original_argv
    typed = helper['typed']
    connection = helper['connection']
    from django_app.queries import get_query_module_for_db
    import tpch_paramsets

    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(path.name + '.pending')
        pending.write_text(json.dumps(typed(value), indent=2) + '\n')
        pending.replace(path)

    def digest(value):
        return hashlib.sha256(json.dumps(typed(value), sort_keys=True).encode()).hexdigest()

    connection.ensure_connection()
    if args.dbms == 'oracle':
        connection.connection.call_timeout = 1800000
    else:
        connection.connection.timeout = 1800
    meta = helper['inventory']()
    meta['os_release'] = Path('/etc/os-release').read_text()
    meta['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    meta['followup_id'] = str(uuid.uuid4())
    meta['scope'] = 'Fresh diagnostic follow-up; current OS; not historical environment binding'
    save(args.out / 'inventory.json', meta)
    assert meta['row_counts_match_sf1'] and not meta['source_mismatches']
    assert meta['client_cpus'] == [2, 3]
    assert meta['host_verification']['returncode'] == 0, meta['host_verification']
    verification = subprocess.run([sys.executable, 'scripts/1-setup/manage_indexes.py',
                                   '--database', args.dbms, '--action', 'verify',
                                   '--expect', args.schema], text=True, capture_output=True)
    save(args.out / 'index-verification.json', vars(verification))
    assert verification.returncode == 0, verification.stdout + verification.stderr
    environment_hash = digest(meta)

    class Captured(Exception):
        pass

    def capture_statement(fn):
        captured = []
        def intercept(execute, sql, params, many, context):
            assert not many and sql.lstrip().upper().startswith('SELECT')
            captured.append((sql, params))
            raise Captured()
        try:
            with connection.execute_wrapper(intercept):
                fn()
        except Captured:
            pass
        assert len(captured) == 1
        return captured[0]

    def handwritten_bound(q, literal, p):
        # Exact textual substitutions in the retained baseline. No join,
        # aggregation, grouping, ordering, projection, or limit is changed.
        replacements = {
            17: [('7.0', Decimal('7.0')), ("'" + p.get('brand', '') + "'", p.get('brand')),
                 ("'" + p.get('container', '') + "'", p.get('container')), ('0.2', Decimal('0.2'))],
            20: [("'" + p.get('color', '') + "%'", p.get('color', '') + '%'), ('0.5', Decimal('0.5')),
                 ("TO_DATE('" + str(p.get('date')) + "', 'YYYY-MM-DD')", p.get('date')),
                 ("TO_DATE('" + str(p.get('date_end')) + "', 'YYYY-MM-DD')", p.get('date_end')),
                 ("'" + p.get('nation', '') + "'", p.get('nation'))],
            18: [('> ' + str(p.get('quantity')), Decimal(p.get('quantity')))],
        }[q]
        text = literal
        located = []
        for old, value in replacements:
            assert text.count(old) == 1, (q, old, text.count(old))
            pos = text.index(old)
            located.append((pos, old, value))
        bound = []
        for pos, old, value in sorted(located, reverse=True):
            replacement = '> %s' if q == 18 else '%s'
            text = text[:pos] + replacement + text[pos + len(old):]
            bound.insert(0, value)
        return text, tuple(bound)

    plans = {}
    for q in args.queries:
        assert (args.dbms, args.schema, q) in [('oracle', 'non-indexed', 17),
            ('oracle', 'non-indexed', 20), ('sqlserver', 'indexed', 18)]
        module = get_query_module_for_db(q, args.dbms)
        for index in range(8):
            p = tpch_paramsets.params_of(q, index)
            generated = capture_statement(lambda: module.run_query_orm(using='default', params=p))
            literal = capture_statement(lambda: module.run_query_sql(connection, params=p))
            assert literal[1] is None or not literal[1]
            bound = handwritten_bound(q, literal[0], p)
            signature = lambda values: Counter(json.dumps(typed(v), sort_keys=True) for v in values)
            assert signature(generated[1]) == signature(bound[1]), ('Binding values/types differ', q, index)
            plans[q, index] = (module, p, {'generated': generated, 'bound': bound, 'literal': literal})
            save(args.out / f'q{q:02d}-set{index}-statements.json',
                 {'query': q, 'parameter_set': index, 'parameters': p,
                  'statements': plans[q, index][2], 'environment_sha256': environment_hash})
    print('PREPARED', len(plans), 'query/input combinations; source and environment gates passed', flush=True)
    if args.prepare_only:
        connection.close()
        return

    paths = ['orm', 'generated', 'bound', 'literal']
    williams = [(0, 1, 2, 3), (1, 3, 0, 2), (3, 2, 1, 0), (2, 0, 3, 1)]
    protocol = {'paths': paths, 'williams': williams, 'cycles': 2,
                'warmup': 'One execution per path with qualification input, excluded from estimates',
                'blocks': 'Eight matched input sets; two seeded permutations of four Williams sequences',
                'time_scope': 'Function call for ORM; cursor execute, full fetch, and named dictionaries for direct paths',
                'validation': 'Complete returned rows, named columns, duplicate counts and order; exact values; no rounding',
                'interpretation': 'ORM versus generated direct includes ORM construction/materialization. Generated versus handwritten bound compares formulations with bound values through the same Django backend. Literal versus bound is a separate interface control. Native result representation can still differ and is retained.',
                'environment_sha256': environment_hash, 'seed': 20261007}
    save(args.out / 'protocol.json', protocol)
    report = []
    progress = {'pid': os.getpid(), 'followup_id': meta['followup_id'],
                'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'planned_timed_executions': len(args.queries) * 8 * 4,
                'planned_query_input_checks': len(args.queries) * 8,
                'completed_timed_executions': 0, 'accepted_timed_executions': 0,
                'passed_query_input_checks': 0}
    def update_progress(**updates):
        progress.update(updates, updated_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        save(args.out / 'progress.json', progress)
    for q in args.queries:
        rng = random.Random(20261007 + q)
        orders = []
        for _ in range(2):
            cycle = list(range(4)); rng.shuffle(cycle); orders.extend(cycle)
        for block in range(-1, 8):
            index = max(0, block)
            module, p, statements = plans[q, index]
            order = list(range(4)) if block == -1 else williams[orders[block]]
            outputs = {}
            for position, path_index in enumerate(order):
                path = paths[path_index]
                trace = []
                def trace_statement(execute, sql, params, many, context):
                    trace.append({'sql': sql, 'params': params, 'many': many})
                    return execute(sql, params, many, context)
                entry = {'followup_id': meta['followup_id'], 'environment_sha256': environment_hash,
                         'query': q, 'schema': args.schema, 'dbms': args.dbms,
                         'block': block, 'position': position, 'path': path,
                         'parameter_set_id': tpch_paramsets.set_id(q, index), 'parameters': p,
                         'utc': dt.datetime.now(dt.timezone.utc).isoformat()}
                update_progress(state='running', query=q, block=block, path=path,
                                parameter_set=index, warmup=(block == -1))
                print('START', q, block, path, 'warmup' if block == -1 else 'timed', flush=True)
                started = time.perf_counter()
                try:
                    with connection.execute_wrapper(trace_statement):
                        if path == 'orm':
                            rows = module.run_query_orm(using='default', params=p)
                        else:
                            sql, bound = statements[path]
                            with connection.cursor() as cursor:
                                cursor.execute(sql, bound)
                                names = [d[0] for d in cursor.description]
                                assert len(set(n.lower() for n in names)) == len(names)
                                rows = [dict(zip(names, r)) for r in cursor.fetchall()]
                    entry['elapsed_s'] = time.perf_counter() - started
                    entry.update(status='ok', rows=rows, statements=trace)
                    outputs[path] = rows
                    if path in ['orm', 'generated']:
                        assert len(trace) == 1
                        assert trace[0]['sql'] == statements['generated'][0]
                        assert typed(trace[0]['params']) == typed(statements['generated'][1])
                except Exception:
                    entry.update(status='error', elapsed_s=time.perf_counter()-started,
                                 error=traceback.format_exc(), statements=trace)
                    save(args.out / f'q{q:02d}-block{block}-{path}.json', entry)
                    update_progress(state='error', error=entry['error'])
                    raise
                entry['result_sha256'] = digest(rows)
                save(args.out / f'q{q:02d}-block{block}-{path}.json', entry)
                if block >= 0:
                    progress['completed_timed_executions'] += 1
                update_progress(state='running')
                print('DONE', q, block, path, round(entry['elapsed_s'], 3), len(rows), flush=True)
            comparisons = {path: helper['compare'](outputs['literal'], outputs[path]) for path in paths}
            item = {'query': q, 'block': block, 'parameter_set': index, 'comparisons': comparisons}
            report.append(item)
            save(args.out / 'validation.json', report)
            print('CHECK', q, block, {k:v['exact_named_ordered_equal'] for k,v in comparisons.items()}, flush=True)
            if not all(v['exact_named_ordered_equal'] for v in comparisons.values()):
                save(args.out / 'needs-review.json', item)
                update_progress(state='result_mismatch')
                raise RuntimeError('Result mismatch: retained for review; no further timing is justified yet')
            if block >= 0:
                progress['passed_query_input_checks'] += 1
                progress['accepted_timed_executions'] += 4
            update_progress(state='block_validated')
    end = helper['inventory']()
    save(args.out / 'inventory-after.json', end)
    assert end['source_hashes'] == meta['source_hashes']
    assert end['indexes'] == meta['indexes']
    assert end['host_verification']['returncode'] == 0
    save(args.out / 'completion.json', {'completed_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                                      'all_exact_named_ordered_checks_pass':True,
                                      'query_input_checks':len(report), 'historical_rows_replaced':False})
    update_progress(state='complete')
    connection.close()


if __name__ == '__main__':
    main()
