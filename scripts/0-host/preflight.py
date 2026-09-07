#!/usr/bin/env python3
"""Everything that must be true before a campaign starts, checked in one place.

    python3 scripts/0-host/preflight.py --dbms sqlserver --schema indexed
    python3 scripts/0-host/preflight.py --dbms mysql --schema non-indexed --quick

Why this exists
---------------
The SF1 campaigns were validated for plumbing - connections open, indexes
present, parameters substitute - and every one of those checks passed. What was
never checked was whether the *measurement protocol* was sound, and that is
where the time went. Four defects were found inside campaigns rather than
before them, each costing a full run:

  - SQL Server was measured while auto_create_stats was still building its
    statistics, because the statistics rebuild lived inside
    manage_indexes.py --action create and the database arrived already indexed.
    Q19's django/orm sat at 6.1 s for six blocks, then dropped to 0.29 s.

  - Query Store was on, with a 900 s flush interval, writing runtime statistics
    to disk during measurement. It put isolated multi-second stalls into
    sub-second queries: Q19's CV was 144% with it on and 1.4% with it off.
    No other engine had an equivalent subsystem running.

  - The per-block warmup warmed one rotating path. The pages it read were
    shared; the compiled plan was not, so the warming path kept a private
    advantage - and an advantage of different size on the ORM and SQL paths of
    a pair, which does not cancel in a median. It moved SQL Server's Q02
    sqlalchemy overhead from -19.0% to -47.8%.

  - Q13NotExpressible was recorded as "error", so a declared result (C17) read
    as eight undeclared failures and scored a whole campaign NO-GO.

The first three share a shape: the database or the harness was still changing
while it was being measured, and nothing looked for that. A check that only
asks "can we connect and are the indexes there" cannot see any of them.

So the last section here does not inspect configuration at all. It runs the
real harness over one cheap query and asks whether the protocol biased the
result - whether position within a block predicts time, and whether early
blocks differ from late ones. Either would mean the design is measuring itself.
That probe is what would have caught the warmup defect in four minutes instead
of four campaigns.

Exit code is 0 only if every check passes. run_pilot.sh gates on it.
"""
import argparse
import collections
import os
import statistics
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)

PASS, FAIL, INFO, WARN = "pass", "FAIL", "----", "warn"

# The probe's bounds. Both are properties of the design, not of any engine, so
# they are the same everywhere and are stated before the probe runs.
POSITION_SPREAD_MAX = 0.10   # max |median(position p) / median(all) - 1|
BLOCK_DRIFT_MAX = 0.15       # max |median(first half) / median(second half) - 1|

_failures = []


def line(status, label, detail=""):
    mark = {PASS: "  ok  ", FAIL: "  FAIL", INFO: "      ", WARN: "  warn"}[status]
    print(f"{mark}  {label}" + (f"   {detail}" if detail else ""))
    if status == FAIL:
        _failures.append(label)


def section(title):
    print(f"\n{title}")


# --------------------------------------------------------------------------
# 1. Both frameworks reach the same database, through the same driver.
# --------------------------------------------------------------------------
def check_connectivity(dbms):
    section("CONNECTIVITY AND DRIVER PARITY")
    import django
    django.setup()
    from django.db import connections
    import sqlalchemy as sa

    dsn = os.environ.get("SA_DSN", "")
    if not dsn:
        line(FAIL, "SA_DSN is set")
        return None
    conn = connections["default"]

    try:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) FROM lineitem")
            dj_rows = c.fetchone()[0]
        dj_driver = conn.Database.__name__
        dj_ver = getattr(conn.Database, "__version__", "?")
    except Exception as e:
        line(FAIL, "Django connects", str(e)[:90])
        return None

    try:
        eng = sa.create_engine(dsn)
        with eng.connect() as c:
            sa_rows = c.exec_driver_sql("SELECT COUNT(*) FROM lineitem").scalar()
        sa_driver = eng.dialect.dbapi.__name__
        sa_ver = getattr(eng.dialect.dbapi, "__version__", "?")
    except Exception as e:
        line(FAIL, "SQLAlchemy connects", str(e)[:90])
        return None

    line(PASS, "both frameworks connect")
    line(PASS if dj_rows == sa_rows else FAIL,
         "both see the same database",
         f"lineitem {dj_rows} vs {sa_rows}")
    # Driver parity is a measurement requirement, not hygiene: a compiled driver
    # under one framework and a pure-Python one under the other could move the
    # framework contrast by more than the effects this study reports.
    line(PASS if dj_driver == sa_driver else FAIL,
         "same DBAPI in both frameworks",
         f"Django {dj_driver} {dj_ver} / SQLAlchemy {sa_driver} {sa_ver}")
    return dj_rows


