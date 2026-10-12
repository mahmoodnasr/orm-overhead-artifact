#!/usr/bin/env python3
"""Optimizer plans for one measured Oracle cell, from the statements it timed.

Why: phase G Oracle Q20 indexed disagreed with the host (05-mac-speed-
justification.md). Per input, the hand-written SQL paths, which inline literal
values, took ~1.9 s on four of eight inputs on the Mac and ~0.26 s on the other
four (host: one slow input of eight), while both ORM paths, which send bind
variables, were flat. That pattern points at a per-literal plan choice. This
script records the plan Oracle chooses for each recorded statement, so the
claim rests on plans and not on timing shape alone.

EXPLAIN only: nothing is executed or timed. The statements are read from the
timed records of block 1..8 (one input each), never retyped. Bound statements
are explained with their bind markers, so Oracle does not peek the values;
that is stated in the output. Column statistics for the predicates' tables are
recorded alongside (histograms decide literal-dependent plans).

Usage (Mac, setup mode):
  source code/rc_g_env.sh oracle && $RC_PY code/rc_explain_g.py \
      --run-dir G-mac-server/v2/oracle-indexed --query 20 --out evidence/G-plans/oracle-indexed-q20-mac.json
Host (controller shell step, SF1 indexed, nothing timing):
  source code/rc_env.sh oracle tpch && cd $RC_CAMPAIGN && taskset -c 2,3 $RC_PY code/rc_explain_g.py \
      --run-dir A-sf1/oracle-indexed --query 20 --out evidence/G-plans/oracle-indexed-q20-host.json
"""
import argparse
import datetime as dt
import decimal
import gzip
import json
import os
import re
import sys
from pathlib import Path

PATHS = ('django/sql', 'django/orm', 'sqlalchemy/sql', 'sqlalchemy/orm')
TABLES = ('SUPPLIER', 'NATION', 'PARTSUPP', 'PART', 'LINEITEM')


def oracle_binds(sql, params):
    # Django records its Oracle statements with %s and positional values;
    # Oracle wants :name. The driver requires a value for every marker even
    # under EXPLAIN PLAN, which still does not peek it.
    def val(v):
        if isinstance(v, dict) and set(v) == {'type', 'value'}:
            return {'date': dt.date.fromisoformat, 'Decimal': decimal.Decimal}[v['type']](v['value'])
        return v
    if isinstance(params, list):
        n = iter(range(1000))
        sql = re.sub(r'%s', lambda _: f':b{next(n)}', sql)
        params = {f'b{i}': v for i, v in enumerate(params)}
    return sql, {k: val(v) for k, v in (params or {}).items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', type=Path, required=True)
    ap.add_argument('--query', type=int, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    from sqlalchemy import create_engine, text
    eng = create_engine(os.environ['SA_DSN'])
    qd = a.run_dir / f'q{a.query:02d}'
    plans = []
    with eng.connect() as c:
        banner = c.execute(text("SELECT banner_full FROM v$version")).scalar()
        for b in range(1, 9):
            dec = json.loads((qd / f'b{b}' / 'decision.json').read_text())
            for p in PATHS:
                rec = json.load(gzip.open(qd / f'b{b}' / dec['timed_records'][p]))
                st0 = rec['statements'][0]
                sql, binds = oracle_binds(st0['sql'].strip().rstrip(';'), st0.get('params'))
                bound = bool(binds)
                sid = f'rc{b}{p.replace("/", "")}'[:30]
                c.execute(text("DELETE FROM plan_table WHERE statement_id = :s"), {'s': sid})
                c.exec_driver_sql(f"EXPLAIN PLAN SET STATEMENT_ID = '{sid}' FOR {sql}", binds)
                out = [r[0] for r in c.execute(text(
                    "SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', :s, 'TYPICAL'))"), {'s': sid})]
                phv = next((int(m.group(1)) for l in out for m in [re.search(r'Plan hash value: (\d+)', l)] if m), None)
                plans.append({'block': b, 'input_id': rec['input_id'], 'parameters': rec.get('parameters'), 'path': p,
                              'timed_elapsed_s': float(rec['elapsed_s']['value']), 'bind_variables': bound,
                              'plan_hash_value': phv, 'plan': out})
                c.execute(text("DELETE FROM plan_table WHERE statement_id = :s"), {'s': sid})
        cols = [dict(r._mapping) for r in c.execute(text(
            "SELECT table_name, column_name, num_distinct, histogram, num_buckets, "
            "TO_CHAR(last_analyzed, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS last_analyzed "
            "FROM user_tab_col_statistics WHERE table_name IN ('SUPPLIER','NATION','PARTSUPP','PART','LINEITEM') "
            "ORDER BY table_name, column_name"))]
        tabs = [dict(r._mapping) for r in c.execute(text(
            "SELECT table_name, num_rows, blocks, TO_CHAR(last_analyzed, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS last_analyzed "
            "FROM user_tables WHERE table_name IN ('SUPPLIER','NATION','PARTSUPP','PART','LINEITEM') ORDER BY table_name"))]
        c.rollback()
    summary = {}
    for x in plans:
        summary.setdefault(x['path'], {}).setdefault(str(x['plan_hash_value']), []).append(
            {'input_id': x['input_id'], 'timed_elapsed_s': round(x['timed_elapsed_s'], 3)})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    rec = {'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'run_dir': str(a.run_dir), 'query': a.query,
           'server': banner, 'method': 'EXPLAIN PLAN + DBMS_XPLAN.DISPLAY(TYPICAL) on the statements recorded in the '
           'timed records; bound statements explained without bind peeking', 'plans_by_hash': summary,
           'plans': plans, 'table_stats': tabs, 'column_stats': cols}
    with open(a.out, 'x') as f:
        f.write(json.dumps(rec, indent=1, default=str) + '\n')
    print(a.out)
    for p, hs in summary.items():
        print(p, {h: [f"{v['input_id']}:{v['timed_elapsed_s']}" for v in vs] for h, vs in hs.items()})


if __name__ == '__main__':
    sys.exit(main())
