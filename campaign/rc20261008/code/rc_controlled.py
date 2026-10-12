#!/usr/bin/env python3
"""Phase F: four-path decomposition of large ORM gaps (Reviewer 2, point 3).

For one framework of one cell, four paths run on the same input in the same
block, in Williams order, each warmed first:

  O  the ORM call (the paper's ORM path, unchanged);
  G  the ORM's own generated statements, replayed directly on the same driver
     with the same bound values - ORM client work removed, SQL text kept;
  B  the framework's handwritten SQL with its TPC-H substitution parameters
     bound, each with the value and Python type the ORM binds for it - the
     handwritten formulation, ORM's parameter interface;
  L  the handwritten SQL with literals (the paper's baseline, unchanged).

O/G isolates ORM client work, G/B the SQL formulation at matched bindings,
B/L the parameter interface. Every path's full result is compared with L's
before the block is accepted.

G's statements are captured from the same block's O warmup (pass-through, so
dependent statements - Django Q15 computes a maximum and filters by it - carry
the values the ORM actually bound); B is built from L's warmup statement by
replacing only literals equal to a substitution parameter of this input
(dates in any of the wrappers DATE '..', TO_DATE('..', fmt), CAST('..' AS DATE)
or a bare string; strings and LIKE patterns containing a parameter; numbers
only when the value occurs exactly once). Constants of the query stay literal.
A replacement that cannot be made unambiguously is recorded, not guessed.

EXPLAIN plans for G, B and L are captured once per cell, outside timing.
This file subclasses the frozen phase A runner and changes nothing in it.
"""
import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402
from rc_analytical import Runner, TIMEOUT_MARKERS  # noqa: E402

P4 = ('O', 'G', 'B', 'L')
# Williams order for four treatments, as in phase A, with O,G,B,L in the
# positions of django/sql, django/orm, sqlalchemy/sql, sqlalchemy/orm.
MAP = dict(zip(C.PATHS, ('L', 'O', 'B', 'G')))
WILLIAMS4 = tuple(tuple(MAP[p] for p in seq) for seq in C.WILLIAMS)

LIT = re.compile(r"""
    (?P<todate>TO_DATE\(\s*'(?P<td>[0-9]{4}-[0-9]{2}-[0-9]{2})'\s*,\s*'[^']*'\s*\))
  | (?P<cast>CAST\(\s*'(?P<cd>[0-9]{4}-[0-9]{2}-[0-9]{2})'\s+AS\s+DATE\s*\))
  | (?P<dlit>DATE\s+'(?P<dd>[0-9]{4}-[0-9]{2}-[0-9]{2})')
  | (?P<str>'(?P<s>(?:[^']|'')*)')
  | (?P<num>(?<![\w.])(?P<n>[0-9]+(?:\.[0-9]+)?)(?![\w.]))
""", re.I | re.X)


def flat(v):
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            out += flat(x)
        return out
    return [v]


def as_date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', v):
        return dt.date.fromisoformat(v)
    return None


def as_dec(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, Decimal)):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(repr(v))
    return None


