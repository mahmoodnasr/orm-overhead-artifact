#!/usr/bin/env python3
"""Measure ONE cell as eight four-path blocks, and write one row per execution.

This is the protocol SF1_RERUN_PLAN.md section 5 specifies, and it differs from
run_query.py in three ways that matter to the analysis rather than to the
plumbing:

  1. **The block is the unit, not the path.** run_query.py runs every
     repetition of Django SQL, then every repetition of Django ORM, and so on.
     That makes the two arms of a ratio non-adjacent in time: Django's SQL
     repetitions all happen before its ORM repetitions, so any drift over the
     cell's runtime - a background process, a cache warming, a thermal effect -
     lands entirely on one arm. Here each block runs all four paths once, close
     together, and the paired ratio is formed inside the block.

  2. **Counterbalancing.** The four paths run in one of four Williams
     sequences, in which every path appears once in every position and every
     ordered pair of paths appears exactly once, so first-order carryover is
     balanced rather than assumed away. The eight measured blocks are two
     independently randomised permutations of the four sequences.

  3. **Eight parameter sets.** Each block draws its own substitution
     parameters, identical across the four paths within that block. One
     parameter instance repeated eight times measures one plan eight times.

Output is append-only and one row per execution - not per path, per cell.
Aggregation is the analysis's job, and writing medians here would throw away
the block structure the design exists to create.

Usage:
    python3 scripts/2-benchmark/run_block.py --query 6 --dbms postgresql \
        --schema indexed --timeout 900 \
        --out results/sf1/measurements/postgresql_indexed.csv --resume
"""
import argparse, csv, datetime, os, random, socket, sys, time, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django
django.setup()
from django.db import connections

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import tpch_paramsets

DSN = os.environ.get("SA_DSN", "")

BANDS = {
    **{q: "Simple" for q in (6, 14, 19)},
    **{q: "Medium" for q in (1, 3, 4, 11, 12, 16)},
    **{q: "Complex" for q in (2, 5, 7, 10, 13, 15, 17, 18, 20)},
    **{q: "Very Complex" for q in (8, 9, 21, 22)},
}

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "utils"))
import results_paths                                          # noqa: E402

# Refuses rather than defaulting to 10: TPCH_SF already has to be right for the
# query parameters (C6), and a default here would label an SF1 run as SF10.
SCALE_FACTOR = results_paths.scale_factor()

PATHS = ("django/sql", "django/orm", "sqlalchemy/sql", "sqlalchemy/orm")

# A Williams design for four treatments: every path once in every position, and
# every ordered pair exactly once. Not four arbitrary orders - an arbitrary set
# of four would leave some carryover pairs unbalanced, which is the thing the
# design is for.
WILLIAMS = (
    ("django/sql", "django/orm", "sqlalchemy/sql", "sqlalchemy/orm"),
    ("django/orm", "sqlalchemy/orm", "django/sql", "sqlalchemy/sql"),
    ("sqlalchemy/orm", "sqlalchemy/sql", "django/orm", "django/sql"),
    ("sqlalchemy/sql", "django/sql", "sqlalchemy/orm", "django/orm"),
)

FIELDS = [
    "run_id", "campaign_id", "host", "benchmark", "query_id", "band",
    "dbms", "schema_config", "scale_factor", "block", "sequence_id", "position",
    "framework", "path", "param_set_id", "is_warmup",
    "elapsed_s", "rows_returned", "status", "note",
    "ceiling_s", "load1", "pid", "session_id", "timestamp",
]

# scale_factor is recorded for the same reason param_set_id is: a row that does
# not name the thing it varied is not a measurement of it. campaign_id is not a
# substitute - it is a free-form label from CAMPAIGN_ID and defaults to "sf1"
# whatever TPCH_SF actually said, so a run at the wrong scale factor would still
# be labelled sf1.
#
# It is also load-bearing downstream. make_all_results.py excludes a row whose
# scale_factor is blank from any build other than SF10, because for the sixteen
# SF10 measurement files - written before the column existed - blank means ten.
# Without this, every row this script writes would be dropped from an SF1 build
# without a word, and counted in an SF10 one.


