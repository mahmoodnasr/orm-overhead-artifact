"""B8 diagnostic capture. Run from the unchanged benchmark checkout."""
import argparse
import csv
import datetime as dt
from decimal import Decimal
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
AP = argparse.ArgumentParser()
AP.add_argument('--dbms', choices=['sqlserver', 'oracle'], required=True)
AP.add_argument('--out', type=Path, required=True)
AP.add_argument('--query', type=int, choices=[17, 18, 20])
AP.add_argument('--set', type=int, default=0)
AP.add_argument('--inventory', action='store_true')
AP.add_argument('--reuse-warmup-from', type=Path)
AP.add_argument('--schema', choices=['indexed', 'non-indexed'], required=True)
A = AP.parse_args()
A.out.mkdir(parents=True, exist_ok=True)
os.environ['TPCH_SF'] = '1'
os.environ['QUERY_TIMEOUT'] = '1800'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings_' + A.dbms)
import django
django.setup()
from django.db import connection
import tpch_paramsets


def typed(x):
    if x is None or isinstance(x, (str, bool, int)):
        return x
    if isinstance(x, dict):
        return {str(k): typed(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [typed(v) for v in x]
    if isinstance(x, (Decimal, float, dt.datetime, dt.date)):
        return {'type': type(x).__name__, 'value': str(x)}
    if hasattr(x, 'getvalue'):
        return {'type': type(x).__name__, 'value': typed(x.getvalue())}
    return {'type': type(x).__name__, 'value': str(x)}


def write(name, value):
    (A.out / name).write_text(json.dumps(typed(value), indent=2) + '\n')


def run(args):
    p = subprocess.run(args, text=True, capture_output=True)
    return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}


def query(sql, params=None):
    with connection.cursor() as c:
        c.execute(sql, params)
        names = [d[0].lower() for d in c.description]
        return [dict(zip(names, r)) for r in c.fetchall()]


def safe_query(sql):
    try:
        return query(sql)
    except Exception as e:
        return {'error': str(e)}


def inventory():
    expected_file = Path(__file__).with_name('paper-source-hashes.json')
    expected = json.loads(expected_file.read_text())
    actual = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
              if (ROOT / p).is_file() else None for p in expected}
    result = {
        'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'host': platform.node(), 'platform': platform.platform(),
        'python': sys.version, 'client_cpus': sorted(os.sched_getaffinity(0)),
        'git_head': run(['git', 'rev-parse', 'HEAD']),
        'git_status': run(['git', 'status', '--short']),
        'source_hashes': actual,
        'source_mismatches': [p for p in expected if actual[p] != expected[p]],
        'capture_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'versions': {p: importlib.metadata.version(p) for p in
                     ['Django', 'SQLAlchemy', 'pyodbc', 'oracledb', 'mssql-django']},
        'host_verification': run(['sudo', '-n', '/usr/local/sbin/bench-host', 'verify', A.dbms]),
        'storage': run(['findmnt', '-T', '/opt/oracle' if A.dbms == 'oracle' else '/var/opt/mssql']),
        'scale_factor': 1, 'schema_requested': A.schema,
    }
    tables = ['region', 'nation', 'supplier', 'customer', 'part', 'partsupp', 'orders', 'lineitem']
    expected_counts = [5, 25, 10000, 150000, 200000, 800000, 1500000, 6001215]
    result['row_counts'] = {t: query('SELECT COUNT(*) AS n FROM ' + t)[0]['n'] for t in tables}
    result['row_counts_match_sf1'] = list(result['row_counts'].values()) == expected_counts
    if A.dbms == 'sqlserver':
        result['server'] = query('SELECT @@VERSION AS version, DB_NAME() AS database_name, @@SPID AS session_id')
        result['indexes'] = query('SELECT t.name AS table_name,i.name AS index_name,i.type_desc,i.is_primary_key,i.is_disabled,c.name AS column_name,ic.key_ordinal,ic.is_included_column FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.index_id>0 ORDER BY t.name,i.name,ic.index_column_id')
        result['settings'] = query("SELECT name,CAST(value_in_use AS bigint) AS value FROM sys.configurations WHERE name IN ('max degree of parallelism','max server memory (MB)','cost threshold for parallelism')")
        result['database_settings'] = query('SELECT compatibility_level,collation_name,recovery_model_desc,is_auto_create_stats_on,is_auto_update_stats_on FROM sys.databases WHERE name=DB_NAME()')
        result['statistics'] = query('SELECT t.name AS table_name,s.name AS statistics_name,p.last_updated,p.rows,p.rows_sampled,p.modification_counter FROM sys.stats s JOIN sys.tables t ON t.object_id=s.object_id OUTER APPLY sys.dm_db_stats_properties(s.object_id,s.stats_id) p ORDER BY t.name,s.name')
        result['session_options'] = query('DBCC USEROPTIONS')
    else:
        result['server'] = safe_query('SELECT banner_full FROM v$version')
        result['indexes'] = query('SELECT i.table_name,i.index_name,i.index_type,i.uniqueness,i.status,c.column_name,c.column_position FROM user_indexes i JOIN user_ind_columns c ON c.index_name=i.index_name ORDER BY i.table_name,i.index_name,c.column_position')
        result['settings'] = safe_query("SELECT name,value FROM v$parameter WHERE name IN ('sga_target','pga_aggregate_target','cpu_count','parallel_degree_policy','result_cache_mode','statistics_level','optimizer_features_enable')")
        result['statistics'] = query('SELECT table_name,num_rows,last_analyzed,sample_size FROM user_tables ORDER BY table_name')
        result['plan_access'] = {view: safe_query('SELECT COUNT(*) AS n FROM ' + view + ' WHERE 1=0') for view in ['v$session','v$sql','v$sql_plan','v$sql_plan_statistics_all']}
    return result


