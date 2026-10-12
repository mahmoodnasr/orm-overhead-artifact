#!/usr/bin/env python3
"""Refresh optimizer statistics on the TPC-C tables, with reserved names quoted.

scripts/1-setup/manage_indexes.py --benchmark tpcc --action analyze quotes the
table name only on PostgreSQL. On Commercial System A it runs
`UPDATE STATISTICS <schema>.order`, and on MySQL `ANALYZE TABLE order`. ORDER is a
reserved word, so both fail ("Incorrect syntax near the keyword 'order'",
phase C, Commercial System A, 2026-10-09 14:23). The script belongs to the frozen
source snapshot (hashed by protocols A-v1 and its derivatives), so it is not
edited. This step does what its update_statistics() does - the same tables
from TPCC_INDEXES, the same statement per engine, FULLSCAN on Commercial System A,
DBMS_STATS on Oracle - with every table name passed through the script's own
quote_table(). It runs with the rc_env.sh tpcc environment, from the source
worktree, exactly like the script.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'scripts' / '1-setup'))
import django  # noqa: E402

django.setup()
from django.db import connections  # noqa: E402
import manage_indexes as MI  # noqa: E402


def main():
    conn = connections['default']
    vendor = MI.get_db_vendor(conn)
    tables = list(MI.TPCC_INDEXES.keys())
    with conn.cursor() as c:
        for t in tables:
            q = MI.quote_table(t, vendor)
            if vendor == 'postgresql':
                c.execute(f'ANALYZE {q}')
            elif vendor == 'mysql':
                # MySQL reports a failed ANALYZE as a result row (Msg_type
                # 'error'), not as an exception; read the rows and stop on one
                c.execute(f'ANALYZE TABLE {q}')
                rows = c.fetchall()
                print(f'    {rows}')
                if not rows or any(str(r[2]).lower() == 'error' for r in rows):
                    raise SystemExit(f'ANALYZE TABLE {q} did not succeed: {rows}')
            elif vendor == 'sqlserver':
                c.execute(f'UPDATE STATISTICS dbo.{q} WITH FULLSCAN')
            elif vendor == 'oracle':
                c.callproc('DBMS_STATS.GATHER_TABLE_STATS', [conn.settings_dict['USER'].upper(), t.upper()])
            print(f'  statistics refreshed: {t} ({q})')
    conn.commit() if not conn.get_autocommit() else None
    print(f'TPC-C statistics refreshed on {len(tables)} tables ({vendor})')


if __name__ == '__main__':
    main()
