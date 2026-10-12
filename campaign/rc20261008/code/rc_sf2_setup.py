#!/usr/bin/env python3
"""Create and load the SF2 TPC-H database on one engine, beside SF1, never over it.

  rc_sf2_setup.py --engine postgresql --duckdb <tpch2.duckdb> --out <evidence dir> [--create] [--load] [--check]

Target: a separate database `tpch_sf2` (PostgreSQL, MySQL, Commercial System A) or a
separate schema/user `TPCH_SF2` (Oracle). Every step refuses to touch a target
that already holds rows unless asked only to --check it, and nothing here ever
connects to the SF1 database except to read its table definitions.

The schema is the SF1 database's own, read from the live catalog, with the
fifteen secondary indexes removed (phase D creates them itself, as phase A
did), so SF2 differs from SF1 in scale only. --check compares column names,
types, lengths, precision, nullability and primary keys between the two and
writes the comparison. Loading reuses the repository loaders unchanged, pointed
at the SF2 target by environment variables. Credentials are taken from the
settings modules and never printed or written.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

TABLES = ['region', 'nation', 'supplier', 'customer', 'part', 'partsupp', 'orders', 'lineitem']
SRC = Path('<campaign>/src')


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def settings(engine):
    sys.path.insert(0, str(SRC))
    mod = {'postgresql': 'django_app.settings', 'mysql': 'settings_mysql', 'sqlserver': 'settings_sqlserver',
           'oracle': 'settings_oracle'}[engine]
    m = __import__(mod, fromlist=['DATABASES'])
    return dict(m.DATABASES['default'])


def columns(engine, conn, schema_or_db):
    c = conn.cursor()
    if engine == 'postgresql':
        c.execute("""SELECT table_name, column_name, data_type, character_maximum_length, numeric_precision,
                            numeric_scale, is_nullable, ordinal_position FROM information_schema.columns
                     WHERE table_schema = 'public' AND table_name = ANY(%s) ORDER BY 1, 8""", (TABLES,))
        cols = c.fetchall()
        c.execute("""SELECT tc.table_name, kcu.column_name, kcu.ordinal_position FROM information_schema.table_constraints tc
                     JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name
                     AND kcu.table_schema = tc.table_schema WHERE tc.constraint_type = 'PRIMARY KEY'
                     AND tc.table_schema = 'public' ORDER BY 1, 3""")
    elif engine == 'mysql':
        c.execute("""SELECT table_name, column_name, column_type, character_maximum_length, numeric_precision,
                            numeric_scale, is_nullable, ordinal_position FROM information_schema.columns
                     WHERE table_schema = %s ORDER BY 1, 8""", (schema_or_db,))
        cols = c.fetchall()
        c.execute("""SELECT table_name, column_name, seq_in_index FROM information_schema.statistics
                     WHERE table_schema = %s AND index_name = 'PRIMARY' ORDER BY 1, 3""", (schema_or_db,))
    elif engine == 'sqlserver':
        c.execute("""SELECT LOWER(t.name), LOWER(col.name), ty.name, col.max_length, col.precision, col.scale,
                            col.is_nullable, col.column_id FROM sys.columns col JOIN sys.tables t ON t.object_id = col.object_id
                     JOIN sys.types ty ON ty.user_type_id = col.user_type_id ORDER BY 1, 8""")
        cols = c.fetchall()
        c.execute("""SELECT LOWER(t.name), LOWER(col.name), ic.key_ordinal FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id
                     JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                     JOIN sys.columns col ON col.object_id = ic.object_id AND col.column_id = ic.column_id
                     WHERE i.is_primary_key = 1 ORDER BY 1, 3""")
    else:
        c.execute("""SELECT LOWER(table_name), LOWER(column_name), data_type, data_length, data_precision, data_scale,
                            nullable, column_id FROM all_tab_columns WHERE owner = :o ORDER BY 1, 8""", o=schema_or_db.upper())
        cols = c.fetchall()
        c.execute("""SELECT LOWER(cc.table_name), LOWER(cc.column_name), cc.position FROM all_constraints k
                     JOIN all_cons_columns cc ON cc.owner = k.owner AND cc.constraint_name = k.constraint_name
                     WHERE k.owner = :o AND k.constraint_type = 'P' ORDER BY 1, 3""", o=schema_or_db.upper())
    pks = c.fetchall()
    keep = lambda rows: [list(map(lambda v: v if v is None or isinstance(v, (int, str)) else str(v), r))
                         for r in rows if str(r[0]).lower() in TABLES]
    return {'columns': keep(cols), 'primary_keys': keep(pks)}


def count_rows(engine, conn, prefix=''):
    c = conn.cursor()
    out = {}
    for t in TABLES:
        try:
            c.execute(f'SELECT COUNT(*) FROM {prefix}{t}')
            out[t] = int(c.fetchone()[0])
        except Exception as exc:
            out[t] = f'absent: {type(exc).__name__}'
            try:
                conn.rollback()
            except Exception:
                pass
    return out


def connect(engine, s, database=None, user=None, password=None):
    if engine == 'postgresql':
        import psycopg2
        conn = psycopg2.connect(host=s['HOST'], port=s['PORT'], dbname=database or s['NAME'], user=s['USER'],
                                password=s['PASSWORD'])
        conn.autocommit = True
        return conn
    if engine == 'mysql':
        import MySQLdb
        return MySQLdb.connect(host=s['HOST'], port=int(s['PORT']), user=s['USER'], password=s['PASSWORD'],
                               database=database or s['NAME'], autocommit=True)
    if engine == 'sqlserver':
        import pyodbc
        drv = s.get('OPTIONS', {}).get('driver', 'ODBC Driver 18 for SQL Server')
        return pyodbc.connect(f"DRIVER={{{drv}}};SERVER={s['HOST']},{s['PORT']};DATABASE={database or s['NAME']};"
                              f"UID={s['USER']};PWD={s['PASSWORD']};TrustServerCertificate=yes", autocommit=True)
    import oracledb
    return oracledb.connect(user=user or s['USER'], password=password or s['PASSWORD'], dsn=s['NAME'])


def oracle_sf2(a, s, rec):
    """Oracle: SF2 lives in schema TPCH_SF2 (created by rc-campaign-root
    oracle-sf2-user), tables from the same schema_oracle.sql as SF1, loaded by
    the unchanged load_oracle.py with its target taken from the environment."""
    owner = 'TPCH_SF2'
    sf1 = connect('oracle', s)
    sf2 = connect('oracle', s, user=owner, password=s['PASSWORD'])
    sf1_def = columns('oracle', sf1, 'TPCH')
    if a.create:
        c = sf2.cursor()
        c.execute("SELECT COUNT(*) FROM user_tables")
        if c.fetchone()[0]:
            raise SystemExit('TPCH_SF2 already has tables; refusing to create over them')
        ddl = (SRC / 'scripts/1-setup/schema_oracle.sql').read_text()
        (a.out / 'oracle-sf2-ddl.sql').write_text(ddl)
        body = '\n'.join(l for l in ddl.splitlines() if not l.strip().startswith('--'))
        stmts = [x.strip() for x in body.split(';') if x.strip()]
        for st in stmts:
            c.execute(st)
        rec['steps'].append({'create_schema_tables': owner, 'statements': len(stmts)})
    if a.load:
        before = count_rows('oracle', sf2)
        if any(isinstance(v, int) and v > 0 for v in before.values()):
            raise SystemExit(f'target already holds rows {before}; refusing to load over it')
        env = dict(os.environ, ORA_DSN=s['NAME'], ORA_USER=owner, ORA_PASS=s['PASSWORD'])
        res = subprocess.run([sys.executable, str(SRC / 'scripts/1-setup/load_oracle.py'), '--duckdb', str(a.duckdb),
                              '--sf', '2', '--skip-constraints'], capture_output=True, text=True, env=env, cwd=str(SRC))
        (a.out / 'oracle-sf2-load.log').write_text(res.stdout + res.stderr)
        rec['steps'].append({'load': 'load_oracle.py', 'rc': res.returncode, 'tail': (res.stdout + res.stderr)[-1500:]})
        if res.returncode:
            raise SystemExit('load failed')
        with sf2.cursor() as c:
            for t in TABLES:
                c.callproc('DBMS_STATS.GATHER_TABLE_STATS', [owner, t.upper()])
        rec['steps'].append({'statistics': 'DBMS_STATS.GATHER_TABLE_STATS on all eight tables'})
    if a.check:
        sf2_def = columns('oracle', sf2, owner)
        rec['row_counts'] = count_rows('oracle', sf2)
        rec['schema_identical_to_sf1'] = sf2_def == sf1_def
        rec['sf1_definition'], rec['sf2_definition'] = sf1_def, sf2_def
    rec['finished_utc'] = stamp()
    p = a.out / f'oracle-sf2-setup-{rec["finished_utc"].replace(":", "")[:17]}.json'
    p.write_text(json.dumps(rec, indent=1, default=str) + '\n')
    print(json.dumps({k: rec.get(k) for k in ('engine', 'row_counts', 'schema_identical_to_sf1')}, default=str))
    if a.check and not rec['schema_identical_to_sf1']:
        raise SystemExit('SF2 schema differs from SF1')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', required=True, choices=['postgresql', 'mysql', 'sqlserver', 'oracle'])
    ap.add_argument('--duckdb', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--create', action='store_true')
    ap.add_argument('--load', action='store_true')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    e = a.engine
    s = settings(e)
    a.out.mkdir(parents=True, exist_ok=True)
    rec = {'engine': e, 'started_utc': stamp(), 'steps': []}
    target = 'tpch_sf2'
    if e == 'oracle':
        oracle_sf2(a, s, rec)
        return
    admin = connect(e, s)
    sf1_def = columns(e, admin, s['NAME'])
    if a.create:
        c = admin.cursor()
        if e == 'postgresql':
            c.execute('SELECT 1 FROM pg_database WHERE datname = %s', (target,))
            if c.fetchone():
                raise SystemExit('tpch_sf2 already exists; refusing to create over it')
            # template0, not the default template1: the host's OS moved from
            # glibc 2.39 to 2.43 (Ubuntu 26.04, 2026-10-06, before the campaign),
            # and PostgreSQL refuses to copy template1, which recorded 2.39
            # ("template database has a collation version mismatch", 2026-10-10
            # 03:23). template0 records no version, so the new database records
            # the library actually in use; encoding and locale are the cluster's,
            # as tpch's (checked by rc_pg_sf2_settings.py). Nothing existing is
            # altered.
            c.execute(f'CREATE DATABASE {target} TEMPLATE template0')
            dump = subprocess.run(['pg_dump', '--schema-only', '--no-owner', '--no-privileges', '-h', str(s['HOST']),
                                   '-p', str(s['PORT']), '-U', s['USER'], '-d', s['NAME']]
                                  + sum((['-t', t] for t in TABLES), []),
                                  capture_output=True, text=True, env={**os.environ, 'PGPASSWORD': s['PASSWORD']}, check=True)
            ddl = '\n'.join(l for l in dump.stdout.splitlines()
                            if not l.startswith('CREATE INDEX idx_') and 'transaction_timeout' not in l)
            (a.out / 'postgresql-sf2-ddl.sql').write_text(ddl)
            res = subprocess.run(['psql', '-v', 'ON_ERROR_STOP=1', '-h', str(s['HOST']), '-p', str(s['PORT']),
                                  '-U', s['USER'], '-d', target], input=ddl, capture_output=True, text=True,
                                 env={**os.environ, 'PGPASSWORD': s['PASSWORD']})
            rec['steps'].append({'create_database': target, 'ddl_apply_rc': res.returncode, 'stderr': res.stderr[-2000:]})
            if res.returncode:
                raise SystemExit('DDL failed: ' + res.stderr[-1000:])
        elif e == 'mysql':
            c.execute('SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s', (target,))
            if c.fetchone()[0]:
                raise SystemExit('tpch_sf2 already exists; refusing to create over it')
            c.execute(f'SHOW CREATE DATABASE {s["NAME"]}')
            dbddl = c.fetchone()[1].replace(f'`{s["NAME"]}`', f'`{target}`', 1)
            c.execute(dbddl)
            stmts = []
            for t in TABLES:
                c.execute(f'SHOW CREATE TABLE {s["NAME"]}.{t}')
                ddl = c.fetchone()[1]
                lines = [l for l in ddl.splitlines() if not l.strip().startswith('KEY `idx_')]
                # a removed last KEY line can leave a dangling comma before ')'
                for i in range(len(lines) - 1):
                    if lines[i + 1].startswith(')') and lines[i].rstrip().endswith(','):
                        lines[i] = lines[i].rstrip()[:-1]
                ddl = '\n'.join(lines)
                stmts.append(ddl)
            (a.out / 'mysql-sf2-ddl.sql').write_text(';\n\n'.join(stmts) + ';\n')
            tc = connect(e, s, database=target).cursor()
            for st in stmts:
                tc.execute(st)
            rec['steps'].append({'create_database': target, 'tables': len(stmts)})
        elif e == 'sqlserver':
            c.execute('SELECT COUNT(*) FROM sys.databases WHERE name = ?', target)
            if c.fetchone()[0]:
                raise SystemExit('tpch_sf2 already exists; refusing to create over it')
            c.execute(f'CREATE DATABASE {target}')
            # Same adaptive features as the SF1 database: the historical
            # preflight refuses plan store on, and recovery model SIMPLE.
            c.execute('SELECT recovery_model_desc, is_query_store_on, is_auto_create_stats_on, is_auto_update_stats_on, '
                      'compatibility_level, is_read_committed_snapshot_on FROM sys.databases WHERE name = ?', s['NAME'])
            o = c.fetchone()
            c.execute(f'ALTER DATABASE {target} SET RECOVERY {o[0]}')
            c.execute(f'ALTER DATABASE {target} SET QUERY_STORE = {"ON" if o[1] else "OFF"}')
            c.execute(f'ALTER DATABASE {target} SET AUTO_CREATE_STATISTICS {"ON" if o[2] else "OFF"}')
            c.execute(f'ALTER DATABASE {target} SET AUTO_UPDATE_STATISTICS {"ON" if o[3] else "OFF"}')
            c.execute(f'ALTER DATABASE {target} SET COMPATIBILITY_LEVEL = {o[4]}')
            ddl = (SRC / 'scripts/1-setup/schema_sqlserver.sql').read_text()
            (a.out / 'sqlserver-sf2-ddl.sql').write_text(ddl)
            res = subprocess.run(['/opt/mssql-tools18/bin/sqlcmd', '-S', f"{s['HOST']},{s['PORT']}", '-U', s['USER'],
                                  '-C', '-b', '-d', target], input=ddl, capture_output=True, text=True,
                                 env={**os.environ, 'SQLCMDPASSWORD': s['PASSWORD']})
            rec['steps'].append({'create_database': target, 'options_copied': [str(x) for x in o],
                                 'ddl_apply_rc': res.returncode, 'stderr': res.stderr[-2000:]})
            if res.returncode:
                raise SystemExit('DDL failed: ' + res.stderr[-1000:] + res.stdout[-1000:])
    tconn = connect(e, s, database=target)
    if a.load:
        before = count_rows(e, tconn)
        if any(isinstance(v, int) and v > 0 for v in before.values()):
            raise SystemExit(f'target already holds rows {before}; refusing to load over it')
        env = dict(os.environ)
        loader = {'postgresql': 'load_pg.py', 'mysql': 'load_mysql.py', 'sqlserver': 'load_sqlserver.py'}[e]
        if e == 'postgresql':
            env['PG_DSN'] = f"host={s['HOST']} port={s['PORT']} dbname={target} user={s['USER']} password={s['PASSWORD']}"
        elif e == 'mysql':
            env['MYSQL_DB'] = target
        else:
            env['SQLSERVER_DB'] = target
        res = subprocess.run([sys.executable, str(SRC / 'scripts/1-setup' / loader), '--duckdb', str(a.duckdb)],
                             capture_output=True, text=True, env=env, cwd=str(SRC))
        (a.out / f'{e}-sf2-load.log').write_text(res.stdout + res.stderr)
        rec['steps'].append({'load': loader, 'rc': res.returncode, 'tail': (res.stdout + res.stderr)[-1500:]})
        if res.returncode:
            raise SystemExit('load failed')
    if a.check:
        sf2_def = columns(e, tconn, target)
        rec['row_counts'] = count_rows(e, tconn)
        rec['schema_identical_to_sf1'] = sf2_def == sf1_def
        rec['sf1_definition'] = sf1_def
        rec['sf2_definition'] = sf2_def
    rec['finished_utc'] = stamp()
    p = a.out / f'{e}-sf2-setup-{rec["finished_utc"].replace(":", "")[:17]}.json'
    p.write_text(json.dumps(rec, indent=1, default=str) + '\n')
    print(json.dumps({k: rec.get(k) for k in ('engine', 'row_counts', 'schema_identical_to_sf1')}, default=str))
    if a.check and not rec['schema_identical_to_sf1']:
        raise SystemExit('SF2 schema differs from SF1')


if __name__ == '__main__':
    main()