ACTIVE = None


class DriverTrace:
    """Delegate without changing driver execution or parameter conversion."""
    def __init__(self, cursor):
        object.__setattr__(self, '_raw', cursor)

    def execute(self, statement, *args, **kwargs):
        if ACTIVE is not None:
            ACTIVE['driver_statements'].append({'sql': statement, 'args': typed(args), 'kwargs': typed(kwargs)})
        self._raw.execute(statement, *args, **kwargs)
        return self

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def __setattr__(self, name, value):
        setattr(self._raw, name, value)

    def __iter__(self):
        return iter(self._raw)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def install_trace():
    original = connection.create_cursor
    def create(name=None):
        c = original(name)
        c.cursor = DriverTrace(c.cursor)
        return c
    connection.create_cursor = create


def normalize_value(v):
    if isinstance(v, dt.datetime):
        assert v.time() == dt.time(), 'Non-midnight datetime cannot be normalized as date'
        return v.date()
    return v


def comparable(rows):
    return [{str(k).lower(): normalize_value(v) for k, v in row.items()} for row in rows]


def compare(left, right):
    l, r = comparable(left), comparable(right)
    differences = []
    if len(l) != len(r):
        differences.append({'row_count': [len(l), len(r)]})
    for i, (x, y) in enumerate(zip(l, r)):
        if x.keys() != y.keys():
            differences.append({'row': i, 'columns': [list(x), list(y)]})
            continue
        for k in x:
            a, b = x[k], y[k]
            if a != b:
                differences.append({'row': i, 'column': k, 'left': a, 'right': b})
    return {'exact_named_ordered_equal': not differences, 'rows': [len(l), len(r)],
            'differences': differences, 'normalization': 'column-name case; midnight datetime to date only; no value sorting or rounding'}


def execute_function(module, path, params, label):
    global ACTIVE
    api = []
    driver = {'driver_statements': []}
    def wrapper(execute, sql, bound, many, context):
        api.append({'sql': sql, 'params': bound, 'many': many})
        return execute(sql, bound, many, context)
    ACTIVE = driver
    start = time.perf_counter()
    try:
        with connection.execute_wrapper(wrapper):
            rows = (module.run_query_orm(using='default', params=params) if path == 'orm'
                    else module.run_query_sql(connection, params=params))
        record = {'label': label, 'elapsed_s': time.perf_counter()-start, 'api_statements': api,
                  **driver, 'rows': rows, 'utc': dt.datetime.now(dt.timezone.utc).isoformat()}
        write(label+'.json', record)
        print(label, 'completed', round(record['elapsed_s'], 3), 's', len(rows), 'rows', flush=True)
        return record
    finally:
        ACTIVE = None


