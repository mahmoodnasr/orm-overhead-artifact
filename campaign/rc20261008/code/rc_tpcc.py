#!/usr/bin/env python3
"""Transaction runner for campaign rc20261008: matched inputs, verified state, balanced order.

What the historical TPC-C harness (scripts/2-benchmark/run_tpcc.py) did, and
what this changes:

  * Inputs. Every transaction function draws its keys from the module-level
    `random` inside the function; the harness built a seeded Random and the
    path lambdas discarded it, and nothing seeded the global generator. Inputs
    therefore differed across paths, repetitions and runs. Here the global
    generator is seeded with the block's seed S immediately before each call,
    so all four paths draw identical keys, and the same draw sequence replayed
    on random.Random(S) predicts them (checked against the returned keys).
  * State. Paths ran one after another on whatever the previous one left.
    Here every call starts from the block's verified starting state: the
    rows the input can touch are captured before the call (outside the timer),
    captured again after, the committed difference is recorded, the before-
    image is written back, and the scope is re-read and must equal it exactly.
    Table row counts are checked around every block and a full content
    fingerprint around every phase.
  * Order. The four paths run in Williams sequences (24 blocks = six seeded
    cycles of the four sequences), each path warmed on the block input first.
  * Equivalence. A framework's ORM and SQL calls in a block are accepted only
    if their committed differences agree column by column (three declared
    clock columns are checked for presence and a time window instead of
    equality), their declared common outputs agree, and both reverts verified.
    Differences in which tables the statements touched are recorded.

Timer: perf_counter around the transaction function, which commits inside;
statement-capture hooks inside, as in the analytical runner. Seeding, capture,
revert, verification and the SQLAlchemy session's post-call rollback (which
ends the read transaction expire_on_commit can leave open) are outside it.
"""
import argparse
import datetime as dt
from decimal import Decimal
import fcntl
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import re
import socket
import subprocess
import sys
import time
import traceback
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

TX = {1: ('T1', 'New-Order', 't1_neworder', 't1'), 2: ('T2', 'Payment', 't2_payment', 't2'),
      3: ('T3', 'Order-Status', 't3_orderstatus', 't3'), 4: ('T4', 'Delivery', 't4_delivery', 't4'),
      5: ('T5', 'Stock-Level', 't5_stocklevel', 't5')}
TABLES = ['warehouse', 'district', 'customer', 'history', 'item', 'stock', 'order', 'new_order', 'order_line']
CLOCK_COLUMNS = {'order': {'o_entry_d'}, 'history': {'h_date'}, 'order_line': {'ol_delivery_d'}}
KEYS = {'warehouse': ['w_id'], 'district': ['d_w_id', 'd_id'], 'customer': ['c_w_id', 'c_d_id', 'c_id'],
        'item': ['i_id'], 'stock': ['s_w_id', 's_i_id'], 'order': ['o_w_id', 'o_d_id', 'o_id'],
        'new_order': ['no_w_id', 'no_d_id', 'no_o_id'],
        'order_line': ['ol_w_id', 'ol_d_id', 'ol_o_id', 'ol_number']}
# Outputs every path of a transaction returns (from the code study; other keys
# differ by path and are recorded, not compared).
COMMON_OUTPUT = {1: ['w_id', 'd_id', 'c_id', 'o_id', 'total_amount'],
                 2: ['w_id', 'd_id', 'c_id', 'payment', 'c_balance'],
                 3: ['w_id', 'd_id', 'c_id', 'c_first', 'c_last', 'c_balance', 'o_id'],
                 4: ['w_id', 'carrier_id', 'orders_delivered'],
                 5: ['w_id', 'd_id', 'threshold', 'low_stock_count']}
CLOCK_TOLERANCE_S = 2.0
TABLE_RE = re.compile(r'\b(?:from|join|update|into)\s+[`"\[]?(\w+)[`"\]]?', re.I)


def predict(t, seed, cfg):
    """Replay the draw sequence of transaction t (code study, section 3)."""
    r = random.Random(seed)
    if t in (1, 2, 3):
        w, d, c, ol_cnt = cfg.pick_keys(r)
        out = {'w_id': w, 'd_id': d, 'c_id': c}
        if t == 1:
            out['ol_cnt'] = ol_cnt
            out['items'] = [(r.randint(1, cfg.ITEMS), r.randint(1, 10)) for _ in range(ol_cnt)]
        if t == 2:
            out['payment'] = r.uniform(1.0, 5000.0)
        return out
    if t == 4:
        return {'w_id': r.randint(1, cfg.WAREHOUSES), 'carrier_id': r.randint(1, 10)}
    return {'w_id': r.randint(1, cfg.WAREHOUSES), 'd_id': r.randint(1, cfg.DISTRICTS_PER_WAREHOUSE),
            'threshold': r.randint(10, 20)}


