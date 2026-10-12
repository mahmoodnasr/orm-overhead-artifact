#!/usr/bin/env python3
"""PostgreSQL SF2: give tpch_sf2 the database-level settings of tpch, then
prove the two databases run with the same settings.

rc_sf2_setup.py creates tpch_sf2 with CREATE DATABASE from template1 and
copies the table DDL only. A setting attached to the database tpch (ALTER
DATABASE tpch SET ..., or ALTER ROLE ... IN DATABASE tpch SET ...) would not
follow it, and phase D would then compare SF2 with SF1 under different
settings without anything failing: the gate checks only
max_parallel_workers_per_gather, and the inventory records values, not their
source. (Audit of plan visits3, 2026-10-09 22:40, before any PostgreSQL SF2
step ran. MySQL copies SHOW CREATE DATABASE and Commercial System A its database
options; Oracle's SF2 user has no per-database settings.)

1. Every pg_db_role_setting entry of tpch is applied to tpch_sf2 with the same
   role scope (ALTER DATABASE / ALTER ROLE ... IN DATABASE). Recorded.
2. Encoding, collation and ctype of the two databases must be equal (they
   cannot be changed after CREATE DATABASE).
3. The eight settings the runner records (rc_analytical inventory), plus
   their source, are read in a fresh session of each database as the
   benchmark user and must be equal.
Exit 1 on any difference, before any SF2 measurement; the record is written
either way.

Usage (host, PostgreSQL visit, after postgresql-sf2-load):
  source code/rc_env.sh postgresql && cd $RC_CAMPAIGN && $RC_PY code/rc_pg_sf2_settings.py \\
      --target tpch_sf2 --out evidence/sf2-setup/postgresql-sf2-settings.json
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

NAMES = ('shared_buffers', 'work_mem', 'effective_cache_size', 'max_parallel_workers_per_gather',
         'max_parallel_workers', 'jit', 'random_page_cost', 'server_version')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', default='tpch_sf2')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    from sqlalchemy import create_engine, text
    src_dsn = os.environ['SA_DSN']
    if not src_dsn.endswith('/tpch'):
        raise SystemExit(f'SA_DSN does not name the SF1 database tpch: ...{src_dsn[-12:]}')
    dst_dsn = src_dsn[:-len('/tpch')] + '/' + a.target
    rec = {'source_db': 'tpch', 'target_db': a.target, 'applied': [], 'utc': dt.datetime.now(dt.timezone.utc).isoformat()}
    src = create_engine(src_dsn, isolation_level='AUTOCOMMIT')
    with src.connect() as c:
        dbs = {r[0]: {'encoding': r[1], 'collate': r[2], 'ctype': r[3]} for r in c.execute(text(
            "SELECT datname, pg_encoding_to_char(encoding), datcollate, datctype FROM pg_database "
            "WHERE datname IN ('tpch', :t)"), {'t': a.target})}
        rec['databases'] = dbs
        rows = c.execute(text(
            "SELECT COALESCE(r.rolname, '') AS role, s.setconfig FROM pg_db_role_setting s "
            "JOIN pg_database d ON d.oid = s.setdatabase LEFT JOIN pg_roles r ON r.oid = s.setrole "
            "WHERE d.datname = 'tpch'")).fetchall()
        rec['tpch_db_role_settings'] = [{'role': r[0], 'setconfig': list(r[1] or [])} for r in rows]
        for role, cfg in ((r[0], r[1] or []) for r in rows):
            for item in cfg:
                k, v = item.split('=', 1)
                scope = f'ALTER ROLE "{role}" IN DATABASE {a.target}' if role else f'ALTER DATABASE {a.target}'
                c.execute(text(f"{scope} SET {k} = '{v}'"))
                rec['applied'].append(f'{scope} SET {k} = {v!r}')

    def settings(dsn):
        e = create_engine(dsn)
        with e.connect() as c:
            out = {r[0]: {'setting': r[1], 'unit': r[2], 'source': r[3]} for r in c.execute(text(
                'SELECT name, setting, unit, source FROM pg_settings WHERE name = ANY(:n)'), {'n': list(NAMES)})}
        e.dispose()
        return out
    rec['settings'] = {'tpch': settings(src_dsn), a.target: settings(dst_dsn)}
    problems = []
    if a.target not in dbs:
        problems.append(f'{a.target} does not exist')
    elif dbs['tpch'] != dbs[a.target]:
        problems.append(f"encoding/collation differ: {dbs['tpch']} vs {dbs[a.target]}")
    for n in NAMES:
        x, y = rec['settings']['tpch'].get(n), rec['settings'][a.target].get(n)
        if (x or {}).get('setting') != (y or {}).get('setting'):
            problems.append(f'{n}: tpch {x} vs {a.target} {y}')
    rec['problems'] = problems
    rec['equal'] = not problems
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'x') as fh:
        fh.write(json.dumps(rec, indent=1, default=str) + '\n')
    print(json.dumps({'applied': rec['applied'], 'equal': rec['equal'], 'problems': problems}))
    sys.exit(0 if not problems else 1)


if __name__ == '__main__':
    main()