def capture_commercial(warm, label):
    global ACTIVE
    assert len(warm['api_statements']) == 1, 'This follow-up expects one SQL statement per path'
    statement = warm['api_statements'][0]
    trace = {'driver_statements': []}
    start = time.perf_counter()
    try:
        with connection.cursor() as c:
            # Keep SET and SELECT on the same cursor. MARS logical sessions
            # can otherwise discard the SET state when its cursor closes.
            c.execute('SET STATISTICS XML ON')
            ACTIVE = trace
            c.execute(statement['sql'], statement['params'])
            columns = [x[0] for x in c.description]
            rows = [dict(zip(columns, r)) for r in c.fetchall()]
            plans = []
            while c.nextset():
                if c.description:
                    for r in c.fetchall():
                        for value in r:
                            if isinstance(value, str) and 'ShowPlanXML' in value:
                                ET.fromstring(value)
                                plans.append(value)
            ACTIVE = None
            c.execute('SET STATISTICS XML OFF')
        elapsed = time.perf_counter()-start
    finally:
        ACTIVE = None
        with connection.cursor() as c:
            c.execute('SET STATISTICS XML OFF')
    for i, xml in enumerate(plans):
        (A.out/f'{label}-plan-{i}.sqlplan').write_text(xml)
    result = {'elapsed_s': elapsed, **trace, 'rows': rows,
              'same_driver_sql_and_bindings': trace['driver_statements'] == warm['driver_statements'],
              'matches_function_results': compare(warm['rows'], rows),
              'actual_plan_count': len(plans),
              'runtime_counter_count': sum(x.count('RunTimeCountersPerThread') for x in plans),
              'capture': 'same-backend statement replay with original bindings; STATISTICS XML ON'}
    write(label+'.json', result)
    assert result['same_driver_sql_and_bindings'], 'Driver SQL or bindings changed in replay'
    assert result['matches_function_results']['exact_named_ordered_equal'], 'Replay results differ'
    assert result['runtime_counter_count'] > 0, 'Actual plan statistics missing'
    print(label, 'actual plans',len(plans), 'elapsed', round(elapsed,3), flush=True)
    return result


def capture_oracle(module, path, params, label):
    # A cursor cached before statistics_level=ALL retained no runtime counters
    # on this host. A controlled tiny probe reproduced that failure; disabling
    # the client statement cache fixed it without changing SQL or bindings.
    old_cache_size = connection.connection.stmtcachesize
    connection.connection.stmtcachesize = 0
    with connection.cursor() as c:
        c.execute('ALTER SESSION SET statistics_level=ALL')
    result = execute_function(module, path, params, label)
    identity = query("SELECT prev_sql_id AS sql_id,prev_child_number AS child_number FROM v$session WHERE sid=SYS_CONTEXT('USERENV','SID')")[0]
    sql_id, child = identity['sql_id'], identity['child_number']
    source = query('SELECT sql_fulltext FROM v$sql WHERE sql_id=%s AND child_number=%s', [sql_id, child])
    full_sql = source[0]['sql_fulltext']
    if hasattr(full_sql, 'read'):
        full_sql = full_sql.read()
    assert len(result['driver_statements']) == 1
    assert full_sql.strip() == result['driver_statements'][0]['sql'].strip(), 'Plan belongs to another statement'
    text = query("SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(%s,%s,'ALLSTATS LAST +PEEKED_BINDS +PREDICATE +ALIAS +OUTLINE'))", [sql_id, child])
    plan_text = '\n'.join(r['plan_table_output'] for r in text)
    (A.out/(label+'-plan.txt')).write_text(plan_text+'\n')
    operators = query('SELECT id,parent_id,operation,options,object_owner,object_name,cardinality,cost,last_starts,last_output_rows,last_cr_buffer_gets,last_disk_reads,last_elapsed_time FROM v$sql_plan_statistics_all WHERE sql_id=%s AND child_number=%s ORDER BY id', [sql_id, child])
    write(label+'-plan.json', {'identity':identity,'sql':full_sql,'operators':operators})
    assert any(r['last_starts'] for r in operators), 'Runtime operator counters missing'
    result['plan_identity'] = identity
    result['actual_plan_operators'] = len(operators)
    result['instrumentation'] = {'statistics_level':'ALL',
        'client_statement_cache_before':old_cache_size,
        'client_statement_cache_during_capture':0}
    write(label+'.json', result)
    return result


