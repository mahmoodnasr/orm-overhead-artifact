#!/usr/bin/env python3
"""Phase G setup: one engine at a time in a container on this Mac.

  rc_g_setup.py <engine> start|load|stop|describe

start     run the container with the benchmark host's envelope (2 CPUs pinned
          to two VM vCPUs, 3 GB memory, no swap) and the host's measured
          engine settings; wait until it accepts connections.
load      create the TPC-H schema from the repository's DDL for that engine
          and load SF1 from the DuckDB file (the same generator call as the
          host's data; content verified afterwards by fingerprint), then
          gather statistics. Refuses if the tables already hold rows.
stop      stop the container (data volume kept).
describe  write docker inspect (image digest, platform, limits) as evidence.

Credentials come from the repository's settings modules (as on the host);
none is printed or written.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CAMP = Path(__file__).resolve().parent.parent
SRC = Path.home() / 'rc20261008-client' / 'src'
DUCK = Path(os.environ.get('RC_G_DUCKDB', str(Path.home() / 'rc20261008-client' / 'tpch1.duckdb')))
EVID = CAMP / 'evidence' / 'G-setup'
LIMITS = ['--cpus', '2', '--cpuset-cpus', '0,1', '--memory', '3g', '--memory-swap', '3g']
IMAGES = {'postgresql': 'postgres:18.6', 'mysql': 'mysql:8.4.11', 'oracle': 'gvenzl/oracle-free:23.7-slim',
          'sqlserver': 'mcr.microsoft.com/mssql/server:2025-CU9-ubuntu-24.04'}
PORTS = {'postgresql': (15432, 5432), 'mysql': (13306, 3306), 'oracle': (11521, 1521), 'sqlserver': (11433, 1433)}


def sh(cmd, check=True, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if check and p.returncode:
        raise SystemExit(f'failed: {cmd[:3]} ... rc={p.returncode}\n{p.stderr[-1500:]}')
    return p


def settings(engine):
    sys.path.insert(0, str(SRC))
    mod = {'postgresql': 'django_app.settings', 'mysql': 'settings_mysql', 'sqlserver': 'settings_sqlserver',
           'oracle': 'settings_oracle'}[engine]
    m = __import__(mod, fromlist=['DATABASES'])
    return dict(m.DATABASES['default'])


def start(e):
    s = settings(e)
    name = f'rcg-{e}'
    if sh(['docker', 'ps', '-q', '-f', f'name=^{name}$']).stdout.strip():
        # configuration is idempotent; a container started by an interrupted
        # attempt may not have had it applied yet
        print(name, 'already running; applying configuration')
    elif sh(['docker', 'ps', '-aq', '-f', f'name=^{name}$']).stdout.strip():
        sh(['docker', 'start', name])
    else:
        hp, cp = PORTS[e]
        base = ['docker', 'run', '-d', '--name', name, *LIMITS, '-p', f'127.0.0.1:{hp}:{cp}']
        if e == 'postgresql':
            cmd = base + ['-e', f"POSTGRES_USER={s['USER']}", '-e', f"POSTGRES_PASSWORD={s['PASSWORD']}",
                          '-e', 'POSTGRES_DB=tpch', '-v', 'rcg-postgresql:/var/lib/postgresql', IMAGES[e],
                          # the host's measured settings (phase P inventory)
                          '-c', 'shared_buffers=1536MB', '-c', 'work_mem=32MB', '-c', 'effective_cache_size=4GB',
                          '-c', 'max_parallel_workers=0', '-c', 'max_parallel_workers_per_gather=0',
                          '-c', 'jit=on', '-c', 'random_page_cost=4', '-c', 'max_wal_size=1GB',
                          '-c', 'timezone=Africa/Cairo']
        elif e == 'mysql':
            cmd = base + ['-e', f"MYSQL_ROOT_PASSWORD={s['PASSWORD']}", '-e', 'MYSQL_DATABASE=tpch',
                          '-e', f"MYSQL_USER={s['USER']}", '-e', f"MYSQL_PASSWORD={s['PASSWORD']}",
                          '-v', 'rcg-mysql:/var/lib/mysql', IMAGES[e],
                          '--innodb-buffer-pool-size=1536M', '--innodb-parallel-read-threads=1', '--local-infile=1']
        elif e == 'oracle':
            cmd = base + ['-e', f"ORACLE_PASSWORD={s['PASSWORD']}", '-e', f"APP_USER={s['USER']}",
                          '-e', f"APP_USER_PASSWORD={s['PASSWORD']}", '-v', 'rcg-oracle:/opt/oracle/oradata', IMAGES[e]]
        else:
            cmd = ['docker', 'run', '-d', '--platform', 'linux/amd64', '--name', name, *LIMITS,
                   '-p', f'127.0.0.1:{hp}:{cp}', '-e', 'ACCEPT_EULA=Y', '-e', 'MSSQL_PID=Developer',
                   '-e', f"MSSQL_SA_PASSWORD={s['PASSWORD']}", '-v', 'rcg-sqlserver:/var/opt/mssql', IMAGES[e]]
        sh(cmd)
    wait_ready(e, s)
    configure(e, s)
    print(name, 'ready')


def connect(e, s, database=None, admin=False):
    if e == 'postgresql':
        import psycopg2
        c = psycopg2.connect(host='127.0.0.1', port=PORTS[e][0], dbname=database or 'tpch', user=s['USER'], password=s['PASSWORD'])
        c.autocommit = True
        return c
    if e == 'mysql':
        import MySQLdb
        return MySQLdb.connect(host='127.0.0.1', port=PORTS[e][0], user='root' if admin else s['USER'],
                               password=s['PASSWORD'], database=database or 'tpch', autocommit=True)
    if e == 'sqlserver':
        import pyodbc
        return pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=127.0.0.1,{PORTS[e][0]};"
                              f"DATABASE={database or 'master'};UID={s['USER']};PWD={s['PASSWORD']};"
                              "TrustServerCertificate=yes", autocommit=True)
    import oracledb
    if admin:
        return oracledb.connect(user='system', password=s['PASSWORD'], dsn=f"127.0.0.1:{PORTS[e][0]}/FREEPDB1")
    return oracledb.connect(user=s['USER'], password=s['PASSWORD'], dsn=f"127.0.0.1:{PORTS[e][0]}/FREEPDB1")


def wait_ready(e, s, limit=900):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            c = connect(e, s, admin=(e == 'oracle'))
            c.cursor().execute('SELECT 1' + (' FROM dual' if e == 'oracle' else ''))
            c.close()
            return
        except Exception:
            time.sleep(5)
    raise SystemExit(f'{e} did not become ready in {limit} s')


def configure(e, s):
    if e == 'mysql':
        c = connect(e, s, admin=True).cursor()
        c.execute(f"GRANT SESSION_VARIABLES_ADMIN, SYSTEM_VARIABLES_ADMIN ON *.* TO '{s['USER']}'@'%'")
    elif e == 'sqlserver':
        c = connect(e, s).cursor()
        for st in ["EXEC sp_configure 'show advanced options', 1", 'RECONFIGURE',
                   "EXEC sp_configure 'max degree of parallelism', 1", "EXEC sp_configure 'max server memory (MB)', 1536",
                   "EXEC sp_configure 'cost threshold for parallelism', 5", "EXEC sp_configure 'optimize for ad hoc workloads', 0",
                   'RECONFIGURE']:
            c.execute(st)
        c.execute("SELECT COUNT(*) FROM sys.databases WHERE name = 'tpch'")
        if not c.fetchone()[0]:
            c.execute('CREATE DATABASE tpch')
        for st in ['ALTER DATABASE tpch SET RECOVERY SIMPLE', 'ALTER DATABASE tpch SET QUERY_STORE = OFF',
                   'ALTER DATABASE tpch SET COMPATIBILITY_LEVEL = 170']:
            c.execute(st)
    elif e == 'oracle':
        a = connect(e, s, admin=True).cursor()
        # host: result cache MANUAL, one parallel server, 512 MB PGA (phase A inventory)
        for st in ["ALTER SYSTEM SET result_cache_mode = MANUAL", "ALTER SYSTEM SET parallel_max_servers = 1",
                   "ALTER SYSTEM SET pga_aggregate_target = 512M"]:
            try:
                a.execute(st)
            except Exception as exc:
                print('note:', st, str(exc)[:120])
        oracle_host_parameters(e, s)
        sysc = None
        for g in ('GRANT SELECT ON SYS.V_$SESSION TO {u}', 'GRANT SELECT ON SYS.V_$PARAMETER TO {u}'):
            try:
                import oracledb
                sysc = sysc or oracledb.connect(user='sys', password=s['PASSWORD'], dsn=f"127.0.0.1:{PORTS[e][0]}/FREEPDB1",
                                                mode=oracledb.AUTH_MODE_SYSDBA)
                sysc.cursor().execute(g.format(u=s['USER'].upper()))
            except Exception as exc:
                print('note: grant', str(exc)[:120])


HOST_ORACLE = {  # evidence/G-setup/host-oracle-parameters.txt (read from the host, 2026-10-08)
    'sga_max_size': '1536M', 'sga_target': '0', 'pga_aggregate_target': '512M', 'pga_aggregate_limit': '2G',
    'processes': '200', 'open_cursors': '300', 'cpu_count': '2', 'parallel_max_servers': '1',
    'result_cache_mode': 'MANUAL', 'optimizer_adaptive_plans': 'TRUE', 'optimizer_adaptive_statistics': 'FALSE'}


def oracle_host_parameters(e, s):
    """Set the host's Oracle parameters at CDB level, restart, verify; revert on failure."""
    import oracledb
    dsn_cdb = f"127.0.0.1:{PORTS[e][0]}/FREE"
    sysc = oracledb.connect(user='sys', password=s['PASSWORD'], dsn=dsn_cdb, mode=oracledb.AUTH_MODE_SYSDBA)
    c = sysc.cursor()
    c.execute("SELECT name, value FROM v$parameter WHERE name IN (%s)" % ','.join(f"'{k}'" for k in HOST_ORACLE))
    now = {n: v for n, v in c.fetchall()}
    want = {k: v for k, v in HOST_ORACLE.items()}
    def norm(v):
        v = str(v).upper()
        return {'1536M': '1610612736', '512M': '536870912', '2G': '2147483648'}.get(v, v)
    if all(norm(now.get(k)) == norm(v) for k, v in want.items()):
        print('oracle parameters already match the host')
        return
    c.execute("CREATE PFILE='/opt/oracle/oradata/rc-backup-init.ora' FROM SPFILE")
    for k, v in want.items():
        q = f"'{v}'" if k in ('result_cache_mode',) else v
        c.execute(f"ALTER SYSTEM SET {k} = {q} SCOPE=SPFILE")
    sysc.close()
    sh(['docker', 'restart', f'rcg-{e}'])
    try:
        wait_ready(e, s, limit=600)
    except SystemExit:
        # revert: start from the saved pfile
        sh(['docker', 'exec', f'rcg-{e}', 'bash', '-c',
            "echo \"STARTUP PFILE='/opt/oracle/oradata/rc-backup-init.ora'\" | sqlplus -s / as sysdba"], check=False)
        raise SystemExit('Oracle did not start with the host parameters; reverted to the saved parameter file')
    sysc = oracledb.connect(user='sys', password=s['PASSWORD'], dsn=dsn_cdb, mode=oracledb.AUTH_MODE_SYSDBA)
    c = sysc.cursor()
    c.execute("SELECT name, value FROM v$parameter WHERE name IN (%s)" % ','.join(f"'{k}'" for k in HOST_ORACLE))
    got = {n: v for n, v in c.fetchall()}
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / 'oracle-parameters-applied.json').write_text(json.dumps({'wanted': want, 'got': got}, indent=1) + '\n')
    print('oracle parameters set:', got)


