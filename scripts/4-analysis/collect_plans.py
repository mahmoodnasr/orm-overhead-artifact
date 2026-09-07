#!/usr/bin/env python3
"""MOEF Phase 2: collect execution plans and compute per-operator q-error.

For every query this captures the SQL each of the four paths actually sends,
runs EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) on it, and walks the resulting plan
tree recording estimated against actual cardinality for each operator.

This is the evidence MOEF's mechanism argument rests on. Without it the causal
chains in the discussion are inference from timings; with it they are traceable
to the operator that went wrong.

Outputs, under --outdir:
    execution_plans/<schema>/<query>_<framework>_<path>.json   full plan + SQL
    qerror/qerror_by_operator.csv                              one row per operator
    qerror/qerror_by_query.csv                                 aggregated per config

Usage:
    python3 collect_plans.py --schema non-indexed --timeout 300
    python3 collect_plans.py --schema non-indexed --queries 1,6,13,17
"""
import argparse, csv, json, os, sys, time

# Derived from this file's own location, so the script runs from a clone at any
# path. The default was /home/claude/bench/results_sf10, the sandbox the campaign
# happened to run in, which exists on no reviewer's machine.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_OUTDIR = os.path.join(_REPO, "results", "corrected")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django
django.setup()
from django.db import connections

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

DSN = os.environ.get("SA_DSN", "postgresql+psycopg2://postgres:bench@127.0.0.1:55432/tpch")

BANDS = {
    **{q: "Simple" for q in (6, 14, 19)},
    **{q: "Medium" for q in (1, 3, 4, 11, 12, 16)},
    **{q: "Complex" for q in (2, 5, 7, 10, 13, 15, 17, 18, 20)},
    **{q: "Very Complex" for q in (8, 9, 21, 22)},
}

_emitted = []


class _Captured(Exception):
    """Raised from the cursor hook once the statement text is known.

    Capturing the SQL does not require running the query, and running it is
    actively harmful here: on the pathological configurations the capture run
    takes longer than the EXPLAIN that follows, and it has no timeout because it
    is not the measurement. Aborting at the hook gets the statement for free.
    """


def qerror(est, act):
    """max(est/act, act/est). Undefined when either side is zero."""
    if est is None or act is None or est <= 0 or act <= 0:
        return None
    return max(est / act, act / est)


def walk(node, out, depth=0, parent=None):
    """Depth-first walk of a PostgreSQL plan tree, one record per operator."""
    est = node.get("Plan Rows")
    loops = node.get("Actual Loops", 1) or 1
    act = node.get("Actual Rows")
    if act is not None:
        act = act * loops           # Actual Rows is per-loop
    qe = qerror(est, act)
    out.append({
        "depth": depth,
        "operator": node.get("Node Type"),
        "parent_operator": parent,
        "relation": node.get("Relation Name", ""),
        "index_name": node.get("Index Name", ""),
        "join_type": node.get("Join Type", ""),
        "estimated_rows": est,
        "actual_rows": act,
        "actual_loops": loops,
        "q_error": round(qe, 4) if qe is not None else "",
        "underestimate": ("" if qe is None else (est < act)),
        "actual_total_time_ms": node.get("Actual Total Time"),
        "shared_hit_blocks": node.get("Shared Hit Blocks"),
        "shared_read_blocks": node.get("Shared Read Blocks"),
    })
    for child in node.get("Plans", []) or []:
        walk(child, out, depth + 1, node.get("Node Type"))


def capture_django_sql(n, dbms, conn):
    """The statement Django's raw-SQL path sends."""
    import inspect, re
    dj = __import__(f"django_app.queries.q{n:02d}", fromlist=["x"])
    src = inspect.getsource(dj.run_query_sql)
    # the modules build the statement inline; re-run the builder against a
    # capturing cursor rather than trying to parse it out of the source
    captured = {}
    real_execute = conn.cursor

    class Cap:
        def __init__(self, inner): self.inner = inner
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            captured["sql"] = sql
            raise _Stop()
        def __getattr__(self, k): return getattr(self.inner, k)

    class _Stop(Exception):
        pass

    conn.cursor = lambda: Cap(real_execute())
    try:
        dj.run_query_sql(conn)
    except _Stop:
        pass
    except Exception:
        pass
    finally:
        conn.cursor = real_execute
    return captured.get("sql")


def capture_django_orm_sql(n, conn):
    """The statement Django's ORM path sends, captured without running it."""
    dj = __import__(f"django_app.queries.q{n:02d}", fromlist=["x"])
    captured, real = {}, conn.cursor

    class _Stop(Exception):
        pass

    class Cap:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            try:
                out = self.inner.mogrify(sql, params) if params else sql
                captured["sql"] = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
            except Exception:
                captured["sql"] = sql
            raise _Stop()

        def __getattr__(self, k):
            return getattr(self.inner, k)

    conn.cursor = lambda: Cap(real())
    try:
        dj.run_query_orm(using="default")
    except Exception:
        pass
    finally:
        conn.cursor = real
        try:
            conn.rollback()
        except Exception:
            pass
    return captured.get("sql")


