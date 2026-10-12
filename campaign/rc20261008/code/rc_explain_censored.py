#!/usr/bin/env python3
"""Why a censored cell cannot finish: the plans of its recorded statements.

A censored cell is reported with a cause, not only with "exceeded 900 s".
For every path of a cell this records the optimizer's plan for exactly the
statement and parameters the timed-out call sent (read from the cell-warmup
records; the runner captures a statement before executing it). Plain EXPLAIN:
nothing is executed. PostgreSQL: EXPLAIN (FORMAT TEXT); MySQL: EXPLAIN
FORMAT=TREE. The plans show whether the hand-written SQL and the ORM share the
same nested full scans (a property of the schema without indexes) or differ
(a property of the ORM's SQL).

Run with the database in the index state of the cell (non-indexed for the
censored cells), so the plan is the one the timed call faced.

Usage (host, inside the engine visit, after SF1 is primary-key-only):
  source code/rc_env.sh mysql && cd $RC_CAMPAIGN && taskset -c 2,3 $RC_PY code/rc_explain_censored.py \\
      --run-dir A-sf1/mysql-non-indexed --queries 13 17 20 --out evidence/censored-plans/mysql-non-indexed.json
"""
import argparse
import datetime as dt
import decimal
import gzip
import json
import os
import sys
from pathlib import Path

PATHS = ('django/sql', 'django/orm', 'sqlalchemy/sql', 'sqlalchemy/orm')


sys.path.insert(0, str(Path(__file__).resolve().parent))
# The records' own decoder. This file decoded only date and Decimal, and the
# Q17 SQLAlchemy cell-warmup records of PostgreSQL and MySQL carry a float
# parameter: KeyError 'float', no output (found by audit, 2026-10-09 22:40,
# before the step ran on the host).
from rc_common import untyped as typed  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', type=Path, required=True)
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--stage', default='cellwarm', help='cellwarm (phase A) or validate (phase V)')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    from sqlalchemy import create_engine
    eng = create_engine(os.environ['SA_DSN'])
    dialect = eng.dialect.name
    prefix = {'postgresql': 'EXPLAIN (FORMAT TEXT) ', 'mysql': 'EXPLAIN FORMAT=TREE '}[dialect]
    raw = eng.raw_connection()
    out = {'run_dir': str(a.run_dir), 'stage': a.stage, 'dialect': dialect, 'method': prefix.strip() +
           ' on the statements recorded by the timed-out (or completed) cell-warmup calls; nothing executed',
           'cells': {}}
    try:
        for q in a.queries:
            att = sorted((a.run_dir / f'q{q:02d}' / a.stage).glob('a*'))[-1]
            for p in PATHS:
                f = att / (p.replace('/', '-') + '.json.gz')
                if not f.exists():
                    continue
                rec = json.load(gzip.open(f))
                plans = []
                for st in rec.get('statements', []):
                    cur = raw.cursor()
                    params = typed(st.get('params'))
                    cur.execute(prefix + st['sql'], params if params not in (None, [], {}) else None)
                    plans.append({'sql': st['sql'], 'plan': ['\t'.join(str(x) for x in row) for row in cur.fetchall()]})
                    cur.close()
                el = rec['elapsed_s']
                out['cells'].setdefault(f'q{q:02d}', {})[p] = {
                    'status': rec['status'], 'elapsed_s': float(el['value']) if isinstance(el, dict) else el,
                    'input_id': rec['input_id'], 'record': str(f), 'statements': plans}
                print(f'q{q:02d} {p:15s} {rec["status"]:8s} {len(plans)} plan(s)')
    finally:
        raw.rollback()
        raw.close()
    out['utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'x') as fh:
        fh.write(json.dumps(out, indent=1, default=str) + '\n')
    print(a.out)


if __name__ == '__main__':
    main()