def network(e):
    sh(['docker', 'network', 'create', 'rcg-net'], check=False)
    sh(['docker', 'network', 'connect', 'rcg-net', f'rcg-{e}'], check=False)
    print('rcg-net connected', e)


def record(e):
    """Container evidence for a run whose client has no Docker CLI (G-v2)."""
    d = json.loads(sh(['docker', 'inspect', f'rcg-{e}']).stdout)[0]
    img = json.loads(sh(['docker', 'image', 'inspect', d['Image']]).stdout)[0]
    cli = json.loads(sh(['docker', 'image', 'inspect', 'rcg-client:3.12.3']).stdout)[0]
    out = {'container': {'name': f'rcg-{e}', 'image': d['Config']['Image'], 'repo_digests': img.get('RepoDigests'),
                         'image_architecture': img.get('Architecture'), 'nano_cpus': d['HostConfig'].get('NanoCpus'),
                         'cpuset_cpus': d['HostConfig'].get('CpusetCpus'), 'memory': d['HostConfig'].get('Memory'),
                         'memory_swap': d['HostConfig'].get('MemorySwap'), 'cmd': d['Config'].get('Cmd'),
                         'running': d['State'].get('Running')},
           'containers_running': [json.loads(x) for x in sh(['docker', 'stats', '--no-stream', '--format', '{{json .}}']).stdout.splitlines() if x.strip()],
           'client_image': {'id': cli['Id'], 'architecture': cli.get('Architecture'), 'created': cli.get('Created')},
           'recorded': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    path = EVID / f'{e}-container-record-{time.strftime("%Y%m%dT%H%M%S")}.json'
    EVID.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + '\n')
    print(path)


