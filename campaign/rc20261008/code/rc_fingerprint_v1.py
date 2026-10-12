#!/usr/bin/env python3
"""Content identity of a loaded TPC-H dataset, comparable across engines.

Every row of every table is read in primary-key order and hashed after a
canonical rendering that removes only representation differences between
engines and drivers, never content:

  * numbers (int, Decimal, float) -> plain decimal string of the exact value,
    trailing zeros removed (Decimal('5.00') and 5 both render '5');
  * strings -> trailing blanks removed (CHAR(n) padding on Commercial System A and
    PostgreSQL; Oracle stores VARCHAR2, see C7);
  * dates, and datetimes at midnight -> ISO date;
  * columns keyed by lower-case name, so column order does not matter.

The same rendering of the DuckDB file the loads were generated from gives the
source identity, so equality proves each engine holds the generated data, not
merely the right row counts. Runs outside every timed interval; it is a
full-table read and is never run while a campaign is timing.
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

KEYS = {'region': ['r_regionkey'], 'nation': ['n_nationkey'], 'supplier': ['s_suppkey'],
        'customer': ['c_custkey'], 'part': ['p_partkey'], 'partsupp': ['ps_partkey', 'ps_suppkey'],
        'orders': ['o_orderkey'], 'lineitem': ['l_orderkey', 'l_linenumber']}
PAGE = 50000


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


def table_hash(fetch_pages, table):
    h = hashlib.sha256()
    n = 0
    cols = None
    t0 = time.perf_counter()
    for names, rows in fetch_pages(table):
        if cols is None:
            cols = names
            order = sorted(range(len(cols)), key=lambda i: cols[i])
            h.update(json.dumps([cols[i] for i in order]).encode() + b'\n')
        for r in rows:
            h.update(json.dumps([canon(r[i]) for i in order], ensure_ascii=False,
                                separators=(',', ':')).encode() + b'\n')
        n += len(rows)
    return {'rows': n, 'sha256': h.hexdigest(), 'columns': sorted(cols or []),
            'seconds': round(time.perf_counter() - t0, 2)}


def duckdb_pages(path):
    import duckdb
    con = duckdb.connect(str(path), read_only=True)

    def pages(table):
        cur = con.execute(f'SELECT * FROM {table} ORDER BY {", ".join(KEYS[table])}')
        names = [d[0].lower() for d in cur.description]
        while True:
            rows = cur.fetchmany(PAGE)
            if not rows:
                break
            yield names, rows
    return pages


def django_pages(dbms):
    """Pages by ranges of the leading key column, each read in full key order.

    A keyset predicate over a composite key ((k1 > ?) OR (k1 = ? AND k2 > ?))
    made Commercial System A rescan LINEITEM from its start on every page (measured:
    over 11 minutes and still running). A range on the leading column is a
    clustered-index seek on every engine and yields the same rows in the same
    order, so the hash is identical to the single ordered stream DuckDB gives.
    """
    from django.db import connection

    def pages(table):
        keys = KEYS[table]
        k1 = keys[0]
        with connection.cursor() as c:
            c.execute(f'SELECT MIN({k1}), MAX({k1}) FROM {table}')
            lo, hi = c.fetchone()
        if lo is None:
            return
        lo, hi = int(lo), int(hi)
        step = max(1, PAGE // (4 if len(keys) > 1 else 1))
        start = lo - 1
        last = None
        while start < hi:
            end = start + step
            with connection.cursor() as c:
                c.execute(f'SELECT * FROM {table} WHERE {k1} > %s AND {k1} <= %s ORDER BY {", ".join(keys)}',
                          [start, end])
                names = [d[0].lower() for d in c.description]
                rows = c.fetchall()
            start = end
            if not rows:
                continue
            idx = [names.index(k) for k in keys]
            first = tuple(rows[0][i] for i in idx)
            assert last is None or first > last, 'primary key not strictly increasing across pages'
            last = tuple(rows[-1][i] for i in idx)
            yield names, rows
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--duckdb', type=Path)
    ap.add_argument('--dbms')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--label', default='')
    a = ap.parse_args()
    if a.duckdb:
        pages, source = duckdb_pages(a.duckdb), {'duckdb': str(a.duckdb)}
    else:
        import django
        django.setup()
        from django.db import connection
        pages = django_pages(a.dbms)
        source = {'dbms': a.dbms, 'database': connection.settings_dict['NAME']}
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    tables = {}
    for t in KEYS:
        tables[t] = table_hash(pages, t)
        print(t, tables[t]['rows'], tables[t]['sha256'][:16], tables[t]['seconds'], flush=True)
    content = hashlib.sha256(json.dumps({t: [v['rows'], v['sha256']] for t, v in tables.items()},
                                        sort_keys=True).encode()).hexdigest()
    out = {'label': a.label, 'source': source, 'started_utc': started,
           'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
           'algorithm': 'rc20261008-canonical-v1: sha256 over canonical rows in primary-key order',
           'tables': tables, 'content_sha256': content, 'pid': os.getpid(),
           'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.out.exists():
        sys.exit(f'{a.out} exists; fingerprints are immutable')
    a.out.write_text(json.dumps(out, indent=1) + '\n')
    print('CONTENT', content)


if __name__ == '__main__':
    main()