def bind_literals(sql, params, orm_values, style):
    """Return (sql_b, values, report). style 'format' (%s) or 'named' (:bN)."""
    pvals = [x for v in params.values() for x in flat(v)]
    p_dates = {d for d in (as_date(x) for x in pvals) if d}
    p_nums = {d for d in (as_dec(x) for x in pvals) if d is not None}
    p_strs = [x for x in pvals if isinstance(x, str) and not as_date(x)]
    orm_flat = [x for v in orm_values for x in flat(v)]

    def orm_typed(kind, value):
        for x in orm_flat:
            if kind == 'date' and as_date(x) == value and not isinstance(x, str):
                return x, 'orm'
            if kind == 'num' and as_dec(x) == value:
                return x, 'orm'
            if kind == 'str' and isinstance(x, str) and x == value:
                return x, 'orm'
        return None, 'param'

    nums_count = {}
    for m in LIT.finditer(sql):
        if m.group('num'):
            nums_count[m.group('n')] = nums_count.get(m.group('n'), 0) + 1
    out, values, report, last = [], [], [], 0
    for m in LIT.finditer(sql):
        kind = value = None
        if m.group('todate') or m.group('cast') or m.group('dlit'):
            d = dt.date.fromisoformat(m.group('td') or m.group('cd') or m.group('dd'))
            if d in p_dates:
                kind, value = 'date', d
        elif m.group('str') is not None:
            s = m.group('s').replace("''", "'")
            d = as_date(s)
            if d and d in p_dates:
                kind, value = 'date', d
            else:
                rem = s
                for p in sorted((x for x in p_strs if x), key=len, reverse=True):
                    rem = rem.replace(p, '')
                # the literal is a parameter, or a LIKE pattern made only of
                # parameters and wildcards (Q13 '%special%requests%')
                if rem != s and set(rem) <= set('%_'):
                    kind, value = 'str', s
        elif m.group('num'):
            n = Decimal(m.group('n'))
            if n in p_nums:
                if nums_count[m.group('n')] == 1:
                    kind, value = 'num', n
                else:
                    report.append({'literal': m.group(0), 'bound': False, 'reason': 'value occurs more than once'})
        if kind is None:
            continue
        typed, source = orm_typed(kind, value)
        if typed is None:
            typed = {'date': value, 'num': value, 'str': value}[kind]
        out.append(sql[last:m.start()])
        out.append('%s' if style == 'format' else f':b{len(values)}')
        values.append(typed)
        report.append({'literal': m.group(0), 'bound': True, 'kind': kind,
                       'value_type': type(typed).__name__, 'type_source': source})
        last = m.end()
    out.append(sql[last:])
    text = ''.join(out)
    if style == 'format':
        # Django formats the statement with %; a literal % left in the text
        # must be doubled once parameters are passed.
        parts = []
        i = 0
        for chunk in re.split(r'(%s)', text):
            parts.append(chunk if chunk == '%s' else chunk.replace('%', '%%'))
        text = ''.join(parts)
    return text, values, report


# ----------------------------------------------------------- driver types
# The F pilot (Commercial System A, 2026-10-09) showed that the SQLAlchemy ORM binds with
# driver types - its dialect has bind_typing SETINPUTSIZES, so a String goes to
# pyodbc as varchar - while text() and driver-level statements get the driver's
# defaults (pyodbc: national-character, which forces Commercial System A to convert a varchar
# column). Q13: O 1.9 s, G 9.6 s, with byte-identical SQL and parameters. G and B
# must bind as the ORM does, or O/G and G/B measure a type mismatch, not ORM
# work and formulation. Affects commercial_a+odbc and oracle+oracledb; psycopg2 and
# mysqlclient bind on the client. Django's backends type statements inside
# their own cursors (commercial-a-django-backend: driver defaults; Oracle: _guess_input_sizes),
# so every Django path - O, G, B - binds alike already.

def sizes_repr(sizes):
    if not sizes:
        return None
    return [[str(k), repr(t), type(s).__name__ if s is not None else None] for k, t, s in sizes]


def driver_form(sql, values, paramstyle):
    """B's :bN text to the driver's parameter style, values in marker order."""
    order = [int(m.group(1)) for m in re.finditer(r'(?<![\w:]):b(\d+)\b', sql)]
    if paramstyle == 'named':
        return sql, {f'b{i}': values[i] for i in order}
    if paramstyle == 'qmark':
        return re.sub(r'(?<![\w:]):b(\d+)\b', '?', sql), [values[i] for i in order]
    # format / pyformat (psycopg2, mysqlclient): %s markers, literal % doubled
    parts = re.split(r'((?<![\w:]):b\d+\b)', sql)
    out = ''.join('%s' if re.fullmatch(r':b\d+', p) else p.replace('%', '%%') for p in parts)
    return out, [values[i] for i in order]


_PYODBC_DECL = {12: 'varchar(8000)', -9: 'nvarchar(4000)', 1: 'varchar(8000)', -8: 'nvarchar(4000)',
                -1: 'varchar(max)', -10: 'nvarchar(max)', 4: 'int', 5: 'smallint', -6: 'tinyint', -5: 'bigint',
                8: 'float', 6: 'float', 7: 'real', 91: 'date', 93: 'datetime2', -7: 'bit'}


