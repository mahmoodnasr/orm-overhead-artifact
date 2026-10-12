#!/usr/bin/env python3
"""Which plan does Commercial System A choose for the same statements from two clients?

Open item of phase E (decision log, 2026-10-11 16:15): on Commercial System A without
secondary indexes, the hand-written SQL of Q6, Q17 and Q21 ran about 3x slower
from the Mac client (E) than from the host's own client (A) - Q6 1.19 s on the
host, 3.27 s from the Mac, one result row - so the time is spent inside the
server, and the ORM/SQL ratio shrank. Client Python packages and server
settings are identical; the client platform differs (x86_64 host, Linux arm64
container on the Mac), and with it the ODBC driver build.

This script opens connections exactly as the phase A/E runner does (Django's
connections['default']; SQLAlchemy create_engine(SA_DSN, future=True) with a
session) in whatever client environment it runs in, and records, from SQL
Server itself:
  1. each session's SET options and client interface (<catalogue view>);
  2. one call of each of the four paths per query on input set 0 (the runner's
     query functions, unchanged), with coarse elapsed time - evidence, not a
     measurement;
  3. for every statement those calls ran: the cached plan (XML), its
     set_options plan attribute, its estimated subtree cost, and execution
     statistics (<catalogue view> since this script started).
Read-only for the data. Run once on the host (as A) and once from the Mac
container (as E), with the database in the state of the cells (non-indexed).

Usage: python code/rc_client_plans.py --campaign-dir <dir> --label host|mac --queries 6 17 21 --out <json>
"""
import argparse
import datetime as dt
import importlib
import json
import os
from pathlib import Path
import platform
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

SESSION_SQL = ("SELECT session_id, ansi_nulls, ansi_padding, ansi_warnings, arithabort, concat_null_yields_null, "
               "quoted_identifier, ansi_null_dflt_on, date_format, date_first, language, transaction_isolation_level, "
               "text_size, lock_timeout, client_interface_name, client_version, program_name, host_name "
               "FROM sys.dm_exec_sessions WHERE session_id = @@SPID")
CACHE_SQL = ("SELECT qs.plan_handle, qs.query_hash, qs.query_plan_hash, qs.execution_count, qs.total_elapsed_time, "
             "qs.last_elapsed_time, qs.last_worker_time, qs.last_logical_reads, qs.creation_time, "
             "SUBSTRING(st.text, (qs.statement_start_offset/2)+1, ((CASE qs.statement_end_offset WHEN -1 THEN "
             "DATALENGTH(st.text) ELSE qs.statement_end_offset END - qs.statement_start_offset)/2)+1) AS stmt, "
             "CAST(pa.value AS int) AS set_options, CAST(qp.query_plan AS nvarchar(max)) AS plan_xml "
             "FROM sys.dm_exec_query_stats qs CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st "
             "CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) qp "
             "CROSS APPLY sys.dm_exec_plan_attributes(qs.plan_handle) pa "
             "WHERE pa.attribute = 'set_options' AND qs.last_execution_time >= ? "
             "AND st.text LIKE '%lineitem%' ORDER BY qs.last_execution_time")


def rows(cur):
    names = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(names, [str(v) if isinstance(v, (bytes, bytearray)) else v for v in r])) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--queries', type=int, nargs='+', default=[6, 17, 21])
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--repeat', type=int, default=2, help='calls per path (the first warms the buffer pool)')
    ap.add_argument('--free-proccache', action='store_true',
                    help='DBCC FREEPROCCACHE first, so this client compiles its own plans, as in A and E '
                         '(clears cached plans only, no data)')
    a = ap.parse_args()
    camp = a.campaign_dir.resolve()
    out_path = a.out.resolve()
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
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    dconn = connections['default']
    engine = create_engine(os.environ['SA_DSN'], future=True)
    session = sessionmaker(bind=engine, future=True)()
    import pyodbc
    raw = engine.raw_connection()
    rec = {'label': a.label, 'started': C.stamps(), 'client': {
        'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.version.split()[0],
        'pyodbc': pyodbc.version, 'odbc_drivers': pyodbc.drivers(),
        'driver_name': raw.dbapi_connection.getinfo(pyodbc.SQL_DRIVER_NAME),
        'driver_version': raw.dbapi_connection.getinfo(pyodbc.SQL_DRIVER_VER),
        'odbc_version': raw.dbapi_connection.getinfo(pyodbc.SQL_DRIVER_ODBC_VER)}}
    raw.close()
    rec['free_proccache'] = a.free_proccache
    if a.free_proccache:
        with dconn.cursor() as c:
            c.execute('DBCC FREEPROCCACHE')
    with dconn.cursor() as c:
        c.execute('SELECT SYSDATETIME() AS t')
        t0_server = c.fetchone()[0]
        c.execute(SESSION_SQL)
        rec['session_django'] = rows(c)
    rec['session_sqlalchemy'] = [dict(r._mapping) for r in session.execute(text(SESSION_SQL))]
    rec['server_start_time'] = str(t0_server)
    calls = []
    for q in a.queries:
        params = inputs['queries'][str(q)]['sets'][0]
        dj = get_query_module_for_db(q, 'default')
        sa = importlib.import_module(f'sqlalchemy_app.queries.q{q:02d}')
        for path, fn in (('django/sql', lambda: dj.run_query_sql(dconn, params=params)),
                         ('django/orm', lambda: dj.run_query_orm(using='default', params=params)),
                         ('sqlalchemy/sql', lambda: sa.run_query_sql(session, params=params)),
                         ('sqlalchemy/orm', lambda: sa.run_query_orm(session, params=params))):
            for i in range(a.repeat):
                t = time.perf_counter()
                res = fn()
                calls.append({'query': q, 'path': path, 'call': i + 1, 'input_id': inputs['queries'][str(q)]['set_ids'][0],
                              'elapsed_s': time.perf_counter() - t, 'rows': len(res)})
                print(f'Q{q:02d} {path:15s} call {i + 1} {calls[-1]["elapsed_s"]:8.3f} s  rows {len(res)}', flush=True)
    rec['calls'] = calls
    # the driver's own cursor: commercial-a-django-backend rewrites '%' and parameter markers
    rc = dconn.connection.cursor()
    rc.execute(CACHE_SQL, t0_server)
    plans = rows(rc)
    rc.close()
    for p in plans:
        x = p.get('plan_xml') or ''
        i = x.find('StatementSubTreeCost="')
        p['estimated_subtree_cost'] = float(x[i + 22:x.index('"', i + 22)]) if i >= 0 else None
        for attr in ('CardinalityEstimationModelVersion', 'StatementOptmLevel', 'QueryPlanHash'):
            j = x.find(attr + '="')
            p[attr] = x[j + len(attr) + 2:x.index('"', j + len(attr) + 2)] if j >= 0 else None
    rec['plans'] = plans
    rec['finished'] = C.stamps()
    session.close()
    engine.dispose()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'x') as fh:
        fh.write(json.dumps(C.typed(rec), indent=1) + '\n')
    print(f'{len(plans)} cached plan entries -> {out_path}')


if __name__ == '__main__':
    main()
