#!/usr/bin/env python3
"""Phase F, protocol F-v2: the F-v1 runner (rc_controlled.py, unchanged) with
three corrections, all on the Django side.

F-v1 accepted 0 of 8 blocks of Commercial System A non-indexed Django Q15
(F-fourpath/commercial_a-non-indexed-django/q15, 2026-10-09 20:33-20:54 Cairo)
although O and L agreed exactly in every block. Both causes were in the
runner, not in the measured code.

1. G: a column the query module adds in Python. Django's Q15 runs three
   statements - the maximum revenue, the suppliers with that revenue
   (HAVING), the supplier rows - and then adds total_revenue to each supplier
   row from the second statement, keyed by supplier (q15.py and
   q15_sqlserver.py, revenue_map). F-v1's replay returned the third
   statement's four columns, and every block was classified schema_error
   against L's five. In phase A on all four engines Q15 is the only query
   whose ORM path does this (Q11 and Q22 also run two statements, but their
   last statement returns every output column).
   F-v2's G applies the same step after the replay: a column of the ORM's
   output that the last statement does not return is taken from the nearest
   earlier replayed statement that returns it, joined on a column whose
   values are unique there and cover the last statement's values of one of
   its columns - Q15's suppkey and s_suppkey. The step is a dictionary
   lookup over a handful of rows inside G's timer, as the module's own step
   is inside O's, so O/G still isolates the ORM's client work. The G record
   says what was joined (g_assembly). If no such join exists, G's rows are
   returned as replayed and the block fails visibly, as in F-v1.

2. B on Commercial System A: commercial-a-django-backend's DECLARE rewrite. commercial-a-django-backend 1.8.0
   rewrites any statement that contains 'GROUP BY' and has parameters as
   'DECLARE @var0 <type> = ?, ... \\n' + statement
   (CursorWrapper.format_group_by_params). Django's handwritten Q15 is the
   only baseline that starts with WITH (all four engines), and the vendor dialect rejects a
   WITH whose preceding statement is not terminated: Msg 319, "Incorrect
   syntax near the keyword 'with'", in every B call. F-v2 puts ';' before
   such a WITH, on Commercial System A only and only when the rewrite applies, and
   records it in prep.json. B still runs through Django's cursor, so its
   values reach the server exactly as G's do.

3. Plans, Django on Commercial System A. Because of the same rewrite, a Django
   statement with GROUP BY and parameters runs with its values in DECLAREd
   local variables, which the optimizer compiles for without knowing the
   values. F-v1 captured those plans through parameterised batch parameters, whose
   values it does sniff. That is a different compilation. F-v2 captures them
   in the form that executes: the batch commercial-a-django-backend's own cursor builds,
   with each DECLARE taking its value as a literal (PLAN CAPTURE cannot take
   parameters; see rc_controlled.mssql_showplan_batch). Every other plan is
   captured as in F-v1.

4. B's date values, Django on Commercial System A. F-v1 gives each B value the value
   and Python type the ORM binds for it, except that a date the ORM binds as
   a string was skipped (bind_literals.orm_typed: `not isinstance(x, str)`),
   so B bound a datetime.date. commercial-a-django-backend binds every date as a string
   ('1993-07-01'), so G declared national-character(10) where B declared DATE, and
   G/B measured that type difference as well as the formulation it is meant
   to isolate. F-v1 cells affected: Commercial System A Django Q04 and Q20 (indexed),
   Q04 and Q15 (non-indexed), all with type_source 'param' in prep.json.
   F-v2 binds such a date with the ORM's own string, and the report says so.
   Django on MySQL also binds dates as strings, but mysqlclient interpolates
   on the client and writes a date and its ISO string as the same literal, so
   nothing reaches that server differently. PostgreSQL's and Oracle's Django
   backends bind dates as dates, which F-v1 already matched.

5. A G or B path over the limit in the cell warm-up censors the cell. F-v1
   has no such rule: on Commercial System A non-indexed, Django Q22's B (the
   handwritten text with its seven country codes in commercial-a-django-backend's DECLAREd
   variables) ran CPU-bound past 900 s (717 s CPU of 718 s elapsed, 79.6 M
   logical reads, no waits; L 0.69 s, G 8.0 s), and F-v1 would have repeated
   it in all 16 later executions, four hours for no paired ratio, since the
   decomposition needs all four paths in each block. Phase A censors a path
   that exceeds the limit in the cell warm-up; F-v2 applies the same rule and
   stops the cell after the warm-up block is decided. cell-done.json says
   'censored' and names the path; the warm-up records keep O, L and G's times
   and the timed-out path's limit. The cell's O/L remains phase A's.

Every other path, statement, comparison and decision is F-v1's. SQLAlchemy
cells are unaffected by all five and stay under F-v1.
"""
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402
import rc_controlled as F1  # noqa: E402