def run_ddl(e, s, path):
    text = path.read_text()
    # SQL comments and psql meta-commands (\echo ...) are not statements.
    body = '\n'.join(l for l in text.splitlines() if not l.strip().startswith(('--', '\\')))
    if e == 'postgresql':
        body = body.split('<<-EOSQL', 1)[1].split('EOSQL', 1)[0] if '<<-EOSQL' in body else body
    if e == 'sqlserver':
        # the vendor dialect scripts separate batches with GO lines; each batch runs whole
        import re
        stmts = [x.strip() for x in re.split(r'^\s*GO\s*$', body, flags=re.M | re.I) if x.strip()]
    else:
        stmts = [x.strip() for x in body.split(';') if x.strip()]
    # init-db.sh is a shell script: its GRANT ... TO $POSTGRES_USER lines give
    # the table owner rights it already has; skip any statement that still
    # contains a shell variable rather than guess its value.
    stmts = [x for x in stmts if '$' not in x]
    c = connect(e, s, database='tpch').cursor()
    for st in stmts:
        c.execute(st)
    return len(stmts)


def load(e):
    s = settings(e)
    EVID.mkdir(parents=True, exist_ok=True)
    c = connect(e, s, database='tpch').cursor()
    rows = None
    try:
        c.execute('SELECT COUNT(*) FROM lineitem')
        rows = c.fetchone()[0]
    except Exception:
        pass
    if rows == 6001215:
        print('already loaded (lineitem 6001215 rows); identity is checked by the fingerprint step')
        return
    if rows:
        raise SystemExit(f'lineitem holds {rows} rows, not a complete SF1 load; refusing to load over it')
    ddl = {'postgresql': SRC / 'docker/postgresql/init-db.sh', 'mysql': SRC / 'scripts/1-setup/schema_mysql.sql',
           'sqlserver': SRC / 'scripts/1-setup/schema_sqlserver.sql', 'oracle': SRC / 'scripts/1-setup/schema_oracle.sql'}[e]
    n = run_ddl(e, s, ddl)
    env = dict(os.environ)
    loader = {'postgresql': 'load_pg.py', 'mysql': 'load_mysql.py', 'sqlserver': 'load_sqlserver.py', 'oracle': 'load_oracle.py'}[e]
    args = ['--duckdb', str(DUCK)]
    if e == 'postgresql':
        env['PG_DSN'] = f"host=127.0.0.1 port={PORTS[e][0]} dbname=tpch user={s['USER']} password={s['PASSWORD']}"
    elif e == 'mysql':
        env.update(MYSQL_HOST='127.0.0.1', MYSQL_PORT=str(PORTS[e][0]), MYSQL_DB='tpch')
    elif e == 'sqlserver':
        env.update(SQLSERVER_HOST='127.0.0.1', SQLSERVER_PORT=str(PORTS[e][0]), SQLSERVER_DB='tpch',
                   SQLSERVER_ODBC_DRIVER='ODBC Driver 18 for SQL Server')
    else:
        env.update(ORA_DSN=f"127.0.0.1:{PORTS[e][0]}/FREEPDB1", ORA_USER=s['USER'], ORA_PASS=s['PASSWORD'])
        args += ['--sf', '1', '--skip-constraints']
    t0 = time.time()
    p = subprocess.run([sys.executable, str(SRC / 'scripts/1-setup' / loader)] + args, capture_output=True,
                       text=True, env=env, cwd=str(SRC))
    (EVID / f'{e}-load.log').write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit(f'load failed, see {EVID / (e + "-load.log")}')
    rec = {'engine': e, 'ddl': str(ddl.relative_to(SRC)), 'ddl_statements': n, 'loader': loader,
           'seconds': round(time.time() - t0, 1), 'duckdb_sha256': sh(['shasum', '-a', '256', str(DUCK)]).stdout.split()[0]}
    (EVID / f'{e}-load.json').write_text(json.dumps(rec, indent=1) + '\n')
    print(json.dumps(rec))