class Tx:
    def __init__(self, a):
        self.a = a
        self.run_dir = a.run_dir.resolve()
        self.campaign = a.campaign_dir.resolve()
        # Phase C runs from src-c, the worktree carrying the two baseline
        # corrections confirmed by the transaction pilot; pilots ran from src.
        self.src = (a.src or (self.campaign / 'src')).resolve()
        self.run_id = uuid.uuid4().hex
        self.progress = {'counts': {}}

    # ---------------------------------------------------------------- infra
    def event(self, event_name, **kw):
        rec = {'event': event_name, 'run_id': self.run_id, 'pid': os.getpid(), **C.stamps(), **kw}
        C.append_jsonl(self.run_dir / 'events.jsonl', rec)
        print(json.dumps(C.typed(rec), default=str)[:400], flush=True)

    def save_progress(self, **kw):
        self.progress.update(kw, **C.stamps())
        C.save(self.run_dir / 'progress.json', self.progress)

    def bump(self, key, n=1):
        self.progress['counts'][key] = self.progress['counts'].get(key, 0) + n

    def lock(self):
        self._lockfh = open(self.campaign / 'server.lock', 'a+')
        try:
            fcntl.flock(self._lockfh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('another campaign process holds server.lock')
        C.save(self.campaign / 'server-lock-holder.json',
               {'pid': os.getpid(), 'run_id': self.run_id, 'argv': sys.argv, **C.stamps()})

    def setup(self):
        a = self.a
        if a.client_cpus and os.sched_getaffinity(0) != {int(c) for c in a.client_cpus.split(',')}:
            raise SystemExit('client affinity wrong; use taskset')
        self.protocol = C.load(a.protocol)
        self.protocol_sha = C.file_sha256(a.protocol)
        if self.run_dir.exists() and any(self.run_dir.iterdir()) and not a.resume:
            raise SystemExit('run dir has records; pass --resume')
        self.run_dir.mkdir(parents=True, exist_ok=True)
        params = {'protocol_id': self.protocol['protocol_id'], 'protocol_sha256': self.protocol_sha,
                  'dbms': a.dbms, 'schema': a.schema, 'transactions': a.transactions, 'blocks': a.blocks,
                  'mode': a.mode, 'phase': a.phase}
        rp = self.run_dir / 'run-parameters.json'
        if rp.exists():
            if json.loads(rp.read_text()) != C.typed(params):
                raise SystemExit('resume with different parameters')
        else:
            C.save(rp, params, immutable=True)
        os.chdir(self.src)
        sys.path.insert(0, str(self.src))
        import django
        django.setup()
        from django.db import connections
        import tpcc_config
        self.cfg = tpcc_config
        self.dconn = connections['default']
        from sqlalchemy import create_engine, event
        from sqlalchemy.engine import make_url
        from sqlalchemy.orm import Session
        from sqlalchemy.sql.elements import TextClause
        url = make_url(os.environ['SA_DSN'])
        self.sa_url_public = url.render_as_string(hide_password=True)
        self.engine = create_engine(url, future=True)
        self.session = Session(self.engine)
        # The control connection: captures, reverts and checks. Autocommit, its
        # own engine, never used by a measured path.
        self.ctl = create_engine(url, future=True, isolation_level='AUTOCOMMIT').connect()
        self.trace = None

        @event.listens_for(self.engine, 'before_cursor_execute')
        def _b(conn, cursor, statement, parameters, context, executemany):
            if self.trace is not None:
                obj = getattr(getattr(context, 'compiled', None), 'statement', None)
                self.trace.append({'sql': statement, 'params': parameters,
                                   'text_clause': isinstance(obj, TextClause)})
        d = a.dbms
        self.order_tbl = {'postgresql': '"order"', 'mysql': '`order`', 'sqlserver': '[order]',
                          'oracle': '"ORDER"'}[d]

    # ------------------------------------------------------------- control SQL
    def tname(self, t):
        return self.order_tbl if t == 'order' else t

    def q(self, sql, **params):
        from sqlalchemy import text
        res = self.ctl.execute(text(sql), params)
        if res.returns_rows:
            cols = [k.lower() for k in res.keys()]
            return [dict(zip(cols, r)) for r in res.fetchall()]
        return res.rowcount

    def db_now(self):
        sql = {'postgresql': 'SELECT clock_timestamp()::timestamp AS t', 'mysql': 'SELECT NOW(6) AS t',
               'sqlserver': 'SELECT SYSDATETIME() AS t', 'oracle': 'SELECT SYSTIMESTAMP AS t FROM dual'}[self.a.dbms]
        v = self.q(sql)[0]['t']
        return v.replace(tzinfo=None) if isinstance(v, dt.datetime) else v

    def rows(self, table, where, **params):
        return self.q(f'SELECT * FROM {self.tname(table)} WHERE {where}', **params)

    def keyed(self, table, rows):
        return {tuple(r[k] for k in KEYS[table]): r for r in rows}

    def scope(self, t, inp, state=None):
        """Every row the input can read or write, keyed; history as a multiset."""
        w = inp['w_id']
        s = {}
        if t in (1, 2, 3, 5):
            d = inp['d_id']
            s['district'] = self.keyed('district', self.rows('district', 'd_w_id = :w AND d_id = :d', w=w, d=d))
            s['warehouse'] = self.keyed('warehouse', self.rows('warehouse', 'w_id = :w', w=w))
        if t in (1, 2, 3):
            s['customer'] = self.keyed('customer', self.rows('customer', 'c_w_id = :w AND c_d_id = :d AND c_id = :c',
                                                              w=w, d=inp['d_id'], c=inp['c_id']))
        if t == 1:
            d0 = (state or {}).get('d0')
            if d0 is None:
                d0 = list(s['district'].values())[0]['d_next_o_id']
            s['order'] = self.keyed('order', self.rows('order', 'o_w_id = :w AND o_d_id = :d AND o_id >= :o', w=w, d=inp['d_id'], o=d0))
            s['new_order'] = self.keyed('new_order', self.rows('new_order', 'no_w_id = :w AND no_d_id = :d AND no_o_id >= :o', w=w, d=inp['d_id'], o=d0))
            s['order_line'] = self.keyed('order_line', self.rows('order_line', 'ol_w_id = :w AND ol_d_id = :d AND ol_o_id >= :o', w=w, d=inp['d_id'], o=d0))
            ids = sorted({i for i, _ in inp['items']})
            s['stock'] = {}
            s['item'] = {}
            for i in ids:
                s['stock'].update(self.keyed('stock', self.rows('stock', 's_w_id = :w AND s_i_id = :i', w=w, i=i)))
                s['item'].update(self.keyed('item', self.rows('item', 'i_id = :i', i=i)))
            s['_d0'] = d0
        if t == 2:
            s['history'] = self.rows('history', 'h_c_w_id = :w AND h_c_d_id = :d AND h_c_id = :c',
                                     w=w, d=inp['d_id'], c=inp['c_id'])
        if t == 3:
            s['order'] = self.keyed('order', self.rows('order', 'o_w_id = :w AND o_d_id = :d AND o_c_id = :c',
                                                       w=w, d=inp['d_id'], c=inp['c_id']))
            if s['order']:
                last = max(k[2] for k in s['order'])
                s['order_line'] = self.keyed('order_line', self.rows('order_line', 'ol_w_id = :w AND ol_d_id = :d AND ol_o_id = :o',
                                                                     w=w, d=inp['d_id'], o=last))
        if t == 4:
            s['new_order'], s['order'], s['order_line'], s['customer'] = {}, {}, {}, {}
            s['_oldest'] = {}
            for d in range(1, self.cfg.DISTRICTS_PER_WAREHOUSE + 1):
                if state and d in state.get('oldest', {}):
                    o = state['oldest'][d]
                else:
                    m = self.q(f'SELECT MIN(no_o_id) AS o FROM new_order WHERE no_w_id = :w AND no_d_id = :d', w=w, d=d)[0]['o']
                    if m is None:
                        continue
                    o = int(m)
                s['_oldest'][d] = o
                s['new_order'].update(self.keyed('new_order', self.rows('new_order', 'no_w_id = :w AND no_d_id = :d AND no_o_id = :o', w=w, d=d, o=o)))
                orow = self.rows('order', 'o_w_id = :w AND o_d_id = :d AND o_id = :o', w=w, d=d, o=o)
                s['order'].update(self.keyed('order', orow))
                s['order_line'].update(self.keyed('order_line', self.rows('order_line', 'ol_w_id = :w AND ol_d_id = :d AND ol_o_id = :o', w=w, d=d, o=o)))
                for r in orow:
                    s['customer'].update(self.keyed('customer', self.rows('customer', 'c_w_id = :w AND c_d_id = :d AND c_id = :c', w=w, d=d, c=r['o_c_id'])))
        if t == 5:
            s['order'] = self.keyed('order', self.q(f'SELECT * FROM {self.order_tbl} WHERE o_w_id = :w AND o_d_id = :d AND o_id >= :lo',
                                                    w=w, d=inp['d_id'], lo=list(s['district'].values())[0]['d_next_o_id'] - 20))
        return s

    def counts(self):
        return {t: int(list(self.q(f'SELECT COUNT(*) AS n FROM {self.tname(t)}')[0].values())[0]) for t in TABLES}

    # ------------------------------------------------------------ difference
    def diff(self, before, after):
        out = {}
        for table in sorted(set(before) | set(after)):
            if table.startswith('_'):
                continue
            b, a = before.get(table, {}), after.get(table, {})
            if table == 'history':
                bl = [C.canonical_json(r) for r in b]
                al = [C.canonical_json(r) for r in a]
                added = list(al)
                for x in bl:
                    if x in added:
                        added.remove(x)
                removed = list(bl)
                for x in al:
                    if x in removed:
                        removed.remove(x)
                out[table] = {'inserted': [json.loads(x) for x in added], 'deleted': [json.loads(x) for x in removed]}
                continue
            ins = {k: a[k] for k in a if k not in b}
            dele = {k: b[k] for k in b if k not in a}
            upd = {}
            for k in a:
                if k in b and a[k] != b[k]:
                    upd[k] = {c: [b[k][c], a[k][c]] for c in a[k] if a[k][c] != b[k].get(c)}
            if ins or dele or upd:
                out[table] = {'inserted': list(ins.values()), 'deleted': list(dele.values()),
                              'updated': [{'key': list(k), 'changes': v} for k, v in upd.items()]}
        return out

    def strip_clock(self, delta, window):
        """Replace clock columns by a window check; everything else stays exact."""
        problems = []

        def ok(v):
            if not isinstance(v, dt.datetime):
                return False
            lo, hi = window
            return lo - dt.timedelta(seconds=CLOCK_TOLERANCE_S) <= v <= hi + dt.timedelta(seconds=CLOCK_TOLERANCE_S)
        out = json.loads(json.dumps(C.typed(delta)))
        for table, d in out.items():
            cols = CLOCK_COLUMNS.get(table, set())
            for kind in ('inserted', 'deleted'):
                for r in d.get(kind, []):
                    for c in cols:
                        if c in r and kind == 'inserted':
                            v = C.untyped(r[c])
                            if v is not None and not ok(v):
                                problems.append(f'{table}.{c} {v} outside call window')
                            r[c] = '<clock>' if v is not None else None
            for u in d.get('updated', []):
                for c in list(u['changes']):
                    if c in cols:
                        new = C.untyped(u['changes'][c][1])
                        if not ok(new):
                            problems.append(f'{table}.{c} {new} outside call window')
                        u['changes'][c] = [u['changes'][c][0], '<clock>']
            if table == 'history':
                for kind in ('inserted', 'deleted'):
                    d[kind] = sorted(d[kind], key=lambda r: json.dumps(r, sort_keys=True))
            else:
                for kind in ('inserted', 'deleted'):
                    d[kind] = sorted(d[kind], key=lambda r: json.dumps([r.get(k) for k in KEYS[table]], default=str))
                d['updated'] = sorted(d.get('updated', []), key=lambda u: json.dumps(u['key'], default=str))
        return out, problems

    # ---------------------------------------------------------------- revert
    def revert(self, t, inp, before, after, window):
        ops = []
        for table in [x for x in TABLES if x in before or x in after]:
            b, a = before.get(table, {}), after.get(table, {})
            tn = self.tname(table)
            if table == 'history':
                d = self.diff({'history': b}, {'history': a})['history']
                for r in d['inserted']:
                    r = C.untyped(r)
                    cond = ' AND '.join(f'{c} = :{c}' for c in r if c != 'h_date' and r[c] is not None)
                    params = {c: v for c, v in r.items() if c != 'h_date' and v is not None}
                    params['lo'] = window[0] - dt.timedelta(seconds=CLOCK_TOLERANCE_S + 1)
                    where = f'{cond} AND h_date >= :lo'
                    n = self.q(f'SELECT COUNT(*) AS n FROM history WHERE {where}', **params)[0]['n']
                    if int(n) != 1:
                        raise RuntimeError(f'history revert would match {n} rows')
                    sql = {'postgresql': f'DELETE FROM history WHERE ctid IN (SELECT ctid FROM history WHERE {where} LIMIT 1)',
                           'mysql': f'DELETE FROM history WHERE {where} LIMIT 1',
                           'sqlserver': f'DELETE TOP (1) FROM history WHERE {where}',
                           'oracle': f'DELETE FROM history WHERE ROWID IN (SELECT ROWID FROM history WHERE {where} AND ROWNUM = 1)'}[self.a.dbms]
                    ops.append(('history', 'delete', self.q(sql, **params)))
                if d['deleted']:
                    raise RuntimeError('a transaction deleted history rows; no revert rule')
                continue
            keys = KEYS[table]
            for k, row in a.items():
                if k not in b:
                    self.q(f'DELETE FROM {tn} WHERE ' + ' AND '.join(f'{c} = :{c}' for c in keys),
                           **{c: row[c] for c in keys})
                    ops.append((table, 'delete', list(k)))
            for k, row in b.items():
                if k not in a:
                    cols = list(row)
                    self.q(f'INSERT INTO {tn} ({", ".join(cols)}) VALUES ({", ".join(":" + c for c in cols)})', **row)
                    ops.append((table, 'insert', list(k)))
                elif a[k] != row:
                    changed = [c for c in row if row[c] != a[k].get(c)]
                    self.q(f'UPDATE {tn} SET ' + ', '.join(f'{c} = :{c}' for c in changed) + ' WHERE ' +
                           ' AND '.join(f'{c} = :k_{c}' for c in keys),
                           **{c: row[c] for c in changed}, **{f'k_{c}': row[c] for c in keys})
                    ops.append((table, 'update', list(k), changed))
        return ops

    # -------------------------------------------------------------- one call
    def call(self, t, path, seed, inp, ctx):
        dj, sa = self.mods
        trace = []

        def dj_wrap(execute, sql, prm, many, context):
            trace.append({'sql': sql, 'params': prm})
            return execute(sql, prm, many, context)
        state = {'d0': None}
        before = self.scope(t, inp)
        if t == 1:
            state['d0'] = before['_d0']
        if t == 4:
            state['oldest'] = dict(before['_oldest'])
        rec = {'campaign': 'rc20261008', 'protocol_id': self.protocol['protocol_id'], 'protocol_sha256': self.protocol_sha,
               'run_id': self.run_id, 'phase': self.a.phase, 'dbms': self.a.dbms, 'schema': self.a.schema,
               'transaction': TX[t][0], 'path': path, 'framework': path.split('/')[0], 'seed': seed,
               'predicted_input': inp, 'environment_id': self.env_id, 'source_sha256': self.source_sha, **ctx,
               'initial_state_sha256': C.digest(before), 'start': C.stamps()}
        c0, d0 = dt.datetime.now(), self.db_now()
        random.seed(seed)
        self.trace = trace if path.startswith('sqlalchemy') else None
        out = None
        t0 = time.perf_counter()
        try:
            with self.dconn.execute_wrapper(dj_wrap):
                if path == 'django/orm':
                    out = dj.run_transaction_orm(using='default')
                elif path == 'django/sql':
                    out = dj.run_transaction_sql(self.dconn)
                elif path == 'sqlalchemy/orm':
                    out = sa.run_transaction_orm(self.session)
                else:
                    out = sa.run_transaction_sql(self.session)
            elapsed = time.perf_counter() - t0
            rec['status'] = 'ok'
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            rec.update(status='error', error=f'{type(exc).__name__}: {exc}'[:2000], traceback=traceback.format_exc()[-3000:])
        finally:
            self.trace = None
        c1, d1 = dt.datetime.now(), self.db_now()
        post = {}
        for label, fn in (('sa_rollback', self.session.rollback),):
            try:
                fn()
                post[label] = 'ok'
            except Exception as exc:
                post[label] = repr(exc)
        if rec['status'] != 'ok':
            try:
                self.dconn.rollback()
            except Exception:
                pass
        rec['elapsed_s'] = elapsed
        rec['post_call'] = post
        rec['output'] = out
        rec['statements'] = trace
        rec['tables_touched'] = sorted({m.lower() for s in trace for m in TABLE_RE.findall(str(s['sql']))})
        window = (min(c0, d0), max(c1, d1))
        rec['window'] = {'client': [c0, c1], 'db': [d0, d1]}
        after = self.scope(t, inp, state)
        delta = self.diff(before, after)
        rec['delta'] = delta
        rec['delta_comparable'], rec['clock_problems'] = self.strip_clock(delta, window)
        # The transaction's keys come from inside the function; check them
        # against the replayed draw sequence.
        mism = {}
        if isinstance(out, dict):
            for k in ('w_id', 'd_id', 'c_id', 'carrier_id', 'threshold'):
                if k in out and k in inp and out[k] != inp[k]:
                    mism[k] = [inp[k], out[k]]
            if 'payment' in out and t == 2 and float(out['payment']) != round(inp['payment'], 12) and \
                    abs(float(out['payment']) - inp['payment']) > 1e-9:
                mism['payment'] = [inp['payment'], out['payment']]
        rec['input_match'] = not mism
        rec['input_mismatch'] = mism
        ops = self.revert(t, inp, before, after, window)
        check = self.scope(t, inp, state)
        rec['revert_ops'] = ops
        rec['revert_verified'] = C.digest({k: v for k, v in check.items() if not k.startswith('_')}) == \
            C.digest({k: v for k, v in before.items() if not k.startswith('_')})
        rec['end'] = C.stamps()
        return rec

    # ---------------------------------------------------------------- the cell
    def compare_pair(self, t, x, y):
        res = {'left': x['path'], 'right': y['path']}
        if x['status'] != 'ok' or y['status'] != 'ok':
            res.update(accepted=False, classification='execution_failed')
            return res
        problems = []
        if x['delta_comparable'] != y['delta_comparable']:
            problems.append('committed differences differ')
        for k in COMMON_OUTPUT[t]:
            xv, yv = (x['output'] or {}).get(k), (y['output'] or {}).get(k)
            if xv != yv and not (C.value_relation(xv, yv) != 'different'):
                problems.append(f'output {k}: {xv!r} vs {yv!r}')
        for r in (x, y):
            if not r['revert_verified']:
                problems.append(f"{r['path']} revert not verified")
            if not r['input_match']:
                problems.append(f"{r['path']} keys differ from the replayed draws")
            if r['clock_problems']:
                problems.append(f"{r['path']} clock: {r['clock_problems']}")
        res['tables_touched'] = {x['path']: x['tables_touched'], y['path']: y['tables_touched']}
        res['tables_touched_equal'] = set(x['tables_touched']) == set(y['tables_touched'])
        res['output_keys'] = {x['path']: sorted((x['output'] or {}).keys()), y['path']: sorted((y['output'] or {}).keys())}
        res.update(accepted=not problems, classification='equivalent' if not problems else 'mismatch', problems=problems)
        return res

    def seed_for(self, t, block):
        return int(hashlib.sha256(f"{self.protocol['protocol_id']}:T{t}:{block}".encode()).hexdigest()[:12], 16)

    def run_cell(self, t):
        a = self.a
        cdir = self.run_dir / TX[t][0]
        if (cdir / 'cell-done.json').exists():
            return
        self.mods = (importlib.import_module(f'django_app.tpcc_queries.{TX[t][2]}'),
                     importlib.import_module(f'sqlalchemy_app.tpcc_queries.{TX[t][3]}'))
        seed0, _ = C.block_plan(f"{self.protocol['protocol_id']}:{a.dbms}:{a.schema}:T{t}")
        rng = random.Random(seed0)
        plan = []
        for _ in range((a.blocks + 3) // 4):
            cyc = [0, 1, 2, 3]
            rng.shuffle(cyc)
            plan += cyc
        plan = plan[:a.blocks]
        if not (cdir / 'plan.json').exists():
            C.save(cdir / 'plan.json', {'seed': seed0, 'sequences': plan, 'input_seeds': [self.seed_for(t, b) for b in range(a.blocks + 1)]})
        counts0 = self.counts()
        if not (cdir / 'cellwarm' / 'done.json').exists():
            att = self._attempt(cdir / 'cellwarm')
            s = self.seed_for(t, 0)
            inp = predict(t, s, self.cfg)
            for pos, path in enumerate(C.WILLIAMS[seed0 % 4]):
                r = self.call(t, path, s, inp, {'kind': 'cell_warmup', 'block': 0, 'attempt': att, 'position': pos})
                self.save_rec(cdir / 'cellwarm' / f'a{att}' / f'{path.replace("/", "-")}.json.gz', r)
            C.save(cdir / 'cellwarm' / 'done.json', {'attempt': att, **C.stamps()}, immutable=True)
        for b in range(1, a.blocks + 1):
            bdir = cdir / f'b{b:02d}'
            if (bdir / 'decision.json').exists():
                continue
            seq = plan[b - 1]
            s = self.seed_for(t, b)
            inp = predict(t, s, self.cfg)
            att = self._attempt(bdir)
            cb = self.counts()
            warm, timed = {}, {}
            for path in C.PATHS:
                r = self.call(t, path, s, inp, {'kind': 'block_warmup', 'block': b, 'attempt': att, 'position': -1})
                self.save_rec(bdir / f'a{att}' / f'warm-{path.replace("/", "-")}.json.gz', r)
                warm[path] = r
            for pos, path in enumerate(C.WILLIAMS[seq]):
                r = self.call(t, path, s, inp, {'kind': 'timed', 'block': b, 'attempt': att, 'position': pos, 'sequence_id': seq})
                self.save_rec(bdir / f'a{att}' / f'timed-{path.replace("/", "-")}.json.gz', r)
                timed[path] = r
            ca = self.counts()
            dec = {'transaction': TX[t][0], 'block': b, 'attempt': att, 'seed': s, 'input': inp, 'sequence_id': seq,
                   'counts_before_block': cb, 'counts_after_block': ca, 'counts_unchanged': cb == ca == counts0,
                   'frameworks': {}, 'cross': {}, 'warmup_pairs': {}, **C.stamps()}
            for fw in ('django', 'sqlalchemy'):
                p = self.compare_pair(t, timed[f'{fw}/sql'], timed[f'{fw}/orm'])
                p['accepted'] = p['accepted'] and dec['counts_unchanged']
                dec['frameworks'][fw] = p
                dec['warmup_pairs'][fw] = self.compare_pair(t, warm[f'{fw}/sql'], warm[f'{fw}/orm'])['classification']
                self.bump('accepted_pairs' if p['accepted'] else 'rejected_pairs')
            dec['cross']['sql'] = self.compare_pair(t, timed['django/sql'], timed['sqlalchemy/sql'])
            dec['cross']['orm'] = self.compare_pair(t, timed['django/orm'], timed['sqlalchemy/orm'])
            C.save(bdir / 'decision.json', dec, immutable=True)
            self.event('block_decided', transaction=TX[t][0], block=b,
                       frameworks={k: v['classification'] for k, v in dec['frameworks'].items()},
                       counts_unchanged=dec['counts_unchanged'])
            self.save_progress(state='block_decided', current={'transaction': TX[t][0], 'block': b})
            if not dec['counts_unchanged']:
                raise SystemExit('table row counts moved; state restoration failed - stopping')
        C.save(cdir / 'cell-done.json', {'transaction': TX[t][0], **C.stamps()}, immutable=True)

    def _attempt(self, d):
        d.mkdir(parents=True, exist_ok=True)
        n = 1
        while (d / f'a{n}').exists():
            n += 1
        (d / f'a{n}').mkdir()
        return n

    def save_rec(self, path, rec):
        C.save(path, rec, immutable=True)
        self.bump(f"saved_{rec['kind']}")
        self.bump(f"status_{rec['kind']}_{rec['status']}")
        if not rec['revert_verified']:
            self.event('revert_failed', record=str(path))
            raise SystemExit('state revert could not be verified - stopping before the next call')

    # -------------------------------------------------------------- inventory
    def inventory(self, label):
        inv = {'label': label, 'run_id': self.run_id, **C.stamps(), 'host': socket.gethostname(),
               'platform': platform.platform(), 'python': sys.version, 'dbms': self.a.dbms, 'schema': self.a.schema,
               'sa_url': self.sa_url_public, 'tpcc_config': self.cfg.summary(), 'packages': {},
               'client_affinity': sorted(os.sched_getaffinity(0))}
        for pkg in ('Django', 'SQLAlchemy', 'psycopg2-binary', 'mysqlclient', 'oracledb', 'pyodbc', 'mssql-django'):
            try:
                inv['packages'][pkg] = importlib.metadata.version(pkg)
            except importlib.metadata.PackageNotFoundError:
                pass
        inv['counts'] = self.counts()
        with self.dconn.cursor() as c:
            self.cfg.verify_against(c)
        inv['index_verification'] = subprocess.run(
            [sys.executable, 'scripts/1-setup/manage_indexes.py', '--database', 'default', '--benchmark', 'tpcc',
             '--action', 'verify', '--expect', self.a.schema], capture_output=True, text=True).__dict__
        inv['index_verification'] = {k: inv['index_verification'][k] for k in ('returncode', 'stdout', 'stderr')}
        inv['host_verification'] = {k: v for k, v in subprocess.run(
            ['sudo', '-n', '/usr/local/sbin/bench-host', 'verify', self.a.dbms], capture_output=True, text=True,
            env={**os.environ, 'ORACLE_SID': 'free'}).__dict__.items() if k in ('returncode', 'stdout')}
        hashes = {}
        for folder in ('django_app/tpcc_queries', 'sqlalchemy_app/tpcc_queries'):
            for p in sorted((self.src / folder).glob('*.py')):
                hashes[str(p.relative_to(self.src))] = C.file_sha256(p)
        for name in ('django_app/tpcc_models.py', 'sqlalchemy_app/tpcc_models.py', 'tpcc_config.py'):
            hashes[name] = C.file_sha256(self.src / name)
        inv['source_hashes'] = hashes
        inv['code_hashes'] = {n: C.file_sha256(HERE / n) for n in ('rc_tpcc.py', 'rc_common.py')}
        return inv

    def main(self):
        self.lock()
        self.setup()
        inv = self.inventory('before')
        self.env_id = C.digest({k: inv[k] for k in ('host', 'platform', 'python', 'packages', 'dbms', 'schema',
                                                       'source_hashes', 'code_hashes', 'client_affinity')})
        self.source_sha = C.digest(inv['source_hashes'])
        inv['environment_id'] = self.env_id
        C.save(self.run_dir / f'inventory-before-{self.run_id}.json', inv, immutable=True)
        if inv['index_verification']['returncode'] != 0:
            raise SystemExit('TPC-C index state does not match --schema')
        if inv['host_verification']['returncode'] != 0 and self.a.dbms != 'oracle':
            raise SystemExit('bench-host verify failed')
        ps = self.protocol.get('tpcc_source_hashes')
        if ps and ps != inv['source_hashes']:
            raise SystemExit('TPC-C source differs from the protocol snapshot')
        old = self.run_dir / 'progress.json'
        if old.exists():
            self.progress['counts'] = C.load(old).get('counts', {})
        self.event('start', argv=sys.argv)
        for t in self.a.transactions:
            self.run_cell(t)
            self.event('cell_done', transaction=TX[t][0])
        after = self.inventory('after')
        after['environment_id'] = self.env_id
        C.save(self.run_dir / f'inventory-after-{self.run_id}.json', after, immutable=True)
        ok = after['counts'] == inv['counts'] and after['source_hashes'] == inv['source_hashes']
        if ok:
            C.save(self.run_dir / 'completion.json', {'run_id': self.run_id, 'counts_unchanged': True,
                                                      'counts': self.progress['counts'], **C.stamps()})
        self.save_progress(state='complete' if ok else 'end_checks_failed')
        self.ctl.close()
        if not ok:
            raise SystemExit('end checks failed')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign-dir', type=Path, required=True)
    ap.add_argument('--run-dir', type=Path, required=True)
    ap.add_argument('--protocol', type=Path, required=True)
    ap.add_argument('--phase', required=True)
    ap.add_argument('--dbms', required=True, choices=['postgresql', 'mysql', 'oracle', 'sqlserver'])
    ap.add_argument('--schema', required=True, choices=['indexed', 'non-indexed'])
    ap.add_argument('--transactions', type=int, nargs='+', default=[1, 2, 3, 4, 5])
    ap.add_argument('--blocks', type=int, default=24)
    ap.add_argument('--mode', choices=['main', 'pilot'], required=True)
    ap.add_argument('--client-cpus', default='2,3')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--src', type=Path)
    a = ap.parse_args()
    r = Tx(a)
    try:
        r.main()
    except SystemExit:
        raise
    except BaseException:
        C.save(a.run_dir / f'failure-{r.run_id}.json', {'error': traceback.format_exc(), **C.stamps()})
        raise


if __name__ == '__main__':
    main()