WITH_LEAD = re.compile(r'\s*WITH\b', re.I)


def mssql_declare_applies(sql, params):
    """commercial-a-django-backend's own condition for its DECLARE rewrite (CursorWrapper.execute)."""
    return 'GROUP BY' in sql and bool(params) and any(p is not None for p in params)


def assemble(last, earlier, missing):
    """The last statement's rows with the `missing` columns taken from an
    earlier statement, joined as the query module joins them; (rows, how) or
    (None, None) when no unambiguous join exists."""
    for i in range(len(earlier) - 1, -1, -1):
        rows = earlier[i]
        if not rows or any(k not in rows[0] for k in missing):
            continue
        for ek in rows[0]:
            if ek in missing:
                continue
            ev = [r[ek] for r in rows]
            if len(set(ev)) != len(ev):
                continue
            for gk in last[0]:
                gv = [r[gk] for r in last]
                if len(set(gv)) == len(gv) and set(gv) <= set(ev):
                    idx = {r[ek]: r for r in rows}
                    out = [{**r, **{k: idx[r[gk]][k] for k in missing}} for r in last]
                    return out, {'from_statement': i, 'columns': list(missing),
                                 'joined_on': {'earlier_statement_column': ek, 'last_statement_column': gk}}
    return None, None


class _Censored(Exception):
    """A G or B path exceeded the limit in the cell warm-up (correction 5)."""


