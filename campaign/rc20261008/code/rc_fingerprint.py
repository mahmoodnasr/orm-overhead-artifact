#!/usr/bin/env python3
"""Content identity of a loaded TPC-H dataset, comparable across engines.

Algorithm rc20261008-canonical-multiset-v2. Every row of every table is read
once, rendered canonically, hashed with SHA-256, and the hashes are summed
modulo 2**256 (an order-independent multiset hash), with the row count. The
rendering removes only representation differences between engines and
drivers, never content:

  * numbers (int, Decimal, float) -> plain decimal string of the exact value,
    trailing zeros removed (Decimal('5.00') and 5 both render '5');
  * strings -> trailing blanks removed (CHAR(n) padding on Commercial System A and
    PostgreSQL; Oracle stores VARCHAR2, see C7);
  * dates, and datetimes at midnight -> ISO date;
  * columns keyed by lower-case name, so column order does not matter.

Why v2. v1 hashed rows in primary-key order and paged by key. LINEITEM has no
primary key on PostgreSQL, MySQL or Commercial System A, so in the primary-key-only
configuration every page would scan the whole table; and a composite keyset
predicate made Commercial System A rescan from the start of each page. v2 needs neither
an order nor an index: one streaming scan per table through a server-side
cursor. v1 results already recorded (Commercial System A pilot, DuckDB source) stay as
evidence under v1.

The same rendering of the DuckDB file the loads were generated from gives the
source identity. Runs outside every timed interval; never while a campaign is
timing.
"""
import argparse
import datetime as dt
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import time

TABLES = ['region', 'nation', 'supplier', 'customer', 'part', 'partsupp', 'orders', 'lineitem']
TPCC_TABLES = ['warehouse', 'district', 'customer', 'history', 'item', 'stock', 'order', 'new_order', 'order_line']
ORDER_TABLE = {'postgresql': '"order"', 'mysql': '`order`', 'sqlserver': '[order]', 'oracle': '"ORDER"'}
PAGE = 20000
MOD = 1 << 256
ALGORITHM = 'rc20261008-canonical-multiset-v2'


def canon(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.rstrip(' ')
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        v = Decimal(repr(v))
    if isinstance(v, Decimal):
        s = format(v.normalize(), 'f')
        return '0' if s in ('-0', '0') else s
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time() and v.tzinfo is None else v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    raise TypeError(type(v).__name__)


def table_hash(cursor_factory, table):
    total, n, t0 = 0, 0, time.perf_counter()
    cur, names = cursor_factory(table)
    order = sorted(range(len(names)), key=lambda i: names[i])
    header = [names[i] for i in order]
    while True:
        rows = cur.fetchmany(PAGE)
        if not rows:
            break
        for r in rows:
            line = json.dumps([canon(r[i]) for i in order], ensure_ascii=False, separators=(',', ':')).encode()
            total = (total + int.from_bytes(hashlib.sha256(line).digest(), 'big')) % MOD
        n += len(rows)
    try:
        cur.close()
    except Exception:
        pass
    return {'rows': n, 'multiset_sha256_sum': format(total, '064x'), 'columns': header,
            'seconds': round(time.perf_counter() - t0, 2)}


def duckdb_factory(path):
    import duckdb
    con = duckdb.connect(str(path), read_only=True)

    def f(table):
        cur = con.cursor()          # a closable duplicate; closing con.execute()'s
        cur.execute(f'SELECT * FROM {table}')   # result would close the database
        return cur, [d[0].lower() for d in cur.description]
    return f


def django_factory(dbms):
    from django.db import connection
    connection.ensure_connection()
    raw = connection.connection
    if dbms == 'oracle':
        import oracledb
        oracledb.defaults.fetch_decimals = True
    if dbms == 'postgresql':
        # psycopg2 refuses a named (server-side) cursor in autocommit mode,
        # which is how Django leaves the connection. Read-only; rolled back.
        raw.autocommit = False

    def f(table):
        if dbms == 'postgresql':
            cur = raw.cursor(name=f'rcfp_{table}')
            cur.itersize = PAGE
        elif dbms == 'mysql':
            import MySQLdb.cursors
            cur = raw.cursor(MySQLdb.cursors.SSCursor)
        else:
            cur = raw.cursor()
            if dbms == 'oracle':
                cur.arraysize = PAGE
                cur.prefetchrows = PAGE
        name = ORDER_TABLE[dbms] if table == 'order' else table
        cur.execute(f'SELECT * FROM {name}')
        if dbms == 'postgresql' and cur.description is None:
            cur.fetchmany(0)
        return cur, [d[0].lower() for d in cur.description]
    return f


def tables_list(a):
    return TPCC_TABLES if a.benchmark == 'tpcc' else TABLES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--duckdb', type=Path)
    ap.add_argument('--dbms')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--label', default='')
    ap.add_argument('--benchmark', choices=['tpch', 'tpcc'], default='tpch')
    a = ap.parse_args()
    if a.out.exists():
        sys.exit(f'{a.out} exists; fingerprints are immutable')
    if a.duckdb:
        factory, source = duckdb_factory(a.duckdb), {'duckdb': str(a.duckdb)}
        try:
            import duckdb
            source['duckdb_version'] = duckdb.__version__
        except Exception:
            pass
    else:
        import django
        django.setup()
        from django.db import connection
        factory = django_factory(a.dbms)
        source = {'dbms': a.dbms, 'database': connection.settings_dict['NAME'], 'user': connection.settings_dict['USER']}
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    tables = {}
    for t in tables_list(a):
        tables[t] = table_hash(factory, t)
        print(t, tables[t]['rows'], tables[t]['multiset_sha256_sum'][:16], tables[t]['seconds'], flush=True)
    content = hashlib.sha256(json.dumps({t: [v['rows'], v['multiset_sha256_sum'], v['columns']] for t, v in tables.items()},
                                        sort_keys=True).encode()).hexdigest()
    out = {'label': a.label, 'benchmark': a.benchmark, 'source': source, 'started_utc': started,
           'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'algorithm': ALGORITHM,
           'tables': tables, 'content_sha256': content, 'pid': os.getpid(),
           'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1) + '\n')
    print('CONTENT', content)


if __name__ == '__main__':
    main()
