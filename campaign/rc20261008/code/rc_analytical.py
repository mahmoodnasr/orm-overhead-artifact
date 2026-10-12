#!/usr/bin/env python3
"""Analytical runner for campaign rc20261008: timing and full results from one execution.

Protocol: the historical block design of scripts/2-benchmark/run_block.py, kept
unchanged where it defines what is measured -
  * one cell-warmup sequence of the four paths on a ninth parameter instance;
  * eight measured blocks, two seeded permutations of four Williams sequences,
    each block using its own saved parameter set, identical across the paths;
  * every path warmed on the block's parameters before the block's timed run;
  * a path that exceeds the ceiling in the cell warmup is censored for the cell.

What this adds, and why:
  * the result each timed call returned is kept, typed, and compared with its
    framework's SQL baseline from the SAME block before the pair is accepted,
    because the historical validation was a separate run that rounded values,
    sorted inside rows and was never tied to a timing row;
  * every execution is an immutable record (written once with link(), so a
    resumed run cannot overwrite one) and acceptance is a separate immutable
    decision written only after the block's comparisons pass - an execution
    that was in flight at a crash has no decision and is never accepted;
  * skipped arms are written down as records with their reason, so absence is
    never silent;
  * after a timeout or error both frameworks' connections are closed and the
    server is asked whether the old session is still running before the next
    timed call; a statement still running there would contend with it.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
import traceback
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

TABLES = 'region nation supplier customer part partsupp orders lineitem'.split()
TIMEOUT_MARKERS = ('57014', 'statement timeout', 'canceling statement', 'hyt00', 'hyt01',
                   'query timeout', 'ora-01013', 'dpy-4024', 'dpi-1067', 'dpy-4011',
                   'maximum statement execution time', 'query execution was interrupted', '3024')


def sh(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {'cmd': cmd, 'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except Exception as exc:
        return {'cmd': cmd, 'returncode': None, 'error': repr(exc)}


class Runner:
    def __init__(self, args):
        self.a = args
        self.run_dir = args.run_dir.resolve()
        self.campaign = args.campaign_dir.resolve()
        self.src = (args.src or (self.campaign / 'src')).resolve()
        self.run_id = uuid.uuid4().hex
        self.crash_counter = 0
        self.progress = {}

    # ------------------------------------------------------------ bookkeeping
    def event(self, event_name, **kw):
        rec = {'event': event_name, 'run_id': self.run_id, 'pid': os.getpid(), **C.stamps(), **kw}
        C.append_jsonl(self.run_dir / 'events.jsonl', rec)
        print(json.dumps(C.typed(rec), default=str)[:400], flush=True)

    def save_progress(self, **kw):
        self.progress.update(kw)
        self.progress.update(C.stamps())
        p = self.progress
        done = p.get('completed_cell_seconds', [])
        rem = p.get('remaining_predicted_s')
        if rem is not None and p.get('observed_over_predicted'):
            p['eta_s'] = rem * p['observed_over_predicted']
        C.save(self.run_dir / 'progress.json', p)

    # ------------------------------------------------------------------ setup
    def lock(self):
        lockpath = self.campaign / 'server.lock'
        self._lockfh = open(lockpath, 'a+')
        try:
            fcntl.flock(self._lockfh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('another campaign process holds server.lock; refusing to overlap')
        # The October diagnostics used their own lock; a holder there is a
        # running measurement too.
        old = self.campaign.parent / 'controlled-followup.lock'
        if old.exists():
            with open(old, 'a+') as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fh, fcntl.LOCK_UN)
                except BlockingIOError:
                    raise SystemExit('controlled-followup.lock is held; a diagnostic is running')
        holder = {'pid': os.getpid(), 'run_id': self.run_id, 'argv': sys.argv,
                  'run_dir': str(self.run_dir), **C.stamps()}
        C.save(self.campaign / 'server-lock-holder.json', holder)

    def setup(self):
        a = self.a
        if os.environ.get('TPCH_SF') != str(a.scale):
            raise SystemExit(f"TPCH_SF={os.environ.get('TPCH_SF')!r} but --scale {a.scale}")
        if a.client_cpus:
            want = {int(c) for c in a.client_cpus.split(',')}
            if os.sched_getaffinity(0) != want:
                raise SystemExit(f'client affinity {sorted(os.sched_getaffinity(0))} != {sorted(want)}; use taskset')
        self.protocol = C.load(a.protocol)
        self.protocol_sha = C.file_sha256(a.protocol)
        self.inputs = C.load(self.campaign / self.protocol['inputs_file'])
        self.inputs_sha = C.file_sha256(self.campaign / self.protocol['inputs_file'])
        assert self.inputs_sha == self.protocol['inputs_sha256'], 'frozen inputs file changed'
        existing = self.run_dir.exists() and any(self.run_dir.iterdir())
        if existing and not a.resume:
            raise SystemExit(f'{self.run_dir} has records; pass --resume or use a new directory')
        self.run_dir.mkdir(parents=True, exist_ok=True)
        rp = self.run_dir / 'run-parameters.json'
        params = {'protocol_id': self.protocol['protocol_id'], 'protocol_sha256': self.protocol_sha,
                  'phase': a.phase, 'dbms': a.dbms, 'schema': a.schema, 'scale': a.scale,
                  'queries': a.queries, 'timeout_s': a.timeout, 'mode': a.mode, 'blocks': a.blocks,
                  'client_mode': a.client_mode, 'database_label': a.database_label}
        if rp.exists():
            prev = json.loads(rp.read_text())
            if prev != C.typed(params):
                raise SystemExit(f'resume with different parameters: {prev} vs {params}')
        else:
            C.save(rp, params, immutable=True)
        os.chdir(self.src)
        sys.path.insert(0, str(self.src))
        import django
        django.setup()
        from django.db import connections
        import tpch_paramsets
        self.tp = tpch_paramsets
        self.dconn = connections['default']
        self._check_inputs()
        self._build_sa()

    def _check_inputs(self):
        """The saved sets must be exactly what tpch_paramsets generates now."""
        for q in self.a.queries:
            saved = self.inputs['queries'][str(q)]
            now = {'warmup': self.tp.warmup_params(q),
                   'sets': [self.tp.params_of(q, i) for i in range(8)],
                   'set_ids': [self.tp.set_id(q, i) for i in range(8)]}
            if C.digest(now) != C.digest({k: saved[k] for k in ('warmup', 'sets', 'set_ids')}):
                raise SystemExit(f'Q{q}: tpch_paramsets no longer reproduces the frozen inputs')

    def _build_sa(self):
        from sqlalchemy import create_engine, event
        from sqlalchemy.engine import URL, make_url
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.sql.elements import TextClause
        cfg = self.dconn.settings_dict
        dsn = os.environ.get('SA_DSN')
        if dsn:
            url = make_url(dsn)
        else:
            driver = {'postgresql': 'postgresql+psycopg2', 'mysql': 'mysql+mysqldb',
                      'oracle': 'oracle+oracledb', 'sqlserver': 'mssql+pyodbc'}[self.a.dbms]
            host, port, db, query = cfg.get('HOST'), cfg.get('PORT'), cfg['NAME'], {}
            if self.a.dbms == 'oracle':
                loc, service = db.rsplit('/', 1)
                host, port = loc.rsplit(':', 1)
                db, query = None, {'service_name': service}
            url = URL.create(driver, username=cfg['USER'], password=cfg['PASSWORD'], host=host,
                             port=int(port) if port else None, database=db, query=query)
        # Same server, database and account as Django's connection.
        self.sa_url_public = url.render_as_string(hide_password=True)
        self.engine = create_engine(url, future=True)
        self.Session = sessionmaker(bind=self.engine, future=True)
        self.session = self.Session()
        self.sa_trace = None

        @event.listens_for(self.engine, 'before_cursor_execute')
        def _before(conn, cursor, statement, parameters, context, executemany):
            if self.sa_trace is not None:
                obj = getattr(getattr(context, 'compiled', None), 'statement', None)
                self.sa_trace.append({'sql': statement, 'params': parameters, 'many': executemany,
                                      'text_clause': isinstance(obj, TextClause)})

        @event.listens_for(self.engine, 'after_cursor_execute')
        def _after(conn, cursor, statement, parameters, context, executemany):
            if self.sa_trace:
                self.sa_trace[-1]['columns'] = [d[0] for d in cursor.description] if cursor.description else []

    # ------------------------------------------------------------ connections
    def _dj_query(self, sql, params=None):
        with self.dconn.cursor() as c:
            c.execute(sql, params or [])
            cols = [d[0].lower() for d in c.description] if c.description else []
            return [dict(zip(cols, r)) for r in c.fetchall()] if cols else []

    def _sa_query(self, sql, params=None):
        from sqlalchemy import text
        res = self.session.execute(text(sql), params or {})
        cols = [k.lower() for k in res.keys()]
        return [dict(zip(cols, r)) for r in res.fetchall()]

    SESSION_SQL = {
        'postgresql': ("SELECT pg_backend_pid() AS sid, backend_start::text AS tag FROM pg_stat_activity WHERE pid = pg_backend_pid()", None),
        'mysql': ('SELECT CONNECTION_ID() AS sid, NULL AS tag', None),
        'sqlserver': ('SELECT @@SPID AS sid, CONVERT(varchar(40), login_time, 126) AS tag FROM sys.dm_exec_sessions WHERE session_id = @@SPID', None),
        # SYS_CONTEXT needs no privilege; the benchmark user cannot read V$SESSION.
        'oracle': ("SELECT SYS_CONTEXT('USERENV','SID') AS sid, SYS_CONTEXT('USERENV','SESSIONID') AS tag FROM dual", None),
    }

    def session_ids(self):
        sql = self.SESSION_SQL[self.a.dbms][0]
        dj = self._dj_query(sql)[0]
        sa = self._sa_query(sql)[0]
        return {'django': {'sid': str(dj['sid']), 'tag': None if dj['tag'] is None else str(dj['tag'])},
                'sqlalchemy': {'sid': str(sa['sid']), 'tag': None if sa['tag'] is None else str(sa['tag'])}}

    def arm(self, seconds):
        """Set and read back the per-call ceiling on both frameworks' connections."""
        from sqlalchemy import text
        d = self.a.dbms
        self.dconn.ensure_connection()
        raw_sa = self.session.connection().connection.dbapi_connection
        raw_dj = self.dconn.connection
        got = {}
        if d == 'oracle':
            for name, raw in (('django', raw_dj), ('sqlalchemy', raw_sa)):
                raw.call_timeout = int(seconds * 1000)
                got[name] = raw.call_timeout
            ok = all(v == int(seconds * 1000) for v in got.values())
        elif d == 'sqlserver':
            for name, raw in (('django', raw_dj), ('sqlalchemy', raw_sa)):
                raw.timeout = int(seconds)
                got[name] = raw.timeout
            ok = all(v == int(seconds) for v in got.values())
        else:
            stmt = (f'SET statement_timeout = {int(seconds * 1000)}' if d == 'postgresql'
                    else f'SET SESSION max_execution_time = {int(seconds * 1000)}')
            read = 'SHOW statement_timeout' if d == 'postgresql' else 'SELECT @@SESSION.max_execution_time AS v'
            with self.dconn.cursor() as c:
                c.execute(stmt)
            self.session.execute(text(stmt))
            got['django'] = str(list(self._dj_query(read)[0].values())[0])
            got['sqlalchemy'] = str(list(self._sa_query(read)[0].values())[0])

            def ms(x):
                x = x.strip()
                for suf, f in (('min', 60000), ('ms', 1), ('s', 1000)):
                    if x.endswith(suf):
                        return float(x[:-len(suf)]) * f
                return float(x)
            ok = all(ms(v) == seconds * 1000 for v in got.values())
        if not ok:
            raise RuntimeError(f'ceiling readback mismatch: {got} for {seconds}s')
        self.armed = {'seconds': seconds, 'readback': got,
                      'raw_ids': [id(raw_dj), id(raw_sa)]}
        self.sids = self.session_ids()
        return self.armed

    def ensure_armed(self, seconds):
        """Re-arm only if a connection changed or the ceiling differs."""
        self.dconn.ensure_connection()
        raw_sa = self.session.connection().connection.dbapi_connection
        a = getattr(self, 'armed', None)
        if not a or a['seconds'] != seconds or a['raw_ids'] != [id(self.dconn.connection), id(raw_sa)]:
            return self.arm(seconds)
        return a

    def _server_session_state(self, fw, ident):
        """Rows for the old session, excluding the session asking the question.

        A request on the asking session is the poll itself: ODBC connection
        pooling hands Commercial System A's reconnect the same physical session (same
        SPID and login time), and the first version of this check counted its
        own polling SELECT as the cancelled statement still running. A session
        runs one request at a time, so if the old session is the asking one,
        the old statement is not running.
        """
        d = self.a.dbms
        sid, tag = ident['sid'], ident['tag']
        if d == 'postgresql':
            rows = self._dj_query("SELECT pid, state, backend_start::text AS tag, pid = pg_backend_pid() AS is_self, left(query, 120) AS q FROM pg_stat_activity WHERE pid = %s", [int(sid)])
            rows = [r for r in rows if r['tag'] == tag]
            running = [r for r in rows if r['state'] == 'active' and not r['is_self']]
        elif d == 'mysql':
            rows = self._dj_query('SELECT id, command, state, time, id = CONNECTION_ID() AS is_self, LEFT(info, 120) AS q FROM information_schema.processlist WHERE id = %s', [int(sid)])
            running = [r for r in rows if r['command'] == 'Query' and not r['is_self']]
        elif d == 'sqlserver':
            rows = self._dj_query("SELECT s.session_id, CONVERT(varchar(40), s.login_time, 126) AS tag, r.status, r.command, CASE WHEN s.session_id = @@SPID THEN 1 ELSE 0 END AS is_self FROM sys.dm_exec_sessions s LEFT JOIN sys.dm_exec_requests r ON r.session_id = s.session_id WHERE s.session_id = %s", [int(sid)])
            rows = [r for r in rows if r['tag'] == tag]
            running = [r for r in rows if r['status'] not in (None, 'sleeping', 'background') and not r['is_self']]
        else:
            try:
                rows = self._dj_query("SELECT sid, audsid, status, sql_id, last_call_et, CASE WHEN sid = SYS_CONTEXT('USERENV','SID') THEN 1 ELSE 0 END AS is_self FROM v$session WHERE sid = %s", [int(sid)])
                rows = [r for r in rows if str(r['audsid']) == str(tag)]
                running = [r for r in rows if r['status'] == 'ACTIVE' and not r['is_self']]
            except Exception as exc:
                if 'ORA-00942' not in str(exc):
                    raise
                rows, running = self._oracle_foreground_busy()
        return rows, running

    def _oracle_foreground_busy(self):
        """Fallback when V$SESSION is not readable (ORA-00942 for this user).

        Every client session on this host is served by a dedicated Oracle
        foreground process ('oraclefree (LOCAL=NO)'). A cancelled statement
        still executing would keep one of them on CPU. Sample the CPU time of
        all of them over two seconds (/proc is readable without privilege);
        any that consumed more than 0.2 s of CPU is counted as running. The
        asking session is idle during the sample.
        """
        import glob as _g
        def sample():
            out = {}
            for d in _g.glob('/proc/[0-9]*'):
                try:
                    cmd = open(d + '/cmdline', 'rb').read().replace(b'\0', b' ').decode(errors='replace')
                    if not cmd.lower().startswith('oracle') or 'LOCAL=NO' not in cmd:
                        continue
                    f = open(d + '/stat').read().rsplit(')', 1)[1].split()
                    out[d] = (cmd.strip(), (int(f[11]) + int(f[12])) / os.sysconf('SC_CLK_TCK'))
                except (OSError, IndexError, ValueError):
                    continue
            return out
        a = sample()
        time.sleep(2)
        b = sample()
        rows = [{'proc': k, 'cmd': b[k][0], 'cpu_s_in_2s': round(b[k][1] - a[k][1], 3)} for k in b if k in a]
        running = [r for r in rows if r['cpu_s_in_2s'] > 0.2]
        return [{'method': 'os_cpu_fallback_no_v$session'}] + rows, running

    def _kill(self, ident):
        d, sid = self.a.dbms, int(ident['sid'])
        stmts = {'postgresql': [f'SELECT pg_cancel_backend({sid})', f'SELECT pg_terminate_backend({sid})'],
                 'mysql': [f'KILL QUERY {sid}', f'KILL {sid}'],
                 'sqlserver': [f'KILL {sid}'],
                 'oracle': []}[d]
        out = []
        for s in stmts:
            try:
                with self.dconn.cursor() as c:
                    c.execute(s)
                out.append({'stmt': s, 'ok': True})
            except Exception as exc:
                out.append({'stmt': s, 'ok': False, 'error': str(exc)[:300]})
        return out

    def recover(self, reason):
        """Close both frameworks' connections and prove the old server work stopped."""
        old = getattr(self, 'sids', None)
        rec = {'reason': reason, 'old_sessions': old, 'steps': [], **C.stamps()}
        for label, fn in (('sa_rollback', self.session.rollback), ('sa_close', self.session.close),
                          ('sa_dispose', self.engine.dispose), ('dj_close', self.dconn.close)):
            try:
                fn()
                rec['steps'].append({label: 'ok'})
            except Exception as exc:
                rec['steps'].append({label: repr(exc)[:300]})
        self.session = self.Session()
        self.armed = None
        deadline = time.monotonic() + self.a.cancel_wait
        verified, polls = False, []
        while True:
            try:
                state = {}
                for fw, ident in (old or {}).items():
                    rows, running = self._server_session_state(fw, ident)
                    state[fw] = {'rows': rows, 'running': len(running)}
                polls.append({'t': time.monotonic(), 'state': state})
                if all(v['running'] == 0 for v in state.values()):
                    verified = True
                    break
            except Exception as exc:
                polls.append({'error': repr(exc)[:400]})
                try:
                    self.dconn.close()
                except Exception:
                    pass
            if time.monotonic() > deadline:
                break
            time.sleep(2)
        if not verified and old:
            rec['kill'] = {fw: self._kill(ident) for fw, ident in old.items()}
            time.sleep(5)
            try:
                state = {fw: len(self._server_session_state(fw, ident)[1]) for fw, ident in old.items()}
                verified = all(v == 0 for v in state.values())
                rec['after_kill_running'] = state
            except Exception as exc:
                rec['after_kill_error'] = repr(exc)
        rec['polls'] = polls[-5:]
        rec['poll_count'] = len(polls)
        rec['server_work_stopped_verified'] = verified
        rec['rearm'] = self.arm(self.a.timeout)
        return rec

    # --------------------------------------------------------------- inventory
    def inventory(self, label):
        d = self.a.dbms
        q = self._dj_query
        inv = {'label': label, 'run_id': self.run_id, **C.stamps(), 'host': socket.gethostname(),
               'platform': platform.platform(), 'python': sys.version, 'executable': sys.executable,
               'client_affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
               'loadavg': os.getloadavg(), 'packages': {}, 'dbms': d, 'schema': self.a.schema,
               'scale': self.a.scale, 'database_label': self.a.database_label,
               'sa_url': self.sa_url_public,
               'django_database': {k: v for k, v in self.dconn.settings_dict.items()
                                   if k in ('ENGINE', 'NAME', 'HOST', 'PORT', 'USER')}}
        for pkg in ('Django', 'SQLAlchemy', 'psycopg2-binary', 'mysqlclient', 'oracledb', 'pyodbc', 'mssql-django'):
            try:
                inv['packages'][pkg] = importlib.metadata.version(pkg)
            except importlib.metadata.PackageNotFoundError:
                pass
        try:
            inv['os_release'] = Path('/etc/os-release').read_text()
        except OSError:
            inv['os_release'] = platform.mac_ver()
        inv['row_counts'] = {t: int(list(q(f'SELECT COUNT(*) AS n FROM {t}')[0].values())[0]) for t in TABLES}
        if d == 'sqlserver':
            inv['server'] = q('SELECT @@VERSION AS version, DB_NAME() AS database_name, SERVERPROPERTY(\'ProductVersion\') AS product_version')
            inv['settings'] = q("SELECT name, CAST(value_in_use AS bigint) AS value FROM sys.configurations WHERE name IN ('max degree of parallelism','max server memory (MB)','cost threshold for parallelism','optimize for ad hoc workloads') ORDER BY name")
            inv['database_options'] = q("SELECT is_auto_create_stats_on, is_auto_update_stats_on, is_query_store_on, compatibility_level, is_read_committed_snapshot_on FROM sys.databases WHERE name = DB_NAME()")
            inv['indexes'] = q("SELECT LOWER(t.name) AS table_name, LOWER(i.name) AS index_name, i.is_primary_key, i.is_disabled, LOWER(c.name) AS column_name, ic.key_ordinal FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.index_id>0 ORDER BY t.name, i.name, ic.key_ordinal")
            inv['stats_updated'] = q("SELECT LOWER(OBJECT_NAME(s.object_id)) AS table_name, LOWER(s.name) AS stat_name, CONVERT(varchar(40), STATS_DATE(s.object_id, s.stats_id), 126) AS updated FROM sys.stats s JOIN sys.tables t ON t.object_id = s.object_id ORDER BY 1, 2")
        elif d == 'oracle':
            inv['server'] = q('SELECT banner_full FROM v$version')
            inv['settings'] = q("SELECT name, value FROM v$parameter WHERE name IN ('sga_target','pga_aggregate_target','parallel_degree_policy','parallel_max_servers','result_cache_mode','optimizer_features_enable','memory_target','cpu_count') ORDER BY name")
            inv['indexes'] = q("SELECT LOWER(i.table_name) AS table_name, LOWER(i.index_name) AS index_name, i.uniqueness, i.status, LOWER(c.column_name) AS column_name, c.column_position, CASE WHEN EXISTS (SELECT 1 FROM user_constraints k WHERE k.index_name = i.index_name AND k.constraint_type = 'P') THEN 1 ELSE 0 END AS is_primary_key FROM user_indexes i JOIN user_ind_columns c ON c.index_name = i.index_name ORDER BY 1, 2, c.column_position")
            inv['stats_updated'] = q("SELECT LOWER(table_name) AS table_name, TO_CHAR(last_analyzed, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS updated, num_rows FROM user_tables ORDER BY 1")
        elif d == 'postgresql':
            inv['server'] = q('SELECT version() AS version, current_database() AS database_name')
            inv['settings'] = q("SELECT name, setting, unit FROM pg_settings WHERE name IN ('shared_buffers','work_mem','effective_cache_size','max_parallel_workers_per_gather','max_parallel_workers','jit','random_page_cost','server_version') ORDER BY name")
            inv['indexes'] = q("SELECT t.relname AS table_name, i.relname AS index_name, x.indisprimary AS is_primary_key, pg_get_indexdef(i.oid) AS definition FROM pg_index x JOIN pg_class t ON t.oid = x.indrelid JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = 'public' ORDER BY 1, 2")
            inv['stats_updated'] = q("SELECT relname AS table_name, last_analyze::text AS analyzed, last_autoanalyze::text AS autoanalyzed, n_live_tup FROM pg_stat_user_tables ORDER BY 1")
        else:
            inv['server'] = q('SELECT VERSION() AS version, DATABASE() AS database_name')
            inv['settings'] = q("SELECT @@innodb_buffer_pool_size AS buffer_pool_bytes, @@sql_mode AS sql_mode, @@optimizer_switch AS optimizer_switch, @@transaction_isolation AS isolation, @@version_comment AS comment")
            inv['indexes'] = q("SELECT LOWER(table_name) AS table_name, LOWER(index_name) AS index_name, LOWER(column_name) AS column_name, seq_in_index AS position, CASE WHEN index_name = 'PRIMARY' THEN 1 ELSE 0 END AS is_primary_key FROM information_schema.statistics WHERE table_schema = DATABASE() ORDER BY 1, 2, 4")
            inv['stats_updated'] = q("SELECT LOWER(table_name) AS table_name, update_time, table_rows FROM information_schema.tables WHERE table_schema = DATABASE() ORDER BY 1")
        tp = [r for r in inv['indexes'] if str(r['table_name']).lower() in TABLES]
        inv['secondary_indexes'] = sorted({str(r['index_name']).lower() for r in tp
                                           if not r.get('is_primary_key') and str(r['index_name']).lower() != 'primary'})
        if self.a.client_mode == 'same-host':
            inv['host_verification'] = sh(['sudo', '-n', '/usr/local/sbin/bench-host', 'verify', d])
            inv['oracle_process_affinity'] = sh(['bash', '-c', "for p in $(pgrep -u oracle); do awk '/Cpus_allowed_list/{print $2}' /proc/$p/status; done | sort | uniq -c"]) if d == 'oracle' else None
            inv['storage'] = sh(['findmnt', '-T', {'sqlserver': '/var/opt/mssql', 'oracle': '/opt/oracle',
                                                    'mysql': '/var/lib/mysql', 'postgresql': '/var/lib/postgresql'}[d]])
            inv['block_devices'] = sh(['lsblk', '-o', 'NAME,MODEL,SERIAL,ROTA,SIZE,TYPE,MOUNTPOINTS'])
            inv['top_processes'] = sh(['ps', '-eo', 'pid,user,pcpu,rss,etime,comm', '--sort=-pcpu'])['stdout'].splitlines()[:15]
            inv['other_engines'] = sh(['systemctl', 'is-active', 'postgresql@18-main', 'mysql', 'mssql-server', 'oracle-free'])
        inv['index_verification'] = sh([sys.executable, 'scripts/1-setup/manage_indexes.py', '--database', 'default',
                                        '--action', 'verify', '--expect', self.a.schema], timeout=300)
        inv['source_hashes'] = self.source_hashes()
        inv['code_hashes'] = {n: C.file_sha256(HERE / n) for n in ('rc_analytical.py', 'rc_common.py')}
        inv['protocol_sha256'] = self.protocol_sha
        inv['inputs_sha256'] = self.inputs_sha
        return inv

    def source_hashes(self):
        out = {}
        for folder in ('django_app', 'sqlalchemy_app'):
            for p in sorted((self.src / folder).rglob('*.py')):
                out[str(p.relative_to(self.src))] = C.file_sha256(p)
        for name in ('tpch_paramsets.py', 'tpch_params.py', 'tpch_domains.py', 'settings_mysql.py', 'settings_oracle.py',
                     'settings_sqlserver.py', 'odbc_driver.py', 'mssql_decimal_fix.py', 'scripts/1-setup/manage_indexes.py'):
            p = self.src / name
            if p.exists():
                out[name] = C.file_sha256(p)
        return out

    def gate(self, inv):
        """Refuse to time anything on a host or database not in the declared state."""
        problems = []
        exp_counts = self.protocol['expected_row_counts'][str(self.a.scale)]
        if inv['row_counts'] != exp_counts:
            problems.append(f"row counts {inv['row_counts']} != {exp_counts}")
        sec = inv['secondary_indexes']
        want = sorted(self.protocol['secondary_indexes'])
        if self.a.schema == 'non-indexed' and sec:
            problems.append(f'non-indexed but secondary indexes present: {sec}')
        if self.a.schema == 'indexed' and sec != want:
            problems.append(f'indexed but secondary set {sec} != {want}')
        if inv['index_verification']['returncode'] != 0:
            problems.append('manage_indexes verify failed')
        hv = inv.get('host_verification')
        if hv is not None and hv.get('returncode') != 0:
            if not (self.a.dbms == 'oracle' and self._oracle_verify_ok(hv, inv)):
                problems.append('bench-host verify failed: ' + (hv.get('stdout') or '')[-800:])
        if self.a.dbms == 'sqlserver':
            s = {r['name']: r['value'] for r in inv['settings']}
            if s.get('max degree of parallelism') != 1:
                problems.append(f'MAXDOP {s.get("max degree of parallelism")}')
        if self.a.dbms == 'postgresql':
            s = {r['name']: r['setting'] for r in inv['settings']}
            if s.get('max_parallel_workers_per_gather') != '0':
                problems.append('PostgreSQL parallel workers per gather != 0')
        if self.a.dbms == 'oracle':
            s = {r['name']: r['value'] for r in inv['settings']}
            if str(s.get('result_cache_mode', '')).upper() != 'MANUAL':
                problems.append(f'Oracle result_cache_mode {s.get("result_cache_mode")}')
        rc = self.protocol.get('runner_code_sha256')
        if rc and rc != inv['code_hashes']:
            problems.append(f"runner code differs from the protocol freeze: {inv['code_hashes']} vs {rc}")
        ps = self.protocol.get('source_hashes')
        if ps and inv['source_hashes'] != ps:
            changed = sorted(k for k in set(ps) | set(inv['source_hashes'])
                             if ps.get(k) != inv['source_hashes'].get(k))
            problems.append(f'source differs from protocol snapshot: {changed[:10]}')
        return problems

    def _oracle_verify_ok(self, hv, inv):
        """bench-host's PMON check assumes SID FREE; this instance runs as 'free'.

        Accept its non-zero exit only if every other line passed and the ora_*
        processes are directly read as pinned to CPUs 0-1.
        """
        out = hv.get('stdout') or ''
        bad = [l for l in out.splitlines() if '<--' in l and 'ora_* affinity' not in l and 'oracle:' not in l]
        aff = (inv.get('oracle_process_affinity') or {}).get('stdout', '').split()
        cpus = {aff[i + 1] for i in range(0, len(aff) - 1, 2)} if aff else set()
        return not bad and cpus == {'0-1'}

    # ---------------------------------------------------------------- execute
    def modules(self, q):
        from django_app.queries import get_query_module_for_db
        dj = get_query_module_for_db(q, 'default')
        sa = importlib.import_module(f'sqlalchemy_app.queries.q{q:02d}')
        return dj, sa

    def execute(self, q, path, params, ctx):
        """One call. Timer brackets the query function only; it returns the
        complete materialised result. Statement capture hooks run inside the
        timer for all four paths alike (one list append per statement)."""
        a = self.a
        limit = ctx.get('limit', a.timeout)
        self.ensure_armed(limit)
        dj, sa = self.mods
        trace = []

        def dj_wrap(execute, sql, prm, many, context):
            item = {'sql': sql, 'params': prm, 'many': many}
            trace.append(item)
            result = execute(sql, prm, many, context)
            cur = context.get('cursor')
            try:
                item['columns'] = [d[0] for d in cur.description] if cur is not None and cur.description else []
            except Exception:
                item['columns'] = None
            return result
        sids = dict(self.sids)
        rec = {'campaign': self.protocol['campaign_id'], 'protocol_id': self.protocol['protocol_id'],
               'protocol_sha256': self.protocol_sha, 'phase': a.phase, 'run_id': self.run_id,
               'dbms': a.dbms, 'schema': a.schema, 'scale': a.scale, 'database_label': a.database_label,
               'client_mode': a.client_mode, 'query': q, 'framework': path.split('/')[0],
               'path': path, 'kind': ctx['kind'], 'block': ctx['block'], 'attempt': ctx['attempt'],
               'sequence_id': ctx.get('sequence_id'), 'position': ctx.get('position'),
               'input_id': ctx['input_id'], 'parameters': params, 'timeout_s': limit,
               'environment_id': self.env_id, 'source_sha256': self.source_sha,
               'dataset_id': self.protocol['dataset_ids'].get(f'{a.dbms}:sf{a.scale}'),
               'server_session': sids.get(path.split('/')[0]), 'pid': os.getpid(),
               'load1_before': os.getloadavg()[0], 'start': C.stamps()}
        self.save_progress(state='executing', current={'query': q, 'path': path, 'kind': ctx['kind'],
                                                        'block': ctx['block'], 'attempt': ctx['attempt'],
                                                        'input_id': ctx['input_id'], 'limit_s': limit,
                                                        'server_session': rec['server_session'], **C.stamps()})
        self.crash_counter += 1
        rows = None
        self.sa_trace = trace if path.startswith('sqlalchemy') else None
        t0 = time.perf_counter()
        try:
            with self.dconn.execute_wrapper(dj_wrap):
                marker = self.run_dir / 'crash-injected.json'
                if a.crash_at and self.crash_counter == a.crash_at and not marker.exists():
                    # Pilot-only: die inside the timed region, as a power cut
                    # would - once; the marker stops a resumed run repeating it.
                    C.save(marker, {'at_call': a.crash_at, 'query': q, 'path': path,
                                    'kind': ctx['kind'], 'block': ctx['block'], **C.stamps()})
                    os._exit(97)
                if path == 'django/sql':
                    rows = dj.run_query_sql(self.dconn, params=params)
                elif path == 'django/orm':
                    rows = dj.run_query_orm(using='default', params=params)
                elif path == 'sqlalchemy/sql':
                    rows = sa.run_query_sql(self.session, params=params)
                else:
                    rows = sa.run_query_orm(self.session, params=params)
            elapsed = time.perf_counter() - t0
            rec['status'] = 'ok'
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            msg = f'{type(exc).__name__}: {exc}'
            if type(exc).__name__ == 'Q13NotExpressible':
                status = 'not_expressible'
            elif any(m in msg.lower() for m in TIMEOUT_MARKERS) or elapsed >= 0.9 * limit:
                status = 'timeout'
            else:
                status = 'error'
            rec.update(status=status, error=msg[:2000], traceback=traceback.format_exc()[-4000:])
        finally:
            self.sa_trace = None
        rec['elapsed_s'] = elapsed
        rec['end'] = C.stamps()
        rec['load1_after'] = os.getloadavg()[0]
        rec['statements'] = trace
        if rows is not None:
            if not isinstance(rows, list):
                # A lazy result would be materialised here, outside the timer;
                # such a call is not a valid measurement of its path.
                rec['status'] = 'invalid_return_type'
                rec['return_type'] = type(rows).__name__
                rows = list(rows)
            rec['rows'] = rows
            rec['rows_returned'] = len(rows)
            rec['result_sha256'] = C.digest(rows)
            rec['output_columns'] = (list(rows[0]) if rows else
                                     (trace[-1].get('columns') if trace else None))
            rec['value_types'] = sorted({f'{k}:{type(v).__name__}' for r in rows[:50] for k, v in r.items()}) if rows else []
        if rec['status'] in ('timeout', 'error'):
            rec['recovery'] = self.recover(rec['status'])
            if not rec['recovery']['server_work_stopped_verified']:
                rec['fatal'] = 'server work after cancellation could not be shown to have stopped'
        return rec

    def record(self, relpath, rec):
        sha = C.save(self.run_dir / relpath, rec, immutable=True)
        self.progress.setdefault('counts', {})
        k = rec['kind']
        cnt = self.progress['counts']
        cnt[f'saved_{k}'] = cnt.get(f'saved_{k}', 0) + 1
        cnt[f'status_{k}_{rec["status"]}'] = cnt.get(f'status_{k}_{rec["status"]}', 0) + 1
        self.event('execution_saved', record=relpath, kind=k, query=rec['query'], path=rec['path'],
                   block=rec['block'], status=rec['status'], elapsed_s=round(rec['elapsed_s'], 6),
                   rows=rec.get('rows_returned'), file_sha256=sha)
        if rec.get('fatal'):
            self.event('fatal', reason=rec['fatal'], record=relpath)
            self.save_progress(state='failed_fatal')
            raise SystemExit(rec['fatal'])
        return sha

    # ------------------------------------------------------------- comparisons
    def orm_check(self, orm, sql):
        return C.orm_path_check(orm, sql)

    def compare_block(self, q, recs):
        out = {}
        pairs = {'django': ('django/sql', 'django/orm'), 'sqlalchemy': ('sqlalchemy/sql', 'sqlalchemy/orm'),
                 'cross_sql': ('django/sql', 'sqlalchemy/sql'), 'cross_orm': ('django/orm', 'sqlalchemy/orm')}
        for name, (x, y) in pairs.items():
            rx, ry = recs.get(x), recs.get(y)
            if not rx or not ry or rx.get('status') != 'ok' or ry.get('status') != 'ok':
                out[name] = {'classification': 'unavailable', 'accepted': False,
                             'status': [rx.get('status') if rx else 'not_run', ry.get('status') if ry else 'not_run']}
                continue
            c = C.compare(q, rx['rows'], ry['rows'], rx.get('output_columns'), ry.get('output_columns'),
                          policy=self.protocol['result_policy']['version'])
            c['left'], c['right'] = x, y
            if name in ('django', 'sqlalchemy'):
                c['orm_path_check'] = self.orm_check(ry, rx)
            out[name] = c
        return out

    # --------------------------------------------------------------- the cell
    def _attempt(self, d):
        d.mkdir(parents=True, exist_ok=True)
        n = 1
        while (d / f'a{n}').exists():
            n += 1
        (d / f'a{n}').mkdir()
        return n

    def run_cell(self, q):
        a = self.a
        cdir = self.run_dir / f'q{q:02d}'
        if (cdir / 'cell-done.json').exists():
            self.event('cell_skip_done', query=q)
            return
        t_cell = time.monotonic()
        self.mods = self.modules(q)
        inp = self.inputs['queries'][str(q)]
        seed, plan = C.block_plan(f"{self.protocol['protocol_id']}:{a.dbms}:{a.schema}:sf{a.scale}:{a.database_label}:q{q}")
        plan = plan[:a.blocks]
        C.save(cdir / 'plan.json', {'seed': seed, 'block_sequences': plan, 'cell_warmup_sequence': seed % 4,
                                    'williams': C.WILLIAMS}) if not (cdir / 'plan.json').exists() else None
        censored, inexpressible = {}, {}
        cw = cdir / 'cellwarm' / 'outcome.json'
        if cw.exists():
            o = C.load(cw)
            censored, inexpressible = o['censored'], o['inexpressible']
        else:
            att = self._attempt(cdir / 'cellwarm')
            recs = {}
            seq = C.WILLIAMS[seed % 4]
            for pos, path in enumerate(seq):
                ctx = {'kind': 'cell_warmup', 'block': 0, 'attempt': att, 'sequence_id': seed % 4,
                       'position': pos, 'input_id': f'q{q:02d}warm'}
                r = self.execute(q, path, inp['warmup'], ctx)
                self.record(f'q{q:02d}/cellwarm/a{att}/{path.replace("/", "-")}.json.gz', r)
                recs[path] = r
            cmp_ = self.compare_block(q, recs)
            for path, r in recs.items():
                if r['status'] == 'timeout':
                    censored[path] = {'input_id': f'q{q:02d}warm', 'limit_s': r['timeout_s'],
                                      'elapsed_s': r['elapsed_s'], 'stage': 'cell_warmup'}
                elif r['status'] == 'not_expressible':
                    inexpressible[path] = {'error': r.get('error', '')[:300]}
            errors = {p: r.get('error', '')[:500] for p, r in recs.items() if r['status'] == 'error'}
            C.save(cw, {'attempt': att, 'censored': censored, 'inexpressible': inexpressible,
                        'errors': errors, 'comparisons': cmp_}, immutable=True)
            self.event('cell_warmup_done', query=q, censored=list(censored), inexpressible=list(inexpressible),
                       errors=list(errors), comparisons={k: v['classification'] for k, v in cmp_.items()})
            if errors:
                C.save(cdir / 'needs-review.json', {'stage': 'cell_warmup', 'errors': errors}, immutable=False)
                self._finish_cell(q, cdir, 'error_in_cell_warmup', t_cell)
                return
        skip = {**{p: 'censored_in_cell_warmup' for p in censored},
                **{p: 'not_expressible' for p in inexpressible}}
        stop_reason = None
        for b, seq_id in enumerate(plan, start=1):
            bdir = cdir / f'b{b}'
            if (bdir / 'decision.json').exists():
                dec = C.load(bdir / 'decision.json')
                if dec.get('stop_cell'):
                    stop_reason = dec['stop_cell']
                    break
                continue
            si = (b - 1) % 8
            params = inp['sets'][si]
            input_id = inp['set_ids'][si]
            att = self._attempt(bdir)
            warm = {}
            for path in C.PATHS:
                if path in skip:
                    continue
                ctx = {'kind': 'block_warmup', 'block': b, 'attempt': att, 'sequence_id': seq_id,
                       'position': -1, 'input_id': input_id}
                r = self.execute(q, path, params, ctx)
                self.record(f'q{q:02d}/b{b}/a{att}/warm-{path.replace("/", "-")}.json.gz', r)
                warm[path] = r
            timed = {}
            for pos, path in enumerate(C.WILLIAMS[seq_id]):
                if path in skip:
                    continue
                ctx = {'kind': 'timed', 'block': b, 'attempt': att, 'sequence_id': seq_id,
                       'position': pos, 'input_id': input_id}
                r = self.execute(q, path, params, ctx)
                self.record(f'q{q:02d}/b{b}/a{att}/timed-{path.replace("/", "-")}.json.gz', r)
                timed[path] = r
            cmp_t = self.compare_block(q, timed)
            cmp_w = self.compare_block(q, warm)
            fw_dec = {}
            stop = None
            for fw in ('django', 'sqlalchemy'):
                c = cmp_t[fw]
                sql_p, orm_p = f'{fw}/sql', f'{fw}/orm'
                if sql_p in skip or orm_p in skip:
                    fw_dec[fw] = {'accepted': False, 'status': 'not_run',
                                  'reason': {p: skip[p] for p in (sql_p, orm_p) if p in skip}}
                    continue
                st = (timed[sql_p]['status'], timed[orm_p]['status'])
                if st != ('ok', 'ok'):
                    fw_dec[fw] = {'accepted': False, 'status': 'execution_' + '_'.join(st)}
                    continue
                ok = c['accepted'] and c['orm_path_check']['passed']
                structural = c['classification'] in ('mismatch', 'schema_error') or not c['orm_path_check']['passed']
                fw_dec[fw] = {'accepted': ok, 'classification': c['classification'],
                              'orm_path_check': c['orm_path_check']['passed'],
                              'status': 'accepted' if ok else
                              ('mismatch' if structural else c['classification'])}
                # A structural difference (rows, keys, strings, or an ORM path
                # that is not the ORM) means the implementation is suspect:
                # stop the cell for diagnosis. A numeric-only difference or a
                # LIMIT-boundary tie is recorded as rejected and the cell runs
                # all eight blocks, so the evidence is complete.
                if structural:
                    stop = f'{fw} result check failed in block {b}: {c["classification"]}'
            dec = {'query': q, 'block': b, 'attempt': att, 'sequence_id': seq_id, 'input_id': input_id,
                   'frameworks': fw_dec, 'comparisons_timed': cmp_t, 'comparisons_block_warmup': cmp_w,
                   'timed_records': {p: f'a{att}/timed-{p.replace("/", "-")}.json.gz' for p in timed},
                   'skipped': skip, 'stop_cell': stop, 'policy': self.protocol['result_policy']['version'], **C.stamps()}
            C.save(bdir / 'decision.json', dec, immutable=True)
            cnt = self.progress.setdefault('counts', {})
            for fw, dd in fw_dec.items():
                key = 'accepted_pairs' if dd['accepted'] else f"pairs_{dd['status']}"
                cnt[key] = cnt.get(key, 0) + 1
            cnt['accepted_timed'] = cnt.get('accepted_pairs', 0) * 2
            self.event('block_decided', query=q, block=b, attempt=att,
                       frameworks={k: v['status'] for k, v in fw_dec.items()},
                       cross={k: cmp_t[k]['classification'] for k in ('cross_sql', 'cross_orm')})
            self.save_progress(state='block_decided')
            if stop:
                C.save(cdir / 'needs-review.json', dec)
                stop_reason = stop
                break
        self._finish_cell(q, cdir, stop_reason or 'complete', t_cell, censored, inexpressible)

    def _finish_cell(self, q, cdir, status, t_cell, censored=None, inexpressible=None):
        secs = time.monotonic() - t_cell
        C.save(cdir / 'cell-done.json', {'query': q, 'status': status, 'censored': censored or {},
                                         'inexpressible': inexpressible or {}, 'wall_s_this_run': secs,
                                         **C.stamps()}, immutable=True)
        p = self.progress
        p.setdefault('cells_done', []).append({'query': q, 'status': status, 'wall_s': secs})
        pred = self.predicted.get(q)
        if pred:
            if not p.get('_obs'):
                p['_obs'] = [0.0, 0.0]
            p['_obs'][0] += secs
            p['_obs'][1] += pred
            p['observed_over_predicted'] = p['_obs'][0] / p['_obs'][1] if p['_obs'][1] else None
        p['remaining_predicted_s'] = sum(self.predicted.get(x, 0) for x in self.remaining if x != q)
        self.event('cell_done', query=q, status=status, wall_s=round(secs, 1))
        self.save_progress(state='cell_done')


    # ------------------------------------------------------- cancellation test
    def cancel_test(self):
        """Force a short ceiling on every path, prove the server stopped, then
        prove the next call on the same framework works. Pilot evidence only."""
        a = self.a
        rows = []
        slow, fast = a.cancel_test_query, a.cancel_check_query
        for path in C.PATHS:
            self.mods = self.modules(slow)
            si = self.inputs['queries'][str(slow)]
            r = self.execute(slow, path, si['sets'][0], {'kind': 'cancel_probe', 'block': -1, 'attempt': 1,
                                                         'input_id': si['set_ids'][0], 'limit': a.cancel_limit})
            self.record(f'cancel-test/{path.replace("/", "-")}-probe.json.gz', r)
            self.mods = self.modules(fast)
            sf = self.inputs['queries'][str(fast)]
            r2 = self.execute(fast, path, sf['sets'][0], {'kind': 'cancel_followup', 'block': -1, 'attempt': 1,
                                                          'input_id': sf['set_ids'][0], 'limit': a.timeout})
            self.record(f'cancel-test/{path.replace("/", "-")}-followup.json.gz', r2)
            rows.append({'path': path, 'probe_status': r['status'], 'probe_elapsed_s': r['elapsed_s'],
                         'probe_limit_s': a.cancel_limit, 'probe_error': (r.get('error') or '')[:300],
                         'recovery_verified': (r.get('recovery') or {}).get('server_work_stopped_verified'),
                         'recovery_polls': (r.get('recovery') or {}).get('poll_count'),
                         'followup_status': r2['status'], 'followup_elapsed_s': r2['elapsed_s']})
        passed = all(x['probe_status'] == 'timeout' and x['recovery_verified'] and x['followup_status'] == 'ok'
                     for x in rows)
        C.save(self.run_dir / 'cancel-test' / 'summary.json', {'passed': passed, 'paths': rows, **C.stamps()},
               immutable=True)
        self.event('cancel_test_done', passed=passed, paths=rows)
        return passed

    # -------------------------------------------------------------- main loop
    def main(self):
        a = self.a
        self.lock()
        self.setup()
        self.event('start', argv=sys.argv, protocol=self.protocol['protocol_id'])
        inv = self.inventory('before')
        self.env_id = C.digest({k: inv[k] for k in ('host', 'platform', 'python', 'packages', 'server', 'settings',
                                                       'secondary_indexes', 'source_hashes', 'code_hashes',
                                                       'client_affinity', 'dbms', 'schema', 'scale')})
        self.source_sha = C.digest(inv['source_hashes'])
        inv['environment_id'] = self.env_id
        C.save(self.run_dir / f'inventory-before-{self.run_id}.json', inv, immutable=True)
        problems = self.gate(inv)
        if problems:
            self.event('gate_refused', problems=problems)
            C.save(self.run_dir / f'gate-refused-{self.run_id}.json', {'problems': problems, **C.stamps()})
            raise SystemExit('gate refused: ' + '; '.join(problems))
        self.arm(a.timeout)
        hist = self.protocol.get('predicted_cell_seconds', {}).get(f'{a.dbms}:{a.schema}', {})
        self.predicted = {int(k): v for k, v in hist.items()}
        self.remaining = list(a.queries)
        self.progress = {'run_id': self.run_id, 'pid': os.getpid(), 'phase': a.phase, 'dbms': a.dbms,
                         'schema': a.schema, 'scale': a.scale, 'mode': a.mode, 'queries': a.queries,
                         'planned_timed': len(a.queries) * 4 * a.blocks, 'counts': {},
                         'environment_id': self.env_id, 'started': C.stamps()}
        prev = self.run_dir / 'progress.json'
        if prev.exists():
            old = C.load(prev)
            self.progress['counts'] = old.get('counts', {})
            self.progress['cells_done'] = old.get('cells_done', [])
            self.progress['_obs'] = old.get('_obs') or [0.0, 0.0]
            self.progress['observed_over_predicted'] = old.get('observed_over_predicted')
            self.progress['resumed_from_run'] = old.get('run_id')
        self.save_progress(state='running')
        if a.cancel_test_query:
            self.cancel_test()
        else:
            for q in list(a.queries):
                self.run_cell(q)
                self.remaining.remove(q)
        after = self.inventory('after')
        after['environment_id'] = self.env_id
        C.save(self.run_dir / f'inventory-after-{self.run_id}.json', after, immutable=True)
        checks = {'source_unchanged': after['source_hashes'] == inv['source_hashes'],
                  'indexes_unchanged': after['indexes'] == inv['indexes'],
                  'row_counts_unchanged': after['row_counts'] == inv['row_counts'],
                  'settings_unchanged': after['settings'] == inv['settings'],
                  'server_unchanged': after['server'] == inv['server'],
                  'gate_after': self.gate(after)}
        all_ok = all(v for k, v in checks.items() if k != 'gate_after') and not checks['gate_after']
        cells = {}
        for q in ([] if a.cancel_test_query else a.queries):
            cells[q] = C.load(self.run_dir / f'q{q:02d}' / 'cell-done.json')['status']
        unresolved = {q: s for q, s in cells.items() if s != 'complete'}
        C.save(self.run_dir / f'end-checks-{self.run_id}.json', {'checks': checks, 'cells': cells, **C.stamps()})
        if all_ok:
            C.save(self.run_dir / 'completion.json', {
                'run_id': self.run_id, 'environment_checks_pass': True, 'checks': checks,
                'cells': cells, 'cells_with_unresolved_items': unresolved,
                'all_cells_complete_without_review': not unresolved,
                'note': 'completion means the run finished and its end checks passed; it does not mean every '
                        'comparison was accepted - see decisions and cells_with_unresolved_items',
                'counts': self.progress.get('counts'), **C.stamps()})
        self.event('end', checks_ok=all_ok, unresolved=unresolved)
        self.save_progress(state='complete' if all_ok else 'end_checks_failed')
        self.session.close()
        self.engine.dispose()
        self.dconn.close()
        if not all_ok:
            raise SystemExit('end checks failed: ' + json.dumps(C.typed(checks))[:800])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, required=True)
    ap.add_argument('--src', type=Path)
    ap.add_argument('--run-dir', type=Path, required=True)
    ap.add_argument('--protocol', type=Path, required=True)
    ap.add_argument('--phase', required=True)
    ap.add_argument('--dbms', choices=['postgresql', 'mysql', 'oracle', 'sqlserver'], required=True)
    ap.add_argument('--schema', choices=['indexed', 'non-indexed'], required=True)
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--database-label', default='tpch')
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--timeout', type=float, default=900)
    ap.add_argument('--blocks', type=int, default=8)
    ap.add_argument('--mode', choices=['main', 'pilot'], required=True)
    ap.add_argument('--client-mode', choices=['same-host', 'separate-client'], default='same-host')
    ap.add_argument('--client-cpus', default='2,3')
    ap.add_argument('--cancel-wait', type=float, default=60)
    ap.add_argument('--crash-at', type=int, default=0, help='pilot only: os._exit inside the Nth call')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--cancel-test-query', type=int, default=0)
    ap.add_argument('--cancel-check-query', type=int, default=6)
    ap.add_argument('--cancel-limit', type=float, default=1)
    args = ap.parse_args()
    if args.cancel_test_query and args.mode != 'pilot':
        raise SystemExit('the cancellation test is pilot evidence only')
    if args.crash_at and args.mode != 'pilot':
        raise SystemExit('--crash-at is a pilot-only fault injection')
    r = Runner(args)
    try:
        r.main()
    except SystemExit:
        raise
    except BaseException:
        try:
            C.save(args.run_dir / f'failure-{r.run_id}.json', {'error': traceback.format_exc(), **C.stamps()})
            r.event('failure', error=traceback.format_exc()[-2000:])
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