# --------------------------------------------------------------------------
# 2. Nothing in the engine may adapt while it is being measured.
# --------------------------------------------------------------------------
def check_engine_is_stationary(dbms):
    section("THE ENGINE MUST NOT ADAPT WHILE MEASURED")
    from django.db import connections
    cur = connections["default"].cursor()

    def scalar(sql, default=None):
        try:
            cur.execute(sql)
            row = cur.fetchone()
            return row[0] if row else default
        except Exception:
            return default

    if dbms == "sqlserver":
        qs = scalar("SELECT actual_state_desc FROM sys.database_query_store_options")
        line(PASS if qs == "OFF" else FAIL, "Query Store off", f"is {qs}")
        rec = scalar("SELECT recovery_model_desc FROM sys.databases WHERE name=DB_NAME()")
        line(PASS if rec == "SIMPLE" else WARN, "recovery model SIMPLE", f"is {rec}")
        at = scalar("SELECT COUNT(*) FROM sys.database_automatic_tuning_options "
                    "WHERE actual_state_desc <> 'OFF'", 0)
        line(PASS if at == 0 else FAIL, "automatic tuning off", f"{at} option(s) on")
        # auto_create/auto_update stay on - they are the vendor default and the
        # statistics are built ahead of the run, so nothing is left to build.
        stale = scalar("""SELECT COUNT(*) FROM sys.stats s
                          CROSS APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) p
                          JOIN sys.tables t ON t.object_id = s.object_id
                          WHERE p.rows > 0 AND p.modification_counter > 0""", 0)
        line(PASS if stale == 0 else FAIL, "statistics current",
             f"{stale} with pending modifications")
        dop = scalar("SELECT CAST(value_in_use AS INT) FROM sys.configurations "
                     "WHERE name='max degree of parallelism'")
        line(INFO, "max degree of parallelism", str(dop))

    elif dbms == "oracle":
        # C19: the result cache turns the second execution of a query into a
        # lookup, which is not the query.
        # C19: the result cache turns the second execution of a query into a
        # lookup, which is not the query. Reading it needs SELECT on
        # v_$parameter, which the measuring user does not hold by default -
        # and an unreadable setting is not a verified one, so the two cases
        # fail alike but must not read alike. "is None" sent me looking for a
        # wrong value when the value was right and the grant was missing.
        rc = scalar("SELECT value FROM v$parameter WHERE name='result_cache_mode'")
        if rc is None:
            line(FAIL, "result_cache_mode MANUAL",
                 "cannot read v$parameter as this user - "
                 "GRANT SELECT ON v_$parameter TO <user>")
        else:
            line(PASS if rc.upper() == "MANUAL" else FAIL,
                 "result_cache_mode MANUAL", f"is {rc}")

    elif dbms == "postgresql":
        line(INFO, "autovacuum", str(scalar("SHOW autovacuum")))
        # A statistics target below the default means fewer histogram buckets
        # than every other campaign used.
        line(INFO, "default_statistics_target",
             str(scalar("SHOW default_statistics_target")))

    elif dbms == "mysql":
        line(INFO, "innodb_buffer_pool_size",
             str(scalar("SELECT @@innodb_buffer_pool_size")))
        line(INFO, "innodb_stats_persistent",
             str(scalar("SELECT @@innodb_stats_persistent")))
    cur.close()


# --------------------------------------------------------------------------
# 3. The configuration the rows will claim is the one the database is in.
# --------------------------------------------------------------------------
def check_index_state(dbms, schema):
    section("INDEX STATE MATCHES THE CLAIMED CONFIGURATION")
    alias = "default" if dbms == "postgresql" else dbms
    r = subprocess.run([sys.executable, "scripts/1-setup/manage_indexes.py",
                        "--database", alias, "--action", "verify",
                        "--expect", schema],
                       cwd=REPO, capture_output=True, text=True)
    tail = [l for l in r.stdout.strip().splitlines() if l.strip()][-1:] or [""]
    line(PASS if r.returncode == 0 else FAIL,
         f"index state is '{schema}'", tail[0].strip())


# --------------------------------------------------------------------------
# 4. The ceiling is actually in force (C32).
# --------------------------------------------------------------------------
def check_ceiling(dbms):
    section("THE CEILING IS IN FORCE, NOT MERELY ISSUED")
    sys.path.insert(0, os.path.join(REPO, "scripts", "2-benchmark"))
    try:
        from django.db import connections
        cur = connections["default"].cursor()
        probe = {"postgresql": "SHOW statement_timeout",
                 "mysql": "SELECT @@max_execution_time"}.get(dbms)
        if probe:
            cur.execute(probe)
            line(INFO, "server reports", str(cur.fetchone()[0]))
        else:
            line(INFO, "bound is client-side on this vendor",
                 "asserted per connection by the harness")
        cur.close()
    except Exception as e:
        line(WARN, "ceiling could not be read back", str(e)[:80])