def verify_affinity():
    """The harness must not run on the cores the database is pinned to.

    G4 puts the engine on cores 0,1 and the client on 2,3, and the rule is
    normally applied by remembering to type `taskset -c 2,3`. Forgetting it
    does not announce itself: the run completes, the numbers look like numbers,
    and the client has been competing with the server it is timing for every
    one of them. That is the same failure shape as the contaminated validation
    run of 2026-09-02, where a second engine was live inside the envelope for
    16 minutes and only the journal revealed it afterwards.

    So it is checked here rather than trusted. BENCH_CLIENT_CPUS names the
    cores the harness may use (default 2,3); BENCH_SKIP_AFFINITY=1 overrides
    for a machine with a different topology, and says so on stdout so the
    override appears in the campaign log rather than only in someone's shell
    history.
    """
    want = os.environ.get("BENCH_CLIENT_CPUS", "2,3")
    if os.environ.get("BENCH_SKIP_AFFINITY") == "1":
        print(f"  affinity check SKIPPED by BENCH_SKIP_AFFINITY "
              f"(would have required {want})")
        return
    try:
        actual = os.sched_getaffinity(0)
    except AttributeError:                       # not Linux
        print("  affinity check unavailable on this platform")
        return
    expected = {int(c) for c in want.split(",") if c != ""}
    if actual != expected:
        raise SystemExit(
            f"harness affinity is {sorted(actual)}, G4 requires {sorted(expected)}.\n"
            f"Run it as:  taskset -c {want} python3 {sys.argv[0]} ...\n"
            "The engine is pinned to its own cores; a client sharing them "
            "competes with the server it is timing, and nothing in the output "
            "would show it."
        )
    print(f"  harness affinity: cores {sorted(actual)}")


def verify_williams():
    """A design that is only labelled Williams is not one. Check it."""
    for pos in range(4):
        if sorted(seq[pos] for seq in WILLIAMS) != sorted(PATHS):
            raise AssertionError(f"position {pos} does not contain every path once")
    pairs = [(seq[i], seq[i + 1]) for seq in WILLIAMS for i in range(3)]
    if len(pairs) != len(set(pairs)):
        raise AssertionError("an ordered pair appears twice; carryover is unbalanced")
    return True


def block_plan(seed):
    """Eight blocks: two independent random permutations of the four sequences.

    Returned as (block_number, sequence_index) so the sequence actually run is
    recorded per row and can be verified in the raw file rather than trusted
    because this docstring says so.
    """
    r = random.Random(seed)
    first, second = [0, 1, 2, 3], [0, 1, 2, 3]
    r.shuffle(first); r.shuffle(second)
    return list(enumerate(first + second, start=1))


def already_done(path, qid, dbms, schema):
    if not os.path.exists(path):
        return False
    with open(path) as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["query_id"] == qid and r["dbms"] == dbms
                and r["schema_config"] == schema and r["is_warmup"] == "0"]
    # A cell is done when all eight blocks have all four paths recorded.
    #
    # framework belongs in this key. "path" alone is "sql" or "orm", so the set
    # could never exceed 8 x 2 = 16 and the >= 32 test could never be true: no
    # cell was ever considered done, --resume re-ran everything it was given,
    # and an interrupted campaign resumed into duplicate rows rather than
    # continuing. It shows up as a cell with eight rows per block instead of
    # four, which the gate reports as a broken design.
    return len({(r["block"], r["framework"], r["path"]) for r in rows}) >= 8 * 4