def explain(cur, sql, label):
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
    return cur.fetchone()[0][0]["Plan"], cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", required=True, choices=["indexed", "non-indexed"])
    ap.add_argument("--queries", default="")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR)
    args = ap.parse_args()

    nums = ([int(x) for x in args.queries.split(",")] if args.queries
            else list(range(1, 23)))

    plandir = os.path.join(args.outdir, "execution_plans", args.schema)
    qdir = os.path.join(args.outdir, "qerror")
    os.makedirs(plandir, exist_ok=True)
    os.makedirs(qdir, exist_ok=True)

    engine = create_engine(DSN, future=True)

    @event.listens_for(engine, "before_cursor_execute")
    def _cap(conn, cursor, statement, params, context, executemany):
        # The ORM emits parameterised SQL. EXPLAIN cannot take placeholders, so
        # render the literal statement with the driver's own quoting rather than
        # interpolating by hand.
        try:
            rendered = cursor.mogrify(statement, params)
            if isinstance(rendered, bytes):
                rendered = rendered.decode("utf-8", "replace")
        except Exception:
            rendered = statement
        _emitted.append(rendered)
        raise _Captured()

    Session = sessionmaker(bind=engine, future=True)
    conn = connections["default"]

    ops_rows, agg_rows = [], []

    for n in nums:
        qid = f"Q{n:02d}"
        sa = __import__(f"sqlalchemy_app.queries.q{n:02d}", fromlist=["x"])
        sess = Session()
        statements = {}

        # --- capture the SQL each path emits -----------------------------
        try:
            for label, fn in (("orm", sa.run_query_orm), ("sql", sa.run_query_sql)):
                _emitted.clear()
                try:
                    fn(sess)
                except Exception:
                    pass
                finally:
                    try:
                        sess.rollback()
                    except Exception:
                        pass
                if _emitted:
                    statements[("sqlalchemy", label)] = _emitted[0]
        finally:
            sess.close()

        try:
            dj = __import__(f"django_app.queries.q{n:02d}", fromlist=["x"])
            qs = dj.run_query_orm.__wrapped__ if hasattr(dj.run_query_orm, "__wrapped__") else None
        except Exception:
            pass
        s = capture_django_sql(n, "postgresql", conn)
        if s:
            statements[("django", "sql")] = s

        s2 = capture_django_orm_sql(n, conn)
        if s2:
            statements[("django", "orm")] = s2

        # --- EXPLAIN each captured statement ------------------------------
        for (fw, path), sql in sorted(statements.items()):
            tag = f"{qid}_{fw}_{path}"
            t0 = time.perf_counter()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SET statement_timeout = {int(args.timeout*1000)}")
                    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
                    plan = cur.fetchone()[0][0]["Plan"]
                status, note = "ok", ""
            except Exception as e:
                conn.rollback()
                plan, status = None, ("timeout" if time.perf_counter()-t0 >= args.timeout*0.9
                                      else "error")
                note = f"{type(e).__name__}: {str(e)[:100]}"
                print(f"  {tag:34s} {status}  {note[:60]}")

            json.dump({"query_id": qid, "schema": args.schema, "framework": fw,
                       "path": path, "status": status, "note": note,
                       "sql": sql, "plan": plan},
                      open(os.path.join(plandir, tag + ".json"), "w"), indent=1)

            if plan is None:
                agg_rows.append({"schema_config": args.schema, "query_id": qid,
                                 "complexity_band": BANDS[n], "framework": fw,
                                 "access_path": path, "status": status,
                                 "operators": 0, "mean_qerror": "", "median_qerror": "",
                                 "max_qerror": "", "operators_qerror_gt_2": "",
                                 "operators_qerror_gt_10": "", "underestimate_rate_pct": ""})
                continue

            ops = []
            walk(plan, ops)
            qs_ = [o["q_error"] for o in ops if o["q_error"] != ""]
            for o in ops:
                o.update({"schema_config": args.schema, "query_id": qid,
                          "complexity_band": BANDS[n], "framework": fw,
                          "access_path": path})
                ops_rows.append(o)
            import statistics as st
            unders = [o["underestimate"] for o in ops if o["underestimate"] != ""]
            agg_rows.append({
                "schema_config": args.schema, "query_id": qid,
                "complexity_band": BANDS[n], "framework": fw, "access_path": path,
                "status": "ok", "operators": len(ops),
                "mean_qerror": round(st.mean(qs_), 3) if qs_ else "",
                "median_qerror": round(st.median(qs_), 3) if qs_ else "",
                "max_qerror": round(max(qs_), 3) if qs_ else "",
                "operators_qerror_gt_2": sum(1 for q in qs_ if q > 2),
                "operators_qerror_gt_10": sum(1 for q in qs_ if q > 10),
                "underestimate_rate_pct": (round(100*sum(unders)/len(unders), 1)
                                           if unders else ""),
            })
            print(f"  {tag:34s} ok  {len(ops):>3d} operators  "
                  f"median q-error {agg_rows[-1]['median_qerror']}  "
                  f"max {agg_rows[-1]['max_qerror']}")

    # ------------------------------------------------------------- write out
    if ops_rows:
        keys = ["schema_config", "query_id", "complexity_band", "framework",
                "access_path", "depth", "operator", "parent_operator", "relation",
                "index_name", "join_type", "estimated_rows", "actual_rows",
                "actual_loops", "q_error", "underestimate", "actual_total_time_ms",
                "shared_hit_blocks", "shared_read_blocks"]
        p = os.path.join(qdir, "qerror_by_operator.csv")
        new = not os.path.exists(p)
        with open(p, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(ops_rows)
        print(f"\nwrote {len(ops_rows)} operator rows -> {p}")

    if agg_rows:
        p = os.path.join(qdir, "qerror_by_query.csv")
        new = not os.path.exists(p)
        with open(p, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(agg_rows[0].keys()))
            if new:
                w.writeheader()
            w.writerows(agg_rows)
        print(f"wrote {len(agg_rows)} config rows -> {p}")
    print(f"plans -> {plandir}")


if __name__ == "__main__":
    main()