class Controlled2(F1.Controlled):
    _g_columns = None
    _g_results = None
    _g_assembly = None
    _censored = ()

    def inventory(self, label):
        inv = super().inventory(label)
        inv['code_hashes']['rc_controlled2.py'] = C.file_sha256(HERE / 'rc_controlled2.py')
        return inv

    def prepare(self, fw, o_rec, l_rec, params):
        prep = super().prepare(fw, o_rec, l_rec, params)
        self._g_columns = list(o_rec.get('output_columns') or []) if fw == 'django' else None
        prep['G_output_columns'] = self._g_columns
        if fw == 'django':
            orm_flat = []
            for st in prep['G']:
                p = st['params']
                for v in (p.values() if isinstance(p, dict) else (p or [])):
                    orm_flat += F1.flat(v)
            str_dates = {F1.as_date(x): x for x in orm_flat if isinstance(x, str) and F1.as_date(x)}
            for st, rep in zip(prep['B']['statements'], prep['B']['report']):
                for j, r in enumerate(x for x in rep if x.get('bound')):
                    if r['kind'] == 'date' and r['type_source'] == 'param' and st['values'][j] in str_dates:
                        st['values'][j] = str_dates[st['values'][j]]
                        r.update(value_type='str', type_source='orm: bound as a string, as the ORM binds it '
                                                               '(F-v2 correction 4)')
        if fw == 'django' and self.a.dbms == 'sqlserver':
            for st in prep['B']['statements']:
                if WITH_LEAD.match(st['sql']) and mssql_declare_applies(st['sql'], st['values']):
                    st['sql'] = ';' + st['sql'].lstrip()
                    st['terminator_added'] = ("';' before WITH: mssql-django prepends DECLARE to statements "
                                              "with GROUP BY and parameters (F-v2 correction 2)")
        return prep

    def replay(self, fw, stmts):
        if fw != 'django':
            return super().replay(fw, stmts)
        results, rows = [], None
        for st in stmts:
            with self.dconn.cursor() as c:
                c.execute(st['sql'], st['params'])
                if c.description:
                    rows, _ = self.rows_from_cursor(c)
                    results.append(rows)
        self._g_results = results
        if rows and len(results) > 1 and self._g_columns:
            missing = [k for k in self._g_columns if k not in rows[0]]
            if missing:
                out, how = assemble(rows, results[:-1], missing)
                if out is not None:
                    self._g_assembly = how
                    return out
        return rows

    def run_cell(self, q):
        self._censored = []
        # on resume the warm-up block may already be decided: its decision
        # holds each path's status ('unavailable' comparisons carry them)
        d0 = self.run_dir / f'q{q:02d}' / 'b0' / 'decision.json'
        if d0.exists() and not (d0.parent.parent / 'cell-done.json').exists():
            comps = C.load(d0).get('comparisons') or {}
            self._censored = [k[0] for k in ('G=L', 'B=L') if (comps.get(k) or {}).get('status', [None])[0] == 'timeout']
        t0 = time.monotonic()
        try:
            super().run_cell(q)
        except _Censored:
            C.save(self.run_dir / f'q{q:02d}' / 'cell-done.json',
                   {'query': q, 'framework': self.a.framework, 'accepted_blocks': 0, 'status': 'censored',
                    'censored_paths': list(self._censored), 'limit_s': self.a.timeout,
                    'rule': 'a G or B path over the limit in the cell warm-up censors the cell (F-v2 correction 5)',
                    **C.stamps()}, immutable=True)
            self.event('cell_censored', query=q, paths=list(self._censored))
            self._finish_progress(q, time.monotonic() - t0)

    def _attempt(self, d):
        if self._censored and d.name != 'b0':
            raise _Censored()           # before block 1's attempt directory exists
        return super()._attempt(d)

    def exec4(self, q, fw, path, params, prep, ctx):
        if self._censored and ctx['block'] > 0:
            raise _Censored()
        self._g_results, self._g_assembly = None, None
        rec = super().exec4(q, fw, path, params, prep, ctx)
        if ctx['kind'] == 'cell_warmup' and path in ('G', 'B') and rec['status'] == 'timeout':
            self._censored.append(path)
        if path == 'G' and self._g_assembly:
            rec['g_assembly'] = {**self._g_assembly, 'statement_rows': self._g_results,
                                 'note': 'columns added after the replay as the query module adds them '
                                         '(F-v2 correction 1)'}
        return rec

    def explain(self, fw, sql, params, sizes=None):
        if not (fw == 'django' and self.a.dbms == 'sqlserver' and params
                and mssql_declare_applies(sql, list(params))):
            return super().explain(fw, sql, params, sizes)
        try:
            # the live commercial-a-django-backend cursor builds the DECLARE batch and formats
            # the values it binds, with the patches the source applies to both
            # (mssql_decimal_fix.py: Q22's average is quantised to scale 10
            # before binding; written unquantised it is out of range, 22003)
            with self.dconn.cursor() as dj:
                text, values = dj.cursor.format_group_by_params(sql, list(params))
                values = list(dj.cursor.format_params(values))
            decls = re.findall(r'(@var\d+) (.+?) = %s', text)
            if len(decls) != len(values):
                raise ValueError(f'{len(decls)} DECLARE entries for {len(values)} values')
            batch = text % tuple(F1.mssql_literal(v, t.lower()) for v, (_, t) in zip(values, decls))
            rc = self.dconn.connection.cursor()
            out = []
            rc.execute('SET SHOWPLAN_XML ON')
            try:
                rc.execute(batch)
                while True:
                    if rc.description:
                        out += rc.fetchall()
                    if not rc.nextset():
                        break
            finally:
                rc.execute('SET SHOWPLAN_XML OFF')
            return {'ok': True, 'plan': [list(r) for r in out], 'via': 'mssql-django DECLARE batch',
                    'declared': [f'{n} {t}' for n, t in decls],
                    'note': 'values in DECLAREd local variables, as executed (F-v2 correction 3)'}
        except Exception as exc:
            return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:1000]}


if __name__ == '__main__':
    F1.Controlled = Controlled2        # F1.main() constructs the runner by this name
    F1.main()