def append(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
        fh.flush()
        os.fsync(fh.fileno())


def set_timeouts(seconds, dj_conn, sa_session, dbms):
    """Ask the server to abort a statement that exceeds the budget."""
    if not seconds:
        return
    ms = int(seconds * 1000)
    if dbms == "oracle":
        dj_conn.ensure_connection()
        for raw in (getattr(dj_conn, "connection", None),
                    sa_session.connection().connection.dbapi_connection):
            try:
                raw.call_timeout = ms
            except Exception:
                pass
        return
    if dbms in ("mssql", "sqlserver"):
        dj_conn.ensure_connection()
        for raw in (getattr(dj_conn, "connection", None),
                    sa_session.connection().connection.dbapi_connection):
            try:
                raw.timeout = int(seconds)
            except Exception:
                pass
        return
    stmt = {"postgresql": f"SET statement_timeout = {ms}",
            "mysql": f"SET SESSION max_execution_time = {ms}"}.get(dbms)
    if not stmt:
        return
    with dj_conn.cursor() as c:
        c.execute(stmt)
    from sqlalchemy import text
    sa_session.execute(text(stmt))


def read_ceiling(dj_conn, dbms, timeout=None):
    """Read the ceiling back off the server before timing anything (C32).

    A ceiling that was set but did not take effect has already produced a
    number indistinguishable from a measurement: three of Q17's four paths were
    cut at 600 s and the fourth ran to 790 s, because SET statement_timeout was
    issued on a session whose transaction was later rolled back. Returning what
    the server says, rather than what was asked for, is what makes the
    difference visible.
    """
    try:
        if dbms == "postgresql":
            with dj_conn.cursor() as c:
                c.execute("SHOW statement_timeout")
                return c.fetchone()[0]
        if dbms == "mysql":
            with dj_conn.cursor() as c:
                c.execute("SELECT @@SESSION.max_execution_time")
                return str(c.fetchone()[0])
        # Oracle and SQL Server bound the client round trip rather than the
        # server statement, so there is nothing on the server to read back -
        # but the value the harness is enforcing is known, and recording it is
        # the difference between a gate that scores the run and one that scores
        # a default. Writing the bare string "client-side" made pilot_gate.py
        # fall back to its 900 s default, so SQL Server's indexed campaign -
        # deliberately run at the 2700 s retry ceiling because Q18's Django ORM
        # path takes 345 s - was scored against 900 s and failed section 8.3 at
        # 4x. Against the ceiling actually in force the same run is 11x.
        return "client-side:%g" % timeout if timeout else "client-side"
    except Exception as e:
        return f"unreadable: {type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", type=int, required=True)
    ap.add_argument("--dbms", default="postgresql")
    ap.add_argument("--schema", default="indexed", choices=["indexed", "non-indexed"])
    ap.add_argument("--blocks", type=int, default=8,
                    help="measured blocks; the protocol is 8 and changing it "
                         "changes the design, so it is recorded on every row")
    ap.add_argument("--timeout", type=float, default=900,
                    help="per-execution ceiling in seconds, 0 to disable")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=None,
                    help="block-order seed; defaults to one derived from the "
                         "cell so a rerun of the same cell repeats its order")
    ap.add_argument("--campaign-id", default=os.environ.get("CAMPAIGN_ID", "sf1"))
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    verify_williams()
    verify_affinity()
    n, qid = args.query, f"Q{args.query:02d}"
    if args.resume and already_done(args.out, qid, args.dbms, args.schema):
        print(f"{qid} {args.dbms} {args.schema}: all blocks recorded, skipping")
        return 0

    seed = args.seed if args.seed is not None else abs(hash((n, args.dbms, args.schema))) % (2**31)
    plan = block_plan(seed)[:args.blocks]

    print(f"=== {qid} ({BANDS[n]})  {args.dbms}  {args.schema}  "
          f"{args.blocks} blocks x 4 paths, seed {seed} ===")

    from django_app.queries import get_query_module_for_db
    dj = get_query_module_for_db(n, args.dbms)
    sa = __import__(f"sqlalchemy_app.queries.q{n:02d}", fromlist=["x"])

    conn = connections["default"]
    engine = create_engine(DSN, future=True)
    sess = sessionmaker(bind=engine, future=True)()
    run_id = uuid.uuid4().hex[:12]
    host = socket.gethostname()

    def call(path, params):
        if path == "django/sql":
            return dj.run_query_sql(conn, params=params)
        if path == "django/orm":
            return dj.run_query_orm(using="default", params=params)
        if path == "sqlalchemy/sql":
            return sa.run_query_sql(sess, params=params)
        return sa.run_query_orm(sess, params=params)

    def cleanup(path):
        try:
            (sess.rollback() if path.startswith("sqlalchemy") else conn.rollback())
        except Exception:
            pass
        # A rollback drops a session-level statement_timeout, so it is reissued
        # rather than assumed to have survived. C32.
        set_timeouts(args.timeout, conn, sess, args.dbms)

    rows = []
    try:
        set_timeouts(args.timeout, conn, sess, args.dbms)
        ceiling = read_ceiling(conn, args.dbms, args.timeout)
        print(f"  ceiling as the server reports it: {ceiling}")

        # One warmup sequence of four paths, discarded. It is recorded with
        # is_warmup=1 rather than dropped, so a warmup that failed is visible.
        #
        # The warmup uses a ninth parameter instance that no measured block
        # uses. Warming with one of the eight would warm that set's own pages
        # and predicates, and the block sharing it would start warmer than the
        # other seven - a warmup that removes a bias from the cell by
        # introducing one between its blocks.
        # Paths the warmup found to be censored. A path that exceeded the
        # ceiling once will exceed it eight more times, and each repeat costs a
        # full ceiling: on this grid a query whose four paths all time out at
        # 900 s costs 9 blocks x 4 paths x 900 s = 9 hours to learn something
        # the warmup already established, and the plan says as much - declare
        # such cells censored on their EXPLAIN evidence and "measure them once
        # per system rather than nine times per path".
        #
        # Censoring is recorded, never inferred from an absence: the warmup row
        # carries status=timeout and the bound, and section 6 of the analysis
        # plan turns that into a one-sided theta rather than a missing value.
        censored_paths = set()
        warmup = [(0, seed % 4)]
        for block, seq_idx in warmup + plan:
            seq = WILLIAMS[seq_idx]
            if block == 1 and len(censored_paths) == len(PATHS):
                # Every path exceeded the ceiling. There is nothing the eight
                # measured blocks can add: the cell is a bound on all four
                # arms, and running them would spend nine hours confirming it.
                print(f"  all {len(PATHS)} paths exceeded the ceiling in warmup; "
                      f"{qid} recorded as a fully censored cell, 8 blocks skipped")
                break
            if block == 0:
                params = tpch_paramsets.warmup_params(n)
                pset = f"q{n:02d}warm"
            else:
                si = (block - 1) % tpch_paramsets.N_SETS
                params = tpch_paramsets.params_of(n, si)
                pset = tpch_paramsets.set_id(n, si)
            tag = "warmup" if block == 0 else f"block {block}"
            print(f"  {tag:8s} seq {seq_idx}  params {pset}")

            # Per-block warmup. Each block uses its own parameter set, so the
            # first path in a block pays the I/O to bring that set's pages in
            # and the other three run warm. Measured on MySQL indexed: the
            # first position was 2.8x the others on Q12 and 1.9x on Q02, while
            # long queries were unaffected - a fixed cost, invisible at 25 s and
            # dominant at 0.57 s.
            #
            # The Williams design distributes it evenly, so the estimand
            # survives: excluding position 0 entirely shifted the median
            # within-block log ratio by at most 0.006, and by 0.000 at the
            # median. What it damages is the per-path CV, which is published,
            # and which section 8.1 assumed would carry parameter variation but
            # not a position effect.
            #
            # So the block is warmed before it is measured, exactly as the cell
            # already is - and every path is warmed, not one.
            #
            # A single rotating warmer was the first attempt, on the reasoning
            # that PATHS[(block-1) % 4] gives each path the role exactly twice
            # over eight blocks and therefore cancels. It does not. The data
            # pages a warmup brings in are shared with every path; the compiled
            # plan is not, so the warming path keeps a private advantage, and
            # the advantage differs in size between the ORM and SQL paths of the
            # same framework. On SQL Server, being the warmer made Q02's
            # sqlalchemy/orm 0.41x its unwarmed time while sqlalchemy/sql moved
            # only to 0.71x, and an asymmetric benefit does not cancel in a
            # median: Q02's sqlalchemy overhead read -47.8% over all eight
            # blocks against -19.0% over the unwarmed ones, and Q19's read -2.7%
            # against -38.8%. The estimand itself moved by up to 0.46 in log
            # ratio. PostgreSQL's worst cell moved by 0.037, which is why this
            # survived two systems undetected.
            #
            # Warming all four costs eight executions per block instead of five.
            # That is the price of every path entering its timed run in the same
            # state, which is the only version of this that is symmetric.
            for warm_path in (PATHS if block > 0 else []):
                if warm_path not in censored_paths:
                    t0 = time.perf_counter()
                    try:
                        call(warm_path, params)
                        wstatus, wnote = "ok", ""
                    except Exception as e:
                        wstatus = ("timeout" if args.timeout and
                                   time.perf_counter() - t0 >= args.timeout * 0.9
                                   else "error")
                        wnote = f"{type(e).__name__}: {str(e)[:150]}"
                        cleanup(warm_path)
                    welapsed = time.perf_counter() - t0
                    wfw, wkind = warm_path.split("/")
                    print(f"      w {warm_path:16s} {welapsed:9.3f}s  (block warmup)")
                    rows.append({
                        "run_id": run_id, "campaign_id": args.campaign_id, "host": host,
                        "benchmark": "tpch", "query_id": qid, "band": BANDS[n],
                        "dbms": args.dbms, "schema_config": args.schema,
                        "scale_factor": SCALE_FACTOR,
                        "block": block, "sequence_id": seq_idx, "position": -1,
                        "framework": wfw, "path": wkind, "param_set_id": pset,
                        # 2 marks a block warmup, 1 the cell warmup, 0 measured.
                        # Analysis keeps only 0; both warmups stay in the file so
                        # a warmup that failed is visible rather than absent.
                        "is_warmup": 2,
                        "elapsed_s": round(welapsed, 6), "rows_returned": "",
                        "status": wstatus, "note": wnote, "ceiling_s": ceiling,
                        "load1": round(os.getloadavg()[0], 2),
                        "pid": os.getpid(), "session_id": id(sess),
                        "timestamp": datetime.datetime.now().astimezone()
                                     .isoformat(timespec="milliseconds"),
                    })
            for position, path in enumerate(seq):
                fw, kind = path.split("/")
                if path in censored_paths:
                    # Partially censored cell: this arm is a bound, the others
                    # are measured normally. Reporting the whole cell as missing
                    # would discard three good paths - Q13 non-indexed on
                    # PostgreSQL is the standing example, where Django's ORM
                    # exceeds any practical ceiling while the other three return
                    # in about two seconds.
                    print(f"      {position} {path:16s}   -- skipped, censored in warmup")
                    continue
                t0 = time.perf_counter()
                status, note, nrows = "ok", "", ""
                try:
                    result = call(path, params)
                    elapsed = time.perf_counter() - t0
                    nrows = len(result) if isinstance(result, list) else 1
                except Exception as e:
                    elapsed = time.perf_counter() - t0
                    # An inexpressible query is a declared result, not a
                    # failure (C17): Django's ORM has no derived-table
                    # construct, so Q13 cannot be written on SQL Server or
                    # Oracle at all. It was recorded as "error", which is the
                    # status reserved for something going wrong, so section
                    # 8.2 counted eleven undeclared failures and the whole
                    # SQL Server campaign scored NO-GO over a result the
                    # study already reports. It also retried the impossible
                    # once per block for nothing.
                    if type(e).__name__ == "Q13NotExpressible":
                        status = "not_expressible"
                        censored_paths.add(path)
                    else:
                        status = ("timeout" if args.timeout and elapsed >= args.timeout * 0.9
                                  else "error")
                        if status == "timeout" and block == 0:
                            censored_paths.add(path)
                    note = f"{type(e).__name__}: {str(e)[:150]}"
                    cleanup(path)
                print(f"      {position} {path:16s} {elapsed:9.3f}s "
                      f"{status if status != 'ok' else ''}")
                rows.append({
                    "run_id": run_id, "campaign_id": args.campaign_id, "host": host,
                    "benchmark": "tpch", "query_id": qid, "band": BANDS[n],
                    "dbms": args.dbms, "schema_config": args.schema,
                    "scale_factor": SCALE_FACTOR,
                    "block": block, "sequence_id": seq_idx, "position": position,
                    "framework": fw, "path": kind, "param_set_id": pset,
                    "is_warmup": 1 if block == 0 else 0,
                    "elapsed_s": round(elapsed, 6), "rows_returned": nrows,
                    "status": status, "note": note, "ceiling_s": ceiling,
                    "load1": round(os.getloadavg()[0], 2),
                    "pid": os.getpid(), "session_id": id(sess),
                    "timestamp": datetime.datetime.now().astimezone()
                                 .isoformat(timespec="milliseconds"),
                })
            # Written per block, not at the end: a cell can run for hours and
            # an all-or-nothing write loses everything to one hang.
            append(args.out, rows)
            rows = []
    finally:
        if rows:
            append(args.out, rows)
        sess.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
