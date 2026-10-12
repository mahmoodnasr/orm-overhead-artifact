#!/usr/bin/env python3
"""Commercial System A state probe for the phase E open item (decision log 2026-10-11 20:45).

E measured Commercial System A non-indexed after a 2.5 h indexed workload on the same
instance (indexes dropped in between, no restart); A measured it on a freshly
started engine. E's full scans were 2.3-3.8x slower. This probe records, at
one moment, what the server's memory holds and how the non-indexed scans run:

  * process and system memory (<catalogue view>, <catalogue view>),
    the top memory clerks, and the buffer pool by table (<catalogue view>);
  * the hand-written SQL of the given queries on input set 0, --repeat calls each,
    through the runner's own query functions and connections, with elapsed time
    and, from <catalogue view>, the last call's elapsed, worker (CPU) time,
    logical and physical reads.
With --workload it instead runs all four paths of the given queries --repeat
times (the indexed workload of the reproduction) and records only timings.
Evidence, not measurements. Usage:
  python code/rc_commercial_a_probe.py --campaign-dir <dir> --label <name> --queries 6 17 20 21 --out <json>
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

MEM_SQL = {
    'process': "SELECT physical_memory_in_use_kb, locked_page_allocations_kb, memory_utilization_percentage, "
               "process_physical_memory_low, process_virtual_memory_low FROM sys.dm_os_process_memory",
    'system': "SELECT total_physical_memory_kb, available_physical_memory_kb, system_memory_state_desc "
              "FROM sys.dm_os_sys_memory",
    'config': "SELECT name, CAST(value_in_use AS bigint) AS v FROM sys.configurations "
              "WHERE name IN ('max server memory (MB)','min server memory (MB)','max degree of parallelism')",
    'clerks': "SELECT TOP 8 type, SUM(pages_kb) AS pages_kb FROM sys.dm_os_memory_clerks GROUP BY type ORDER BY 2 DESC",
    'buffer_pool_by_table': (
        "SELECT o.name AS table_name, COUNT(*) * 8 / 1024 AS mb FROM sys.dm_os_buffer_descriptors bd "
        "JOIN sys.allocation_units au ON bd.allocation_unit_id = au.allocation_unit_id "
        "JOIN sys.partitions p ON au.container_id = p.hobt_id JOIN sys.objects o ON p.object_id = o.object_id "
        "WHERE bd.database_id = DB_ID() AND o.is_ms_shipped = 0 GROUP BY o.name ORDER BY 2 DESC"),
    'buffer_pool_total_mb': "SELECT COUNT(*) * 8 / 1024 AS mb FROM sys.dm_os_buffer_descriptors",
}
STATS_SQL = ("SELECT TOP 1 qs.last_elapsed_time, qs.last_worker_time, qs.last_logical_reads, qs.last_physical_reads, "
             "qs.execution_count FROM sys.dm_exec_query_stats qs CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st "
             "WHERE st.text LIKE ? ORDER BY qs.last_execution_time DESC")


def rows(cur):
    names = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(names, r)) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--repeat', type=int, default=3)
    ap.add_argument('--workload', action='store_true')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    camp, out_path = a.campaign_dir.resolve(), a.out.resolve()
    if out_path.exists():
        raise SystemExit(f'{out_path} exists')
    src = Path(os.environ.get('RC_SRC') or camp / 'src').resolve()
    inputs = C.load(camp / 'inputs-tpch.json')
    os.chdir(src)
    sys.path.insert(0, str(src))
    import django
    django.setup()
    from django.db import connections
    from django_app.queries import get_query_module_for_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    dconn = connections['default']
    engine = create_engine(os.environ['SA_DSN'], future=True)
    session = sessionmaker(bind=engine, future=True)()
    rec = {'label': a.label, 'mode': 'workload' if a.workload else 'probe', 'started': C.stamps(), 'calls': []}

    def memory():
        with dconn.cursor() as c:
            c.execute('SELECT 1')
        rc = dconn.connection.cursor()
        out = {}
        for k, sql in MEM_SQL.items():
            rc.execute(sql)
            out[k] = rows(rc)
        rc.close()
        return out
    if not a.workload:
        rec['memory_before'] = memory()
    for q in a.queries:
        params = inputs['queries'][str(q)]['sets'][0]
        dj = get_query_module_for_db(q, 'default')
        sa = importlib.import_module(f'sqlalchemy_app.queries.q{q:02d}')
        paths = [('django/sql', lambda: dj.run_query_sql(dconn, params=params))]
        if a.workload:
            paths += [('django/orm', lambda: dj.run_query_orm(using='default', params=params)),
                      ('sqlalchemy/sql', lambda: sa.run_query_sql(session, params=params)),
                      ('sqlalchemy/orm', lambda: sa.run_query_orm(session, params=params))]
        for path, fn in paths:
            for i in range(a.repeat):
                t = time.perf_counter()
                res = fn()
                el = time.perf_counter() - t
                call = {'query': q, 'path': path, 'call': i + 1, 'elapsed_s': el, 'rows': len(res)}
                if not a.workload:
                    rc = dconn.connection.cursor()
                    rc.execute(STATS_SQL, '%FROM lineitem%' if q != 21 else '%l3.l_receiptdate%')
                    st = rows(rc)
                    rc.close()
                    call['server'] = st[0] if st else None
                rec['calls'].append(call)
                s = call.get('server') or {}
                print(f"Q{q:02d} {path:15s} call {i + 1} {el:8.3f} s  physical_reads {s.get('last_physical_reads')} "
                      f"logical_reads {s.get('last_logical_reads')} cpu_ms {round((s.get('last_worker_time') or 0) / 1000)}",
                      flush=True)
    if not a.workload:
        rec['memory_after'] = memory()
        bp = rec['memory_after']['buffer_pool_by_table'][:4]
        print('buffer pool by table (MB):', [(r['table_name'], r['mb']) for r in bp],
              '| total MB', rec['memory_after']['buffer_pool_total_mb'][0]['mb'],
              '| process MB', rec['memory_after']['process'][0]['physical_memory_in_use_kb'] // 1024)
    rec['finished'] = C.stamps()
    session.close()
    engine.dispose()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'x') as fh:
        fh.write(json.dumps(C.typed(rec), indent=1, default=str) + '\n')
    print('->', out_path)


if __name__ == '__main__':
    main()