def main():
    connection.ensure_connection()
    if A.dbms == 'oracle':
        connection.connection.call_timeout = 1800000
    else:
        connection.connection.timeout = 1800
    meta = inventory()
    write('inventory.json', meta)
    print('Inventory', A.dbms, 'SF1 counts', meta['row_counts_match_sf1'],
          'source mismatches', len(meta['source_mismatches']), flush=True)
    if A.inventory:
        return
    assert A.query
    assert meta['row_counts_match_sf1']
    assert not meta['source_mismatches']
    assert meta['host_verification']['returncode'] == 0
    assert meta['client_cpus'] == [2, 3]
    if A.dbms == 'oracle':
        missing = [v for v, result in meta['plan_access'].items() if isinstance(result, dict) and 'error' in result]
        assert not missing, 'Runtime plan views are not readable: ' + ', '.join(missing)
    check = run([sys.executable, 'scripts/1-setup/manage_indexes.py', '--database', A.dbms,
                 '--action', 'verify', '--expect', A.schema])
    write('index-verification.json', check)
    assert check['returncode'] == 0, check
    from django_app.queries import get_query_module_for_db
    module = get_query_module_for_db(A.query, A.dbms)
    params = tpch_paramsets.params_of(A.query, A.set)
    hist = ROOT/'results/sf1/measurements'/f'{A.dbms}_{A.schema.replace("-","_")}.csv'
    rows = [r for r in csv.DictReader(hist.open()) if r['query_id'] == f'Q{A.query:02d}'
            and r['param_set_id'] == tpch_paramsets.set_id(A.query,A.set) and r['framework']=='django']
    write('case.json', {'query':A.query,'module':module.__name__,'param_set_id':tpch_paramsets.set_id(A.query,A.set),
                       'parameters':params,'historical_rows':rows,
                       'historical_file_sha256':hashlib.sha256(hist.read_bytes()).hexdigest(),
                       'historical_link_scope':'same retained source, SF1, parameter ID and configuration; fresh run, not recovered historical plan'})
    install_trace()
    if A.reuse_warmup_from:
        assert A.dbms == 'oracle', 'Warmup reuse is only supported for the documented Oracle collector retry'
        prior = A.reuse_warmup_from
        prior_meta = json.loads((prior/'inventory.json').read_text())
        prior_case = json.loads((prior/'case.json').read_text())
        assert prior_meta['source_hashes'] == typed(meta['source_hashes'])
        assert prior_meta['indexes'] == typed(meta['indexes'])
        assert prior_meta['row_counts'] == typed(meta['row_counts'])
        assert prior_case['parameters'] == typed(params) and prior_case['query'] == A.query
        def decode(value):
            if isinstance(value,list): return [decode(v) for v in value]
            if isinstance(value,dict):
                if set(value)=={'type','value'}:
                    constructors={'Decimal':Decimal,'float':float,'date':dt.date.fromisoformat,'datetime':dt.datetime.fromisoformat}
                    assert value['type'] in constructors
                    return constructors[value['type']](value['value'])
                return {k:decode(v) for k,v in value.items()}
            return value
        warm={p:decode(json.loads((prior/('warmup-'+p+'.json')).read_text())) for p in ['sql','orm']}
        for p in ['sql','orm']:
            shutil.copyfile(prior/('warmup-'+p+'.json'),A.out/('warmup-'+p+'.json'))
        write('warmup-provenance.json',{'reused_from':str(prior),
            'reason':'Earlier instrumented run completed but omitted runtime counters; preserve completed warmup and retry collection',
            'source_indexes_counts_parameters_rechecked':True,
            'prior_inventory_sha256':hashlib.sha256((prior/'inventory.json').read_bytes()).hexdigest()})
        print('Reusing verified warmup from',prior,flush=True)
    else:
        warm = {p:execute_function(module,p,params,'warmup-'+p) for p in ['sql','orm']}
    equality = compare(warm['sql']['rows'],warm['orm']['rows'])
    write('warmup-result-comparison.json',equality)
    # Retain plans even if comparison fails; mark the case unresolved.
    captured = {}
    for path in ['orm','sql']:
        captured[path] = (capture_commercial(warm[path],'capture-'+path) if A.dbms=='sqlserver'
                          else capture_oracle(module,path,params,'capture-'+path))
    equality_capture = compare(captured['sql']['rows'],captured['orm']['rows'])
    write('capture-result-comparison.json', equality_capture)
    end_host = run(['sudo','-n','/usr/local/sbin/bench-host','verify',A.dbms])
    write('host-after.json',end_host)
    write('completion.json', {'completed_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
          'plans_captured':True,'warmup_exact_agreement':equality['exact_named_ordered_equal'],
          'capture_exact_agreement':equality_capture['exact_named_ordered_equal'],
          'host_pass':end_host['returncode']==0})
    print('DONE', A.dbms,A.query,'exact agreement',equality_capture['exact_named_ordered_equal'],flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception:
        (A.out/'error.txt').write_text(traceback.format_exc())
        raise
    finally:
        connection.close()