def mssql_decl(dbtype, value):
    """Declared type of one parameter: the bound driver type, else pyodbc's default for the Python value."""
    code = dbtype[0] if isinstance(dbtype, tuple) else dbtype
    if code in (2, 3):                         # SQL_NUMERIC / SQL_DECIMAL
        dbtype, code = None, None
    if code in _PYODBC_DECL:
        return _PYODBC_DECL[code]
    if isinstance(value, bool):
        return 'bit'
    if isinstance(value, int):
        return 'int' if -2 ** 31 <= value < 2 ** 31 else 'bigint'
    if isinstance(value, float):
        return 'float'
    if isinstance(value, Decimal):
        sign, digits, exp = value.as_tuple()
        scale = max(0, -exp)
        return f'decimal({min(38, max(len(digits), scale, 1))},{scale})'
    if isinstance(value, dt.datetime):
        return 'datetime2'
    if isinstance(value, dt.date):
        return 'date'
    return 'nvarchar(4000)'                     # pyodbc binds str as SQL_WVARCHAR


def mssql_literal(value, decl):
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, dt.datetime):
        return "'" + value.isoformat(sep='T') + "'"
    if isinstance(value, dt.date):
        return "'" + value.isoformat() + "'"
    return ('N' if decl.startswith('n') else '') + "'" + str(value).replace("'", "''") + "'"


def mssql_showplan_batch(sql, params, sizes, style):
    """A parameterized statement as EXEC parameterised batch with declared types, so
    PLAN CAPTURE_XML returns the plan of the statement as it is bound (pyodbc's
    own parameterized execution returns no result under PLAN CAPTURE)."""
    vals = list(params.values()) if isinstance(params, dict) else list(params or [])
    n = [0]

    def nxt(_=None):
        n[0] += 1
        return f'@P{n[0]}'
    if style == 'format':                       # Django: %s markers, %% literal
        inner = re.sub(r'%%|%s', lambda m: '%' if m.group() == '%%' else nxt(), sql)
    else:                                       # pyodbc qmark
        inner = re.sub(r'\?', nxt, sql)
    if n[0] != len(vals):
        raise ValueError(f'{n[0]} markers for {len(vals)} values')
    dbtypes = [t for _, t, _ in sizes] if sizes else [None] * len(vals)
    decls = [mssql_decl(t, v) for t, v in zip(dbtypes, vals)]
    assigns = ', '.join(f'@P{i + 1} = {mssql_literal(v, d)}' for i, (v, d) in enumerate(zip(vals, decls)))
    return ("EXEC sp_executesql N'" + inner.replace("'", "''") + "', N'" +
            ', '.join(f'@P{i + 1} {d}' for i, d in enumerate(decls)) + "'" + (', ' + assigns if assigns else ''),
            decls)