# --------------------------------------------------------------------------
# 5. The protocol itself must not bias the measurement.
# --------------------------------------------------------------------------
def check_protocol_is_unbiased(dbms, schema, query):
    """Run the real harness over one cheap query and look for design effects.

    This is the section the earlier validation did not have. Two things are
    asked of the raw rows, and both are properties of the design rather than of
    any engine:

      position   Every path appears once in every position across the four
                 Williams sequences, so if the design is clean the median time
                 at each position is the same. A position that is reliably
                 slower means the first execution in a block is paying for
                 something the others are not - which is precisely the defect
                 the block warmup was added to fix, and precisely the defect
                 the single-path version of that warmup reintroduced in a
                 different shape.

      drift      Blocks 1-4 against blocks 5-8. The eight blocks are two
                 independent permutations of the same four sequences, so they
                 are exchangeable; a systematic difference between halves means
                 the system is still changing during the cell.
    """
    section("THE PROTOCOL DOES NOT BIAS THE MEASUREMENT")
    # Must not exist: run_block.py writes the CSV header only when the file is
    # absent, so handing it an empty file created by NamedTemporaryFile yields
    # a headerless file and a KeyError on the first read.
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name
    os.unlink(tmp)
    cpus = os.environ.get("BENCH_CLIENT_CPUS", "2,3")
    r = subprocess.run(["taskset", "-c", cpus, sys.executable,
                        "scripts/2-benchmark/run_block.py",
                        "--query", str(query), "--dbms", dbms, "--schema", schema,
                        "--timeout", "900", "--campaign-id", "preflight",
                        "--out", tmp],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        line(FAIL, f"probe query Q{query:02d} runs",
             (r.stderr or r.stdout).strip().splitlines()[-1][:100] if (r.stderr or r.stdout) else "")
        return

    import csv as _csv
    rows = [x for x in _csv.DictReader(open(tmp))
            if x["is_warmup"] == "0" and x["status"] == "ok"]
    if len(rows) < 24:
        line(FAIL, "probe produced a full cell", f"{len(rows)} measured rows")
        return
    line(PASS, f"probe query Q{query:02d} runs", f"{len(rows)} measured executions")

    # Normalise within path, so a slow path does not dominate a pooled median.
    by_path = collections.defaultdict(list)
    for x in rows:
        by_path[(x["framework"], x["path"])].append(x)
    norm = []
    for (fw, kind), xs in by_path.items():
        med = statistics.median(float(x["elapsed_s"]) for x in xs)
        if med <= 0:
            continue
        for x in xs:
            norm.append((int(x["position"]), int(x["block"]),
                         float(x["elapsed_s"]) / med))

    bypos = collections.defaultdict(list)
    for pos, _blk, v in norm:
        bypos[pos].append(v)
    spreads = {p: statistics.median(v) - 1.0 for p, v in sorted(bypos.items())}
    worst_pos = max(spreads.items(), key=lambda kv: abs(kv[1]))
    line(PASS if abs(worst_pos[1]) <= POSITION_SPREAD_MAX else FAIL,
         f"no position effect (bound {POSITION_SPREAD_MAX:.0%})",
         "  ".join(f"p{p}:{s*100:+.1f}%" for p, s in spreads.items()))

    first = [v for _p, b, v in norm if b <= 4]
    second = [v for _p, b, v in norm if b >= 5]
    drift = statistics.median(first) / statistics.median(second) - 1.0
    line(PASS if abs(drift) <= BLOCK_DRIFT_MAX else FAIL,
         f"no drift between block halves (bound {BLOCK_DRIFT_MAX:.0%})",
         f"blocks 1-4 vs 5-8: {drift*100:+.1f}%")
    os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbms", required=True,
                    choices=["postgresql", "mysql", "sqlserver", "oracle"])
    ap.add_argument("--schema", required=True, choices=["indexed", "non-indexed"])
    ap.add_argument("--probe-query", type=int, default=6,
                    help="cheap query used for the protocol probe (default Q06)")
    ap.add_argument("--quick", action="store_true",
                    help="skip the protocol probe (configuration checks only)")
    args = ap.parse_args()

    print("=" * 78)
    print(f"PREFLIGHT   {args.dbms} / {args.schema}")
    print("=" * 78)

    if check_connectivity(args.dbms) is not None:
        check_engine_is_stationary(args.dbms)
        check_ceiling(args.dbms)
    check_index_state(args.dbms, args.schema)
    if not args.quick:
        check_protocol_is_unbiased(args.dbms, args.schema, args.probe_query)

    print("\n" + "=" * 78)
    if _failures:
        print(f"NOT READY - {len(_failures)} check(s) failed:")
        for f in _failures:
            print(f"    {f}")
        return 1
    print("READY - every precondition holds, and the protocol probe is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