def describe(e):
    EVID.mkdir(parents=True, exist_ok=True)
    d = json.loads(sh(['docker', 'inspect', f'rcg-{e}']).stdout)[0]
    img = json.loads(sh(['docker', 'image', 'inspect', d['Image']]).stdout)[0]
    keep = {'name': d['Name'], 'image': d['Config']['Image'], 'image_id': d['Image'],
            'repo_digests': img.get('RepoDigests'), 'image_architecture': img.get('Architecture'),
            'image_os': img.get('Os'), 'host_architecture': sh(['uname', '-m']).stdout.strip(),
            'nano_cpus': d['HostConfig'].get('NanoCpus'), 'cpuset_cpus': d['HostConfig'].get('CpusetCpus'),
            'memory': d['HostConfig'].get('Memory'), 'memory_swap': d['HostConfig'].get('MemorySwap'),
            'cmd': d['Config'].get('Cmd'), 'started': d['State'].get('StartedAt'),
            'docker_info': json.loads(sh(['docker', 'info', '--format', '{{json .}}']).stdout),
            'mac': {'model': sh(['sysctl', '-n', 'machdep.cpu.brand_string']).stdout.strip(),
                    'ncpu': sh(['sysctl', '-n', 'hw.ncpu']).stdout.strip(),
                    'memsize': sh(['sysctl', '-n', 'hw.memsize']).stdout.strip(),
                    'macos': sh(['sw_vers']).stdout}}
    for k in ('docker_info',):
        keep[k] = {x: keep[k].get(x) for x in ('ServerVersion', 'OperatingSystem', 'Architecture', 'NCPU', 'MemTotal', 'KernelVersion')}
    out = EVID / f'{e}-container-{time.strftime("%Y%m%dT%H%M%S")}.json'
    out.write_text(json.dumps(keep, indent=1) + '\n')
    print(out)


def stop(e):
    sh(['docker', 'stop', f'rcg-{e}'], check=False)
    print('stopped', e)


if __name__ == '__main__':
    eng, act = sys.argv[1], sys.argv[2]
    {'start': start, 'load': load, 'stop': stop, 'describe': describe, 'network': network, 'record': record}[act](eng)