class Controlled(Runner):
    def _types_install(self):
        """Record, per statement, the driver types SQLAlchemy sets for the ORM
        call (dialect.do_set_input_sizes runs before before_cursor_execute)."""
        if getattr(self, '_types_ready', False):
            return
        from sqlalchemy import event
        from sqlalchemy.engine import BindTyping
        d = self.engine.dialect
        self.typed = d.bind_typing is BindTyping.SETINPUTSIZES
        self._orig_set_sizes = d.do_set_input_sizes
        self._sizes_pending, self._size_trace, self._o_sizes = None, None, []
        self._prep_sizes = {'G': [], 'B': []}
        orig = self._orig_set_sizes

        def capture(cursor, list_of_tuples, context):
            self._sizes_pending = list(list_of_tuples)
            return orig(cursor, list_of_tuples, context)
        d.do_set_input_sizes = capture

        @event.listens_for(self.engine, 'before_cursor_execute')
        def _attach(conn, cursor, statement, parameters, context, executemany):
            if self._size_trace is not None:
                self._size_trace.append(self._sizes_pending)
            self._sizes_pending = None
        self._types_ready = True

    def _driver_ctx(self):
        from sqlalchemy.engine.interfaces import ExecuteStyle
        return type('DriverCtx', (), {'execute_style': ExecuteStyle.EXECUTE})()

    def _typed_execute(self, sql, params, sizes):
        """One statement on the SQLAlchemy connection's driver cursor, bound
        with the given driver types; recorded in the statement trace."""
        raw = self.session.connection().connection.dbapi_connection
        cur = raw.cursor()
        try:
            if sizes:
                self._orig_set_sizes(cur, sizes, self._driver_ctx())
            if self.sa_trace is not None:
                self.sa_trace.append({'sql': sql, 'params': params, 'inputsizes': sizes_repr(sizes),
                                      'driver_cursor': True})
            cur.execute(sql, params)
            if cur.description:
                rows, names = self.rows_from_cursor(cur)
                if self.sa_trace:
                    self.sa_trace[-1]['columns'] = names
                return rows
            return None
        finally:
            cur.close()

    def inventory(self, label):
        inv = super().inventory(label)
        inv['code_hashes']['rc_controlled.py'] = C.file_sha256(HERE / 'rc_controlled.py')
        return inv

    # ------------------------------------------------------------- execution
    def rows_from_cursor(self, cur):
        names = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(names, r)) for r in cur.fetchall()], names

    def replay(self, fw, stmts):
        rows, names = None, None
        if fw == 'sqlalchemy' and self.typed:
            for i, st in enumerate(stmts):
                sz = self._prep_sizes['G'][i] if i < len(self._prep_sizes['G']) else None
                r = self._typed_execute(st['sql'], st['params'], sz)
                if r is not None:
                    rows = r
            return rows
        for st in stmts:
            if fw == 'django':
                with self.dconn.cursor() as c:
                    c.execute(st['sql'], st['params'])
                    if c.description:
                        rows, names = self.rows_from_cursor(c)
            else:
                res = self.session.connection().exec_driver_sql(st['sql'], st['params'])
                if res.returns_rows:
                    names = list(res.keys())
                    rows = [dict(zip(names, r)) for r in res.fetchall()]
        return rows

    def run_bound(self, fw, b):
        from sqlalchemy import text
        rows = None
        if fw == 'sqlalchemy' and self.typed:
            style = self.engine.dialect.paramstyle
            for i, st in enumerate(b['statements']):
                sql, params = driver_form(st['sql'], st['values'], style)
                sz = self._prep_sizes['B'][i] if i < len(self._prep_sizes['B']) else None
                r = self._typed_execute(sql, params, sz)
                if r is not None:
                    rows = r
            return rows
        for st in b['statements']:
            if fw == 'django':
                with self.dconn.cursor() as c:
                    c.execute(st['sql'], st['values'])
                    if c.description:
                        rows, _ = self.rows_from_cursor(c)
            else:
                res = self.session.execute(text(st['sql']), {f'b{i}': v for i, v in enumerate(st['values'])})
                if res.returns_rows:
                    names = list(res.keys())
                    rows = [dict(zip(names, r)) for r in res.fetchall()]
        return rows

    def exec4(self, q, fw, path, params, prep, ctx):
        a = self.a
        self.ensure_armed(a.timeout)
        dj, sa = self.mods
        trace = []

        def dj_wrap(execute, sql, prm, many, context):
            item = {'sql': sql, 'params': prm, 'many': many}
            trace.append(item)
            res = execute(sql, prm, many, context)
            cur = context.get('cursor')
            try:
                item['columns'] = [d[0] for d in cur.description] if cur is not None and cur.description else []
            except Exception:
                item['columns'] = None
            return res
        rec = {'campaign': self.protocol['campaign_id'], 'protocol_id': self.protocol['protocol_id'],
               'protocol_sha256': self.protocol_sha, 'phase': a.phase, 'run_id': self.run_id, 'dbms': a.dbms,
               'schema': a.schema, 'scale': a.scale, 'database_label': a.database_label, 'query': q,
               'framework': fw, 'path': f'{fw}/{path}', 'kind': ctx['kind'], 'block': ctx['block'],
               'attempt': ctx['attempt'], 'sequence_id': ctx.get('sequence_id'), 'position': ctx.get('position'),
               'input_id': ctx['input_id'], 'parameters': params, 'timeout_s': a.timeout,
               'environment_id': self.env_id, 'source_sha256': self.source_sha,
               'dataset_id': self.protocol['dataset_ids'].get(f'{a.dbms}:sf{a.scale}'),
               'server_session': dict(self.sids).get(fw), 'pid': os.getpid(),
               'load1_before': os.getloadavg()[0], 'start': C.stamps()}
        self.save_progress(state='executing', current={'query': q, 'path': f'{fw}/{path}', 'kind': ctx['kind'],
                                                        'block': ctx['block'], **C.stamps()})
        rows = None
        self.sa_trace = trace if fw == 'sqlalchemy' else None
        # the driver types the ORM call binds with, per statement (see sizes_repr)
        self._size_trace = [] if (fw == 'sqlalchemy' and path == 'O') else None
        t0 = time.perf_counter()
        try:
            with self.dconn.execute_wrapper(dj_wrap):
                if path == 'O':
                    rows = dj.run_query_orm(using='default', params=params) if fw == 'django' else \
                        sa.run_query_orm(self.session, params=params)
                elif path == 'L':
                    rows = dj.run_query_sql(self.dconn, params=params) if fw == 'django' else \
                        sa.run_query_sql(self.session, params=params)
                elif path == 'G':
                    rows = self.replay(fw, prep['G'])
                else:
                    rows = self.run_bound(fw, prep['B'])
            elapsed = time.perf_counter() - t0
            rec['status'] = 'ok'
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            msg = f'{type(exc).__name__}: {exc}'
            rec.update(status='timeout' if any(m in msg.lower() for m in TIMEOUT_MARKERS) or elapsed >= 0.9 * a.timeout
                       else 'error', error=msg[:2000], traceback=traceback.format_exc()[-3000:])
        finally:
            self.sa_trace = None
            if self._size_trace is not None:
                self._o_sizes, self._size_trace = self._size_trace, None
                for i, item in enumerate(trace):
                    item['inputsizes'] = sizes_repr(self._o_sizes[i] if i < len(self._o_sizes) else None)
        rec['elapsed_s'] = elapsed
        rec['end'] = C.stamps()
        rec['statements'] = trace
        if rows is not None:
            if not isinstance(rows, list):
                rec['status'] = 'invalid_return_type'
                rows = list(rows)
            rec['rows'] = rows
            rec['rows_returned'] = len(rows)
            rec['result_sha256'] = C.digest(rows)
            rec['output_columns'] = list(rows[0]) if rows else (trace[-1].get('columns') if trace else None)
        if rec['status'] in ('timeout', 'error'):
            rec['recovery'] = self.recover(rec['status'])
            if not rec['recovery']['server_work_stopped_verified']:
                rec['fatal'] = 'server work after cancellation could not be shown to have stopped'
        return rec

    # ------------------------------------------------------------ preparation
    def prepare(self, fw, o_rec, l_rec, params):
        """G from O's captured statements; B from L's, both from this block."""
        if fw == 'django':
            g = [{'sql': s['sql'], 'params': s['params']} for s in o_rec.get('statements') or []]
        else:
            g = [{'sql': s['sql'], 'params': s['params']} for s in o_rec.get('statements') or []]
        orm_values = []
        for s in g:
            p = s['params']
            orm_values += list(p.values()) if isinstance(p, dict) else list(p or [])
        b_statements, report = [], []
        if fw == 'django':
            # Django's baseline executes its text without parameters, so the
            # captured statement is the handwritten text itself.
            sources = [s['sql'] for s in l_rec.get('statements') or []]
        else:
            # SQLAlchemy's captured statement is driver-level text (percent
            # signs already doubled for the driver); build B from the
            # handwritten text the baseline passes to text().
            from sqlalchemy_app.queries._sql import sql_for
            sources = [sql_for(l_rec['query'], self.session.bind.dialect.name, params)]
        for src_sql in sources:
            text, values, rep = bind_literals(src_sql, params, orm_values, 'format' if fw == 'django' else 'named')
            b_statements.append({'sql': text, 'values': values})
            report.append(rep)
        bound = sum(1 for r in report for x in r if x.get('bound'))
        # Driver types (SQLAlchemy on a SETINPUTSIZES dialect only): G binds with
        # the ORM call's own types; each B value takes the type the ORM bound the
        # equal value with. A B value without an ORM counterpart leaves that
        # statement on the driver's defaults, and the record says so.
        self._prep_sizes = {'G': [], 'B': []}
        if fw == 'sqlalchemy' and self.typed:
            o_sizes = list(self._o_sizes or [])
            self._prep_sizes['G'] = [o_sizes[i] if i < len(o_sizes) else None for i in range(len(g))]
            vmap = []
            for st, sz in zip(g, self._prep_sizes['G']):
                p = st['params']
                for j, (key, dbtype, sqltype) in enumerate(sz or []):
                    val = p.get(key) if isinstance(p, dict) else (list(p)[j] if j < len(p) else None)
                    vmap.append((val, dbtype, sqltype))
            for bst in b_statements:
                tuples, unmatched = [], 0
                for j, v in enumerate(bst['values']):
                    hit = next(((dbt, sqt) for val, dbt, sqt in vmap if type(val) is type(v) and val == v), None)
                    if hit is None:
                        unmatched += 1
                    tuples.append((f'b{j}', hit[0] if hit else None, hit[1] if hit else None))
                self._prep_sizes['B'].append(None if (unmatched or not tuples) else tuples)
                bst['binding_types'] = ('orm' if tuples and not unmatched else 'driver defaults' +
                                        (f' ({unmatched} value(s) without an ORM counterpart)' if unmatched else ''))
                bst['inputsizes'] = sizes_repr(self._prep_sizes['B'][-1])
            for st, sz in zip(g, self._prep_sizes['G']):
                st['inputsizes'] = sizes_repr(sz)
        return {'G': g, 'B': {'statements': b_statements, 'report': report, 'bound_literals': bound}}

    def explain(self, fw, sql, params, sizes=None):
        """Plan of one statement without executing it. sql/params are as the
        path sends them: Django '%s' text through Django's cursor; SQLAlchemy
        driver-level text and parameters (G) or B already in driver form."""
        d = self.a.dbms
        extra = {}
        try:
            if fw == 'django':
                c = self.dconn.cursor()
            else:
                c = self.session.connection().connection.dbapi_connection.cursor()
            if d == 'postgresql':
                c.execute('EXPLAIN (FORMAT JSON) ' + sql, params)
                out = c.fetchall()
            elif d == 'mysql':
                c.execute('EXPLAIN FORMAT=JSON ' + sql, params)
                out = c.fetchall()
            elif d == 'sqlserver':
                raw = self.dconn.connection if fw == 'django' else self.session.connection().connection.dbapi_connection
                rc = raw.cursor()
                if params:
                    batch, decls = mssql_showplan_batch(sql, params, sizes, 'format' if fw == 'django' else 'qmark')
                    extra = {'declared_types': decls, 'via': 'sp_executesql'}
                else:
                    batch = sql.replace('%%', '%') if fw == 'django' else sql
                rc.execute('SET SHOWPLAN_XML ON')
                try:
                    rc.execute(batch)
                    out = rc.fetchall()
                finally:
                    rc.execute('SET SHOWPLAN_XML OFF')
            else:
                sid = f'rc{int(time.time() * 1000) % 10**9}'
                stmt, binds = sql, params
                if fw == 'django':
                    n = [0]

                    def sub(m):
                        if m.group() == '%%':
                            return '%'
                        n[0] += 1
                        return f':p{n[0]}'
                    stmt = re.sub(r'%%|%s', sub, sql)
                    binds = {f'p{i + 1}': v for i, v in enumerate(params or [])}
                raw = self.dconn.connection if fw == 'django' else self.session.connection().connection.dbapi_connection
                rc = raw.cursor()
                # EXPLAIN PLAN does not peek binds (Oracle treats them as
                # VARCHAR2), but the driver still needs a value per marker
                rc.execute(f"EXPLAIN PLAN SET STATEMENT_ID = '{sid}' FOR " + stmt, binds or {})
                rc.execute("SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', :1, 'ALL'))", [sid])
                out = rc.fetchall()
                extra = {'note': 'EXPLAIN PLAN does not peek bind values'} if binds else {}
            return {'ok': True, 'plan': [list(r) for r in out], **extra}
        except Exception as exc:
            try:
                self.session.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:1000]}

    # --------------------------------------------------------------- the cell
    def run_cell(self, q):
        a = self.a
        fw = a.framework
        cdir = self.run_dir / f'q{q:02d}'
        if (cdir / 'cell-done.json').exists():
            return
        t_cell = time.monotonic()
        self._types_install()
        self.mods = self.modules(q)
        inp = self.inputs['queries'][str(q)]
        seed, plan = C.block_plan(f"{self.protocol['protocol_id']}:{a.dbms}:{a.schema}:sf{a.scale}:{a.database_label}:q{q}:{fw}:F")
        plan = plan[:a.blocks]
        if not (cdir / 'plan.json').exists():
            C.save(cdir / 'plan.json', {'seed': seed, 'block_sequences': plan, 'williams4': WILLIAMS4,
                                        'warmup_order': 'O, L, G, B (G and B are built from the O and L warmups)'})
        cell = {'blocks': {}}
        for b in range(0, a.blocks + 1):
            bdir = cdir / f'b{b}'
            if (bdir / 'decision.json').exists():
                continue
            if b == 0:
                params, input_id = inp['warmup'], f'q{q:02d}warm'
            else:
                params, input_id = inp['sets'][b - 1], inp['set_ids'][b - 1]
            att = self._attempt(bdir)
            kind_w = 'cell_warmup' if b == 0 else 'block_warmup'
            warm = {}
            for path in ('O', 'L'):
                r = self.exec4(q, fw, path, params, None, {'kind': kind_w, 'block': b, 'attempt': att,
                                                            'position': -1, 'input_id': input_id})
                self.record(f'q{q:02d}/b{b}/a{att}/warm-{fw}-{path}.json.gz', r)
                warm[path] = r
            if warm['O']['status'] != 'ok' or warm['L']['status'] != 'ok':
                dec = {'block': b, 'attempt': att, 'stop': 'O or L warmup failed',
                       'status': {p: warm[p]['status'] for p in warm}, **C.stamps()}
                C.save(bdir / 'decision.json', dec, immutable=True)
                C.save(cdir / 'cell-done.json', {'query': q, 'framework': fw, 'status': 'stopped: ' + dec['stop'], **C.stamps()}, immutable=True)
                return
            prep = self.prepare(fw, warm['O'], warm['L'], params)
            C.save(bdir / f'a{att}' / 'prep.json', prep, immutable=True)
            if b == 1 and not (cdir / 'plans.json').exists():
                if fw == 'sqlalchemy':
                    style = self.engine.dialect.paramstyle
                    b_plans = []
                    for i, s in enumerate(prep['B']['statements']):
                        bsql, bpar = driver_form(s['sql'], s['values'], style)
                        sz = self._prep_sizes['B'][i] if i < len(self._prep_sizes['B']) else None
                        b_plans.append(self.explain(fw, bsql, bpar, sz))
                    g_plans = [self.explain(fw, s['sql'], s['params'],
                                            self._prep_sizes['G'][i] if i < len(self._prep_sizes['G']) else None)
                               for i, s in enumerate(prep['G'])]
                else:
                    b_plans = [self.explain(fw, s['sql'], s['values']) for s in prep['B']['statements']]
                    g_plans = [self.explain(fw, s['sql'], s['params']) for s in prep['G']]
                plans = {'G': g_plans,
                         'B': b_plans,
                         'L': [self.explain(fw, s['sql'], s.get('params')) for s in warm['L'].get('statements') or []],
                         'note': 'EXPLAIN without execution, once per cell on input set 0, outside every timer'}
                C.save(cdir / 'plans.json', plans, immutable=True)
                self.arm(a.timeout)       # PLAN CAPTURE or EXPLAIN may have touched session state
            for path in ('G', 'B'):
                r = self.exec4(q, fw, path, params, prep, {'kind': kind_w, 'block': b, 'attempt': att,
                                                           'position': -1, 'input_id': input_id})
                self.record(f'q{q:02d}/b{b}/a{att}/warm-{fw}-{path}.json.gz', r)
                warm[path] = r
            timed = {}
            if b > 0:
                seq = WILLIAMS4[plan[b - 1]]
                for pos, path in enumerate(seq):
                    r = self.exec4(q, fw, path, params, prep, {'kind': 'timed', 'block': b, 'attempt': att,
                                                               'sequence_id': plan[b - 1], 'position': pos,
                                                               'input_id': input_id})
                    self.record(f'q{q:02d}/b{b}/a{att}/timed-{fw}-{path}.json.gz', r)
                    timed[path] = r
            src = timed if b > 0 else warm
            pol = self.protocol['result_policy']['version']
            comps = {}
            for path in ('O', 'G', 'B'):
                x, l = src.get(path, {}), src['L']
                if x.get('status') == 'ok' and l.get('status') == 'ok':
                    c = C.compare(q, l['rows'], x['rows'], l.get('output_columns'), x.get('output_columns'), policy=pol)
                    if c['classification'] == 'schema_error' and path == 'G' and src['O'].get('rows'):
                        # Replayed statements carry the database's column labels;
                        # the ORM renames them. Same statement, same order: map
                        # positionally onto the ORM's names and compare again.
                        okeys = list(src['O']['rows'][0])
                        if x['rows'] and len(x['rows'][0]) == len(okeys):
                            ren = [dict(zip(okeys, r.values())) for r in x['rows']]
                            c = C.compare(q, l['rows'], ren, None, None, policy=pol)
                            c['renamed_positionally_to_orm_columns'] = True
                    elif c['classification'] == 'schema_error' and path == 'B' and l.get('rows'):
                        # B on the driver cursor (typed SQLAlchemy path) carries the
                        # driver's labels (Oracle: upper case); it is L's own
                        # statement, so map positionally onto L's names.
                        lkeys = list(l['rows'][0])
                        if x['rows'] and len(x['rows'][0]) == len(lkeys):
                            ren = [dict(zip(lkeys, r.values())) for r in x['rows']]
                            c = C.compare(q, l['rows'], ren, None, None, policy=pol)
                            c['renamed_positionally_to_baseline_columns'] = True
                    comps[f'{path}=L'] = c
                else:
                    comps[f'{path}=L'] = {'classification': 'unavailable', 'accepted': False,
                                          'status': [x.get('status', 'not_run'), l.get('status')]}
            # Acceptance is about results only; a B with no literal bound is
            # the L text again and its B/L ratio is reported as uninformative.
            accepted = all(v['accepted'] for v in comps.values())
            ratios = {}
            if b > 0 and all(src[p]['status'] == 'ok' for p in P4):
                e = {p: src[p]['elapsed_s'] for p in P4}
                ratios = {'O/G': e['O'] / e['G'], 'G/B': e['G'] / e['B'], 'B/L': e['B'] / e['L'], 'O/L': e['O'] / e['L']}
            dec = {'query': q, 'framework': fw, 'block': b, 'attempt': att, 'input_id': input_id,
                   'sequence_id': plan[b - 1] if b > 0 else None, 'comparisons': comps, 'accepted': accepted,
                   'bound_literals': prep['B']['bound_literals'], 'ratios': ratios, 'policy': pol,
                   'records': {p: f"a{att}/{'timed' if b > 0 else 'warm'}-{fw}-{p}.json.gz" for p in P4},
                   **C.stamps()}
            C.save(bdir / 'decision.json', dec, immutable=True)
            self.event('block_decided', query=q, framework=fw, block=b, accepted=accepted,
                       classes={k: v['classification'] for k, v in comps.items()},
                       ratios={k: round(v, 4) for k, v in ratios.items()})
            self.save_progress(state='block_decided')
            if b > 0:
                cell['blocks'][b] = {'accepted': accepted, 'ratios': ratios}
        ok = [v['ratios'] for v in cell['blocks'].values() if v['accepted'] and v['ratios']]
        summary = {'query': q, 'framework': fw, 'accepted_blocks': len(ok), 'status': 'complete', **C.stamps()}
        if len(ok) == a.blocks:
            summary['paired_median'] = {k: math.exp(statistics.median(math.log(r[k]) for r in ok)) for k in ok[0]}
        C.save(cdir / 'cell-done.json', summary, immutable=True)
        self._finish_progress(q, time.monotonic() - t_cell)

    def _finish_progress(self, q, secs):
        p = self.progress
        p.setdefault('cells_done', []).append({'query': q, 'wall_s': secs})
        self.event('cell_done', query=q, wall_s=round(secs, 1))
        self.save_progress(state='cell_done')


def main():
    ap = argparse.ArgumentParser()
    for x in ('--campaign-dir', '--run-dir', '--protocol'):
        ap.add_argument(x, type=Path, required=True)
    ap.add_argument('--src', type=Path)
    ap.add_argument('--phase', default='F')
    ap.add_argument('--dbms', required=True, choices=['postgresql', 'mysql', 'oracle', 'sqlserver'])
    ap.add_argument('--schema', required=True, choices=['indexed', 'non-indexed'])
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--database-label', default='tpch')
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--framework', choices=['django', 'sqlalchemy'], required=True)
    ap.add_argument('--timeout', type=float, default=900)
    ap.add_argument('--blocks', type=int, default=8)
    ap.add_argument('--mode', choices=['main', 'pilot'], default='main')
    ap.add_argument('--client-mode', default='same-host')
    ap.add_argument('--client-cpus', default='2,3')
    ap.add_argument('--cancel-wait', type=float, default=60)
    ap.add_argument('--crash-at', type=int, default=0)
    ap.add_argument('--cancel-test-query', type=int, default=0)
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()
    Controlled(a).main()


if __name__ == '__main__':
    main()
