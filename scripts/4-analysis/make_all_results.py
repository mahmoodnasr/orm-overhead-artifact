#!/usr/bin/env python3
"""Build the one complete results file: results/all_results.csv.

The grid is fixed and always fully emitted:

    4 DBMS x 2 frameworks x 2 schema configurations x 27 queries = 432 rows
    (22 TPC-H queries + 5 TPC-C transactions)

which is the same shape as the original all_results.csv. Every cell is present.
A cell that has been measured carries its timings; a cell that has not carries
`sql_status = not_run` and a `status_note` naming what is blocking it. Absence is
never silent.

Differences from the original file, all deliberate:

  * `direct_sql_execution_s` is a measured median of the framework's own
    hand-written baseline, not a mean copied across repetitions.
  * The five synthesised component columns are gone. The original filled them
    from constants and fixed fractions of the residual whenever the profiler
    disagreed by more than 15%, which was the normal path, so
    `object_materialization_s` was the arithmetic remainder rather than a
    measurement. A measured two-way split asserts less and is true.
  * `q_error` is populated from real EXPLAIN ANALYZE output, per operator,
    summarised here and given in full in qerror/qerror_by_operator.csv.

Usage:
    python3 make_all_results.py                       # repo defaults
    python3 make_all_results.py --measurements DIR --out FILE
"""
import argparse, csv, datetime, math, os, re, statistics, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

sys.path.insert(0, os.path.join(REPO, "scripts", "utils"))
import results_paths                                          # noqa: E402

# --------------------------------------------------------------- the grid

# Versions are what was actually run, read off the running system or the venv,
# not remembered. Until 2026-08-29 this table said PostgreSQL 14.9, MySQL 8.0.34,
# Django 4.2.30 and SQLAlchemy 2.0.36; the campaign log prints
# "PostgreSQL 14.23 (Debian 14.23-1.pgdg13+1)", docs/ENVIRONMENT.md read 8.0.46
# off the MySQL container, and requirements.txt pins Django==4.2.0 and
# SQLAlchemy==2.0.23, which is what venv/ contains. Defect C22.
DBMS = [
    # key,        label,         version
    ("postgresql", "PostgreSQL", "14.23"),
    ("mysql",      "MySQL",      "8.0.46"),
    ("sqlserver",  "SQL Server", "2019 Developer (15.0.4480.2, CU32-GDR)"),
    # Read off the running server on 2026-08-30, not inferred from the image
    # tag: `select banner_full from v$version` returns "Oracle AI Database 26ai
    # Free Release 23.26.2.0.0". docs/ENVIRONMENT.md recorded "23ai Free", which
    # is what the tag `gvenzl/oracle-free:23-slim` suggests and not what the
    # software calls itself - the same C22 failure of reading metadata off a
    # label rather than a system. The image is dated 2026-05-30 and the July
    # campaign ran at the end of that month, so July almost certainly ran this
    # same build; that is inference, not evidence, because no Oracle log of that
    # campaign records a version string at all.
    ("oracle",     "Oracle",     "26ai Free 23.26.2.0.0"),
]
ORMS = [
    ("django",     "DJANGO",     "4.2.0"),
    ("sqlalchemy", "SQLALCHEMY", "2.0.23"),
]

# MySQL's non-indexed campaign has no surviving log, so its exact server build
# was never recorded. The column says that rather than asserting the version the
# other MySQL campaign reports: the image tag was `mysql:8.0` in both cases, but
# a tag is not a version, and reading a version off a tag is what recorded Oracle
# a whole major release out of date.
DBMS_VERSION = {
    ("mysql", "non-indexed"): "8.0.x - build not recorded for this campaign",
}

# Cells re-measured in the B1a campaign of 2026-08-30, after the databases were
# reloaded. The container image is `postgres:14`, which resolved to 14.23 in
# July and to 14.24 now, so these cells differ in minor version from the twenty
# other PostgreSQL queries measured beside them. It is recorded per cell rather
# than smoothed away: the ORM-versus-SQL ratio in each of these rows is taken
# from one run on one server and is unaffected, but a comparison of their
# absolute seconds against another PostgreSQL query's crosses a campaign and a
# patch release.
DBMS_VERSION_QUERY = {
    ("postgresql", "indexed", "Q13"): "14.24",
    ("postgresql", "indexed", "Q18"): "14.24",
    ("postgresql", "non-indexed", "Q18"): "14.24",
    ("postgresql", "indexed", "Q16"): "14.24",
    ("postgresql", "non-indexed", "Q16"): "14.24",
    # SQL Server's Q16 was re-measured in the same B1a campaign. Its version
    # string is unchanged - the container is pinned to 2019-latest and reported
    # the same 15.0.4480.2 CU32-GDR build as July - so only the campaign differs.
    ("sqlserver", "indexed", "Q16"): "2019 Developer (15.0.4480.2, CU32-GDR)",
    ("sqlserver", "non-indexed", "Q16"): "2019 Developer (15.0.4480.2, CU32-GDR)",
    # MySQL's container reports 8.0.46, the version already recorded for the
    # indexed campaign. The non-indexed cell is the one that moves: the rest of
    # that campaign ran on the retired sandbox whose versions were never logged
    # (see DBMS_VERSION), and this one query no longer did.
    ("mysql", "indexed", "Q16"): "8.0.46",
    ("mysql", "non-indexed", "Q16"): "8.0.46",
}
B1A_CAMPAIGN = "sf10-2026-08-b1a-localhost"
UNLOGGED_ORM_QUALIFIER = " (requirements.txt pin; venv not logged for this campaign)"

# The version tables above are what the SF10 campaign ran: PostgreSQL 14.23,
# Django 4.2.0, and so on. They are correct for that campaign and wrong for any
# other, so a build at a different scale factor says so in words rather than
# repeating them. Filling these from the running server is the remaining half of
# C22 - "results metadata from the record, not constants" - and it has to happen
# before an SF1 results file is cited. A stated gap is recoverable; a plausible
# wrong version is not.
NOT_YET_RECORDED = "not recorded - read off the running server at campaign time (C22)"

# Loaded size per system, from docs/ENVIRONMENT.md. A single "14" stood here for
# all four; the four figures are not like-for-like (two include secondary
# indexes, two do not) and are left that way rather than tidied into a false
# comparison.
DATASET_GB = {
    "postgresql": "21 (with indexes)",
    "mysql":      "~22 (with indexes, estimated)",
    "sqlserver":  "14.4 (without indexes)",
    "oracle":     "10.81 (without indexes)",
}
SCHEMAS = [("indexed", "Indexed"), ("non-indexed", "Non-Indexed")]

BANDS = {
    **{f"Q{q:02d}": "Simple" for q in (6, 14, 19)},
    **{f"Q{q:02d}": "Medium" for q in (1, 3, 4, 11, 12, 16)},
    **{f"Q{q:02d}": "Complex" for q in (2, 5, 7, 10, 13, 15, 17, 18, 20)},
    **{f"Q{q:02d}": "Very Complex" for q in (8, 9, 21, 22)},
}
QNAME = {
    "Q01": "Pricing Summary Report", "Q02": "Minimum Cost Supplier",
    "Q03": "Shipping Priority", "Q04": "Order Priority Checking",
    "Q05": "Local Supplier Volume", "Q06": "Forecasting Revenue Change",
    "Q07": "Volume Shipping", "Q08": "National Market Share",
    "Q09": "Product Type Profit Measure", "Q10": "Returned Item Reporting",
    "Q11": "Important Stock Identification", "Q12": "Shipping Modes and Order Priority",
    "Q13": "Customer Distribution", "Q14": "Promotion Effect",
    "Q15": "Top Supplier", "Q16": "Parts/Supplier Relationship",
    "Q17": "Small-Quantity-Order Revenue", "Q18": "Large Volume Customer",
    "Q19": "Discounted Revenue", "Q20": "Potential Part Promotion",
    "Q21": "Suppliers Who Kept Orders Waiting", "Q22": "Global Sales Opportunity",
}
TPCC = {
    "T1": ("New-Order", "Write-heavy"),
    "T2": ("Payment", "Write-heavy"),
    "T3": ("Order-Status", "Read-only"),
    "T4": ("Delivery", "Write-heavy"),
    "T5": ("Stock-Level", "Read-only"),
}

WORKLOAD = ([("tpch", q, QNAME[q], BANDS[q]) for q in sorted(QNAME)]
            + [("tpcc", t, TPCC[t][0], TPCC[t][1]) for t in sorted(TPCC)])

# ------------------------------------------------------- why a cell is empty
#
# One place, so the file explains itself and the plan and the file cannot drift
# apart. Keyed by (dbms, benchmark).

BLOCKED = {
    ("sqlserver", "tpch"): "not_run: edition cap lifted (MSSQL_PID now Developer); "
                           "SF10 campaign not yet executed - one database resident at "
                           "a time here.",
    ("sqlserver", "tpcc"): "not_run: TPC-C not yet executed on SQL Server. "
                           "PLAN.md B2, B3.",
    ("oracle",    "tpch"): "not_run: Oracle Free caps user data at 12 GB and TPC-H SF10 "
                           "loads to 10.81 GB, so the dataset fits but its indexes do "
                           "not. Being run per query group against only the tables each "
                           "group references.",
    ("oracle",    "tpcc"): "not_run: TPC-C not yet executed on Oracle.",
    ("mysql",     "tpch"): "not_run: queries validated 22/22 at SF1; SF10 campaign not "
                           "yet executed (one database resident at a time here). "
                           "one database resident at a time here.",
    ("mysql",     "tpcc"): "not_run: TPC-C not yet executed on MySQL.",
    ("postgresql", "tpcc"): "not_run: the two TPC-C implementations differ in locking "
                            "strategy, transaction boundary and warehouse range; "
                            "measuring them as written compares those choices, not the "
                            "frameworks. See tpcc_config.py.",
}

# A cap failure that applies to specific queries rather than a whole system.
# Measured, not assumed: on Oracle Free the six secondary indexes LINEITEM needs
# for the indexed configuration are about 1.1 GB each. With LINEITEM's 7.22 GB of
# data and its 1.25 GB primary key already resident, the fourth index raises
# ORA-12954. So the indexed configuration is reachable only for the five queries
# that never read LINEITEM.
LINEITEM_QUERIES = {"Q01", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09",
                    "Q10", "Q12", "Q14", "Q15", "Q17", "Q18", "Q19", "Q20",
                    "Q21"}
# Q09 and Q20 are the only two queries whose working set does not fit at all.
# Group G holds LINEITEM, ORDERS, CUSTOMER, PART and PARTSUPP together; loading
# PARTSUPP on top of the others reached 12.37 GB of data and the primary key
# raised ORA-12954 at 12.44 GB. Measured, not estimated - the driver reports
# resident size per group and the failure is in results/corrected/oracle_group_G.log.
BLOCKED_QUERY = {
    ("oracle", "non-indexed", "Q09"): "not_run: Q09 and Q20 need LINEITEM, ORDERS, "
        "CUSTOMER, PART and PARTSUPP resident together. That working set reaches "
        "12.37 GB of data and the PARTSUPP primary key raises ORA-12954 at "
        "12.44 GB against Oracle Free's 12 GB cap. Measured, not estimated. "
        "",
    ("oracle", "non-indexed", "Q20"): "not_run: Q09 and Q20 need LINEITEM, ORDERS, "
        "CUSTOMER, PART and PARTSUPP resident together. That working set reaches "
        "12.37 GB of data and the PARTSUPP primary key raises ORA-12954 at "
        "12.44 GB against Oracle Free's 12 GB cap. Measured, not estimated. "
        "",
    **{
    ("oracle", "indexed", q): "not_run: LINEITEM's six secondary indexes are ~1.1 GB "
                              "each on top of 7.22 GB of data and a 1.25 GB primary "
                              "key; the fourth raises ORA-12954 against Oracle Free's "
                              "12 GB cap. Measured, not estimated. The indexed "
                              "configuration is reachable on Oracle only for the five "
                              "queries that never read LINEITEM."
    for q in LINEITEM_QUERIES
    },
}

# A cell that failed for a reason that says nothing about the query or the
# framework - the machine ran out of disk mid-campaign, a container was
# restarted - is not the same as one that genuinely cannot complete. Both show
# as "partial"; only this one is worth re-running, and a reader should be able
# to tell them apart without reading the note.
NEEDS_RERUN = {
    # ("postgresql", "indexed", "Q18", "django", "orm") lived here from the
    # sandbox campaign, where the disk filled mid-sort. The cell was re-measured
    # on localhost on 2026-07-31 (three clean repetitions in
    # postgresql_indexed.campaign.log) and the note outlived the failure it
    # described by a month. What Q18 actually needs is in C23: it was measured
    # without passing validation, which this map cannot express and the
    # validation columns now do.
}

# --------------------------------------------------- measurements known bad
#
# A cell that was measured but whose measurement does not answer the question it
# claims to. Keeping the timing and marking it is more useful than deleting the
# row: a reader can see that the cell was run, and see why the number must not
# be used.

INVALIDATED = {
    # ("postgresql", "Q11") lived here until the query was re-measured with the
    # scale-corrected threshold. It now returns 8,685 rows instead of 0. The
    # entry is kept as a comment because the mechanism is the useful part: a
    # wrong substitution parameter does not fail, it succeeds at answering a
    # different question, and only a row-count check catches it.
}

# --------------------------------------------------- where each campaign ran
#
# Not every cell in this file was measured on the same machine, and two cells
# measured on different machines differ by the machine as well as by whatever the
# comparison is supposed to isolate. `campaign_id` was previously a single string
# applied to all 432 rows, which could not express that.
#
# The ORM-against-SQL overhead each row reports is a ratio of two timings taken
# in the same process on the same machine, so it is unaffected. What is affected
# is any comparison *across* rows: indexed against non-indexed, and one DBMS
# against another. Those are stated in CROSS_MACHINE below rather than left for a
# reader to notice.
LOCALHOST = "sf10-2026-07-localhost"      # Apple M4, 10 cores, 16 GB, macOS 26.5

# Corrected twice. C22 (2026-08-29) moved PostgreSQL and Oracle off a SANDBOX
# label they never earned: the sandbox PostgreSQL rows are the 2-worker runs
# archived under measurements/superseded/, while the rows in the results file
# come from the 2026-07-31 re-measurement whose campaign log carries this
# machine's paths, port 55432 and the 8-worker parallelism dump. Oracle's twenty
# non-indexed queries appear in the group A-G measure logs written here on
# 2026-07-31 and its indexed cells here on 2026-08-01.
#
# C30 (2026-08-30) removed the label entirely. MySQL non-indexed kept it on one
# argument: it has no surviving local log. That is not evidence of another
# machine, it is the absence of evidence about any machine, and the author - who
# ran the campaign - states every measurement in this study was taken on the
# Apple M4. Testimony from the person at the keyboard outranks an inference from
# a missing file. One machine, and the missing log survives as what it actually
# is: an unrecorded server build, not a second environment.
PROVENANCE = {
    ("postgresql", "indexed"):     LOCALHOST,
    ("postgresql", "non-indexed"): LOCALHOST,
    ("mysql",      "non-indexed"): LOCALHOST,
    ("mysql",      "indexed"):     LOCALHOST,
    ("oracle",     "non-indexed"): LOCALHOST,
    ("oracle",     "indexed"):     LOCALHOST,
    # Both SQL Server schemas were measured here, so unlike MySQL its
    # indexed-against-non-indexed contrast carries no hardware change and needs
    # no CROSS_MACHINE entry. Note for the write-up that SQL Server runs under
    # x86-64 emulation on this Apple Silicon host - there is no arm64 build of
    # the image - so its absolute times are not comparable with the other three
    # systems'. The ORM-versus-SQL comparison within a row is unaffected: both
    # timings are taken in the same process against the same server.
    ("sqlserver",  "non-indexed"): LOCALHOST,
    ("sqlserver",  "indexed"):     LOCALHOST,
}

# A campaign is normally one (dbms, schema) pair, but not always. Defect C6
# invalidated PostgreSQL's Q11 specifically - the scale-dependent FRACTION made
# it a different query - so Q11 alone was re-measured, and it was re-measured
# after the sandbox was gone. It is therefore the one PostgreSQL query in the
# file whose timings come from different hardware than the other twenty-one.
# Keyed per query so the exception is stated rather than averaged away.
PROVENANCE_QUERY = {
    # Q11's two entries were removed with C22: the other twenty-one PostgreSQL
    # queries were measured on this machine too, so Q11 is no longer an
    # exception and the map above already says LOCALHOST for it.
}

# Where a within-DBMS comparison spans two machines, say so on the rows
# themselves. There is no such case now. MySQL held the only entry, on the
# grounds that its two schemas were measured on different machines; C30 retired
# that, because every campaign in this study ran on the one Apple M4 and the
# label rested on a missing log rather than on evidence of a second machine.
CROSS_MACHINE = {}

# The same caveat, one query rather than one schema. Q11's absolute seconds must
# not be compared with the other PostgreSQL queries' - only its overhead ratio,
# which is internally consistent, and its comparison with Q11 elsewhere.
CROSS_MACHINE_QUERY = {
    # The Q11 caveat that stood here claimed a hardware change between Q11 and
    # the other PostgreSQL queries. There was none - all 22 were measured on
    # this machine (C22) - so four rows carried a warning about a difference
    # that did not exist. Kept as a comment because the shape is the useful
    # part: a per-row caveat is only as true as the provenance map behind it.
}

FIELDS = [
    # identity, matching the original file's leading columns
    "benchmark", "orm", "orm_version", "query_id", "query_name",
    "complexity_band", "dbms", "dbms_version", "schema_config",
    "scale_factor", "dataset_size_gb",
    # the measurement pair
    "direct_sql_execution_s", "total_orm_execution_s",
    "overhead_ratio", "overhead_percentage", "overhead_abs_s",
    "rows_returned",
    # dispersion, so a reader can judge stability
    "sql_min_s", "sql_max_s", "sql_cv_pct",
    "orm_min_s", "orm_max_s", "orm_cv_pct", "repetitions_measured",
    # completeness
    "sql_status", "orm_status", "status_note",
    # MOEF phase 2, from real EXPLAIN ANALYZE output
    "orm_plan_operators", "orm_median_qerror", "orm_max_qerror",
    "orm_operators_qerror_gt_10", "orm_underestimate_rate_pct",
    "sql_plan_operators", "sql_median_qerror", "sql_max_qerror",
    "sql_operators_qerror_gt_10", "sql_underestimate_rate_pct",
    "orm_plan_file", "sql_plan_file",
    # implementation validation
    "validated_orm_path_is_orm", "validated_results_match",
    "validated_baselines_match", "validated_orm_equals_sql",
    "validated_rows_nonzero", "validation_source",
    # provenance
    "timing_method", "aggregation", "campaign_id",
]

# scale_factor is filled per run from --scale, not fixed here: this constant
# read "10" while the script was the SF10 campaign's only consumer, and a
# constant that happens to be right is indistinguishable from one that is.
CONST = {
    "timing_method": "time.perf_counter, client-side end-to-end",
    "aggregation": "median of measured repetitions, first discarded as warmup",
}

# --------------------------------------------------------------- loading


def _row_is_this_scale(r, scale):
    """Does this measurement row belong to the campaign being built?

    A blank scale_factor is accepted only when building SF10. The SF10
    measurement files were written before run_query.py recorded the column, so
    for them blank means ten; for any other scale factor a blank is a row whose
    provenance cannot be established, and it is excluded rather than assumed.
    """
    if "scale_factor" not in r:
        # The column is absent from the file altogether, not blank within it.
        # run_tpcc.py and run_tpcc_throughput.py never wrote one, so every
        # TPC-C row was excluded from every build except SF10 and the summary
        # read "0 complete, 10 not_run" for all eight TPC-C configurations
        # while the measurements sat in the directory. A file with no such
        # column takes its provenance from the directory it is in, which is
        # exactly the separation results_paths.py enforces; a file that HAS the
        # column and leaves it blank is still a row that cannot be placed.
        return True
    v = str(r.get("scale_factor", "")).strip()
    if v == "":
        return str(scale) == "10"
    return v == str(scale)


def load_measurements(root, scale="10"):
    """Every per-configuration CSV in the measurements directory, keyed by cell.

    Deliberately NOT recursive. An earlier version walked the whole
    results/corrected/ tree, which also contains archived copies and the SF1
    runs. Those carry the same (dbms, schema, query, framework, path) keys, so
    whichever file os.walk happened to reach last won and a rebuild could
    quietly replace SF10 measurements with SF1 ones. One flat directory, one
    file per (dbms, schema), nothing else.

    The dbms and schema come from the rows themselves, not the filename, so a
    mis-named file cannot silently land in the wrong cell.
    """
    m = {}
    if not os.path.isdir(root):
        return m
    for dirpath, _dirs, files in ((root, [], sorted(os.listdir(root))),):
        for fn in sorted(f for f in files
                         if os.path.isfile(os.path.join(root, f))):
            if not fn.endswith(".csv"):
                continue
            try:
                rows = list(csv.DictReader(open(os.path.join(dirpath, fn))))
            except Exception:
                continue
            if not rows:
                continue
            # Block-protocol files carry one row per EXECUTION, not per path:
            # eight blocks x four paths plus warmups, with elapsed_s and no
            # median_s. Read as if they were run_query.py output, the last row
            # for a path simply won - a warmup or a failure as easily as a
            # measurement - and the summary read "0 complete" for every cell.
            # Every SF1 measurement in this study is in this format, so the
            # results file could not be built from any of them.
            if "block" in rows[0] and "is_warmup" in rows[0]:
                for key, agg in _aggregate_blocks(rows, scale).items():
                    m[key] = agg
                continue
            for r in rows:
                if not r.get("framework") or not r.get("query_id"):
                    break               # not a per-query measurement file
                if not _row_is_this_scale(r, scale):
                    break               # a different scale factor entirely
                key = (r.get("dbms", ""), r.get("schema_config", ""),
                       r.get("query_id", ""), r.get("framework", ""),
                       r.get("path", ""))
                m[key] = r
    return m


DECLARED_ABSENT_STATUSES = ("timeout", "not_expressible")


def _ceiling_words(raw):
    """A ceiling in seconds, whatever syntax the vendor reported it in."""
    t = str(raw or "").strip().lower().replace("client-side:", "")
    if not t:
        return "campaign"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s|min|h)?", t)
    if not m:
        return t
    v = float(m.group(1)) * {"ms": .001, "s": 1., "min": 60., "h": 3600.,
                             None: .001}[m.group(2)]
    return "%g s" % v


def _aggregate_blocks(rows, scale):
    """One summary row per path from a run_block.py file.

    median_s is the median over the eight measured blocks, which is what the
    per-path timing column reports. It is NOT what the overhead column is
    computed from: ANALYSIS_PLAN section 1 defines the estimand as the median
    of the within-block paired log ratios, and a ratio of medians is a
    different quantity - the pairing is the whole point of the block design, and
    averaging it away here would discard it at the last step.

    So each path also carries paired_ratio, the exponential of that median log
    ratio, computed inside the block where both arms saw the same parameter set.
    """
    import statistics
    by_path = defaultdict(list)
    by_block = defaultdict(dict)
    for r in rows:
        if r.get("is_warmup") != "0" or not _row_is_this_scale(r, scale):
            continue
        cell = (r.get("dbms", ""), r.get("schema_config", ""), r.get("query_id", ""))
        pk = cell + (r.get("framework", ""), r.get("path", ""))
        by_path[pk].append(r)
        if r.get("status") == "ok":
            try:
                by_block[cell + (r.get("framework", ""), int(r["block"]))][
                    r.get("path", "")] = float(r["elapsed_s"])
            except (ValueError, KeyError):
                pass

    # The paired estimand, per (cell, framework).
    paired = {}
    per_fw = defaultdict(list)
    for (dbms, schema, qid, fw, _blk), d in by_block.items():
        if "orm" in d and "sql" in d and d["sql"] > 0 and d["orm"] > 0:
            per_fw[(dbms, schema, qid, fw)].append(math.log(d["orm"] / d["sql"]))
    for k, lrs in per_fw.items():
        if lrs:
            paired[k] = math.exp(statistics.median(lrs))

    # A path censored in the cell warmup has NO measured row, so it never
    # reaches by_path and the cell falls through to the builder's not_run
    # branch - which then prints whatever standing reason it holds for that
    # system. PostgreSQL non-indexed Q17 came out as a bare "not_run" and
    # MySQL's as "SF10 campaign not yet executed", when what actually happened
    # is that all four paths exceeded the ceiling and section 6 recorded a
    # one-sided bound. That is a result, and the file has to say so: absence is
    # never silent.
    for r in rows:
        if r.get("is_warmup") != "1" or r.get("status") not in DECLARED_ABSENT_STATUSES:
            continue
        if not _row_is_this_scale(r, scale):
            continue
        pk = (r.get("dbms", ""), r.get("schema_config", ""), r.get("query_id", ""),
              r.get("framework", ""), r.get("path", ""))
        by_path.setdefault(pk, [])

    out = {}
    for pk, rs in by_path.items():
        if not rs:
            # Censored before any block ran.
            cr = next((r for r in rows
                       if (r.get("dbms",""), r.get("schema_config",""),
                           r.get("query_id",""), r.get("framework",""),
                           r.get("path","")) == pk and r.get("is_warmup") == "1"), None)
            if cr is None:
                continue
            st = cr.get("status")
            base = dict(cr)
            base.update({
                "median_s": "", "n_blocks": "0", "status": st,
                # Each vendor reports its ceiling in its own syntax -
                # PostgreSQL "15min", MySQL milliseconds, Oracle and SQL Server
                # a client-side bound - so it is normalised to seconds here
                # rather than pasted in raw as "the 15min s ceiling".
                "note": ("censored: exceeded the %s ceiling in warmup, "
                         "recorded as a one-sided bound (section 6)"
                         % _ceiling_words(cr.get("ceiling_s", ""))
                         if st == "timeout" else
                         "not expressible in this ORM on this vendor (C17)"),
                "paired_ratio": "",
            })
            out[pk] = base
            continue
        ok = [float(r["elapsed_s"]) for r in rs if r.get("status") == "ok"]
        # A path with no successful execution reports the reason the plan
        # declared, not silence: a ceiling timeout is a one-sided bound and an
        # inexpressible query is C17.
        statuses = {r.get("status") for r in rs}
        if ok:
            status = "ok"
        elif "not_expressible" in statuses:
            status = "not_expressible"
        elif "timeout" in statuses:
            status = "timeout"
        else:
            status = "error"
        base = dict(rs[0])
        base.update({
            "median_s": ("%.6f" % statistics.median(ok)) if ok else "",
            "n_blocks": str(len(ok)),
            "status": status,
            "note": next((r.get("note", "") for r in rs if r.get("note")), ""),
            "paired_ratio": ("%.6f" % paired[pk[:4]]) if pk[:4] in paired else "",
        })
        out[pk] = base
    return out


def load_qerror(root):
    q = {}
    for dirpath, _dirs, files in os.walk(root):
        if "qerror_by_query.csv" not in files:
            continue
        for r in csv.DictReader(open(os.path.join(dirpath, "qerror_by_query.csv"))):
            q[(r.get("dbms", "postgresql"), r["schema_config"], r["query_id"],
               r["framework"], r["access_path"])] = r
    return q


NOT_RECORDED = ("not_recorded",) * 5 + ("",)


def load_validation(root):
    """Every validation verdict the campaigns wrote, keyed (dbms, schema, query).

    Until 2026-08-29 this read one file - results/corrected/validation.log, the
    SF1 PostgreSQL validation of 2026-07-28, three checks - keyed it by query id
    alone, and stamped that verdict on all eight campaigns. Every TPC-H row said
    "pass". The per-campaign logs written since disagree for eight measured
    cells, one of them (Oracle non-indexed Q08, Django) a recorded wrong
    answer. Defect C22; the cells themselves are C23.

    Now: scan every *.log under `root`, take the campaign from the filename
    (postgresql_*, pg_q11*, mysql_*, sqlserver_*, oracle_group_*), the schema
    from the filename or - for the Oracle group logs, which carry none - from
    the sibling measure log's query headers, or - for pg_q11.campaign.log,
    which validated both schemas in one run - from its own "=== validating"
    markers. Later logs override earlier ones. The SF1 file matches no campaign
    prefix and is skipped. Verdicts for the five columns the validator prints
    (ORM?, MATCH, SQL=, ORM=SQL, ROWS>0) plus the source file; a query the
    validator could not finish is recorded as the error it raised, which is
    the distinction run_mysql_campaign.sh's comment asks for and nothing kept.
    """
    import re
    v = {}
    if not root or not os.path.isdir(root):
        return v

    # `oracle_group_*` is what run_oracle_campaign.sh wrote in July, one log per
    # query group. The B1a re-validations of 2026-08-30 were run per schema and
    # named for the convention the other three systems already use,
    # `<dbms>_<schema>.b1a.validate.log`, and matched no prefix here - so they
    # were skipped in silence and four Oracle cells kept citing a July verdict
    # the re-validation had superseded. Both spellings are accepted now. The two
    # schema spellings are listed rather than a bare `oracle_` because that would
    # also sweep in oracle_chain*.log and oracle_reload_*.log, which are shell
    # transcripts, not validator tables. Defect C27.
    prefixes = (("postgresql_", "postgresql"), ("pg_q11", "postgresql"),
                ("mysql_", "mysql"), ("sqlserver_", "sqlserver"),
                ("oracle_group_", "oracle"), ("oracle_indexed", "oracle"),
                ("oracle_non_indexed", "oracle"))
    # results/corrected/*.log, plus results/corrected/logs/ where
    # run_oracle_campaign.sh writes its per-group validation logs.
    candidates = []
    for sub in ("", "logs"):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            candidates += [os.path.join(sub, f) for f in os.listdir(d)
                           if f.endswith(".log") and not f.endswith(".gate.log")]
    # Deterministic order, and not by mtime. Later files override earlier ones,
    # so the order decides which log a verdict is attributed to - and mtimes do
    # not survive git. Checking main out over a branch that carried these logs
    # deleted and restored all 77 of them, collapsing every timestamp to one
    # second and silently re-attributing 132 rows from a campaign log to a
    # validate log. The tables were identical so no verdict moved, but nothing
    # in the code guaranteed that.
    #
    # A campaign log is a `tee` of the validator's output, so where both exist
    # they carry the same table; the validate log is the primary artifact and
    # wins by sorting last. Everything else is ordered by path.
    # Generation, then kind, then path. Sorting on the path alone is
    # deterministic - which is what C22 required - but it has no notion of
    # recency, and `postgresql_indexed.b1a.validate.log` sorts before
    # `postgresql_indexed.validate.log` because `b` precedes `v`. Later wins, so
    # the July verdict would silently override the August re-validation that
    # supersedes it. A campaign marker in the name settles which generation a log
    # belongs to; add the next one here rather than relying on the alphabet.
    GENERATION = {".b1a.": 1}

    def rank(rel):
        base = os.path.basename(rel)
        gen = next((g for marker, g in GENERATION.items() if marker in base), 0)
        return (gen, 0 if "campaign" in base else 1, rel)
    files = sorted(candidates, key=rank)
    unattributed = []
    for rel in files:
        fn = os.path.basename(rel)
        dbkey = next((d for p, d in prefixes if fn.startswith(p)), None)
        if dbkey is None:
            # A file named *.validate.log is a validator artifact by name, so one
            # that matches no campaign prefix is a naming mistake, not a stray
            # file, and skipping it quietly is how C27 hid: the run reported
            # success and four cells kept a superseded verdict. Say it instead.
            # Everything else here (tpcc_*, *_load, *_chain, the SF1
            # validation.log) legitimately matches nothing and stays quiet.
            if fn.endswith(".validate.log"):
                unattributed.append(rel)
            continue
        if "non_indexed" in fn or "non-indexed" in fn or "nonidx" in fn:
            schema = "non-indexed"
        elif "indexed" in fn or "_idx" in fn:
            schema = "indexed"
        else:
            schema = None
        if dbkey == "oracle" and schema is None:
            m = re.match(r"oracle_group_([A-Z])\.", fn)
            sib = (os.path.join(root, os.path.dirname(rel), "oracle_group_%s.measure.log" % m.group(1))
                   if m else "")
            if os.path.exists(sib):
                mm = re.search(r"=== Q\d\d \([^)]*\)\s+oracle\s+(non-indexed|indexed)",
                               open(sib, errors="replace").read())
                schema = mm.group(1) if mm else None
        try:
            lines = open(os.path.join(root, rel), errors="replace").read().splitlines()
        except OSError:
            continue
        fn = rel   # the source column names the path under results/corrected/
        for line in lines:
            s = line.strip()
            m = re.match(r"^=== validating q\d\d \((non-indexed|indexed)\)", s)
            if m:
                schema = m.group(1)
                continue
            if schema is None:
                continue
            m = re.match(r"^(q\d\d)\s+(yes|NO|no|n/a)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+\d", s)
            if m:
                # `n/a` is a check that could not run because the access path it
                # compares did not run. It is neither a pass nor a failed
                # comparison, and flattening it into either would misreport the
                # cell - so it gets its own value.
                def verdict(x, fail_label):
                    return ("pass" if x in ("yes", "ok")
                            else "not_checked" if x == "n/a"
                            else fail_label(x))
                v[(dbkey, schema, m.group(1).upper())] = (
                    verdict(m.group(2), lambda _x: "FAIL:not-ORM"),
                    *(verdict(x, lambda y: "FAIL:" + y) for x in m.groups()[2:6]),
                    fn)
                continue
            m = re.match(r"^(q\d\d)\s+ERROR\s+(.*)$", s)
            if m:
                err = "error: " + m.group(2).strip()[:70]
                v[(dbkey, schema, m.group(1).upper())] = (err,) * 5 + (fn,)
    if unattributed:
        sys.stderr.write(
            "WARNING: %d validate log(s) matched no campaign prefix and were "
            "ignored, so any verdict in them is not in the results file:\n"
            % len(unattributed))
        for rel in unattributed:
            sys.stderr.write("    %s\n" % rel)
    return v


def f(r, k):
    if not r:
        return None
    try:
        return float(r.get(k, ""))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- assembly


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default=os.environ.get("TPCH_SF", "10"),
                    help="scale factor of the campaign to build. Selects which "
                         "measurement rows are included and, unless overridden "
                         "below, every default path. Defaults to TPCH_SF, or 10.")
    ap.add_argument("--measurements", default=None,
                    help="directory of per-configuration measurement CSVs")
    ap.add_argument("--qerror", default=None,
                    help="directory tree searched for qerror_by_query.csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--validation-logs", default=None,
                    help="directory whose *.log files carry the per-campaign "
                         "validation tables (C22: one SF1 file used to stand in "
                         "for all eight campaigns)")
    ap.add_argument("--campaign", default=None)
    ap.add_argument("--plan", default=None,
                    help="rewrite the status block in this file from the data. "
                         "Empty to rewrite nothing. Defaults to PLAN.md when "
                         "building SF10 and to nothing otherwise: PLAN.md's "
                         "block describes the SF10 grid, and a rebuild at "
                         "another scale factor must not quietly replace it.")
    args = ap.parse_args()

    # One module decides these, so a campaign cannot be measured into one tree
    # and rebuilt from another.
    sf = str(args.scale).strip()
    if args.measurements is None:
        args.measurements = results_paths.measurements_dir(sf)
    if args.qerror is None:
        args.qerror = results_paths.qerror_dir(sf)
    if args.out is None:
        args.out = results_paths.all_results_path(sf)
    if args.validation_logs is None:
        args.validation_logs = results_paths.validation_logs_dir(sf)
    if args.campaign is None:
        args.campaign = results_paths.campaign_id(sf)
    if args.plan is None:
        args.plan = results_paths.plan_path(sf)

    CONST["scale_factor"] = sf
    legacy = results_paths.is_legacy(sf)

    meas = load_measurements(args.measurements, sf)
    qerr = load_qerror(args.qerror if hasattr(args, "qerror") else args.measurements)
    val = load_validation(args.validation_logs)

    rows = []
    for dbkey, dblabel, dbver in DBMS:
        for schema, schema_label in SCHEMAS:
            for bench, qid, qname, band in WORKLOAD:
                for fw, fw_label, fwver in ORMS:
                    sql = meas.get((dbkey, schema, qid, fw, "sql"))
                    orm = meas.get((dbkey, schema, qid, fw, "orm"))

                    sql_t = f(sql, "median_s") if sql and sql.get("status") == "ok" else None
                    orm_t = f(orm, "median_s") if orm and orm.get("status") == "ok" else None

                    ratio = pct = absd = None
                    if sql_t and orm_t:
                        # Prefer the paired estimand the block design exists to
                        # produce: the median of the within-block log ratios,
                        # where both arms saw the same parameter set and ran
                        # adjacent in time. orm_t/sql_t is a ratio of medians -
                        # a different quantity, and one that silently discards
                        # the pairing. Files from run_query.py carry no paired
                        # value and fall back to it, which is correct for them.
                        pr = (orm or {}).get("paired_ratio") or (sql or {}).get("paired_ratio")
                        ratio = round(float(pr), 4) if pr else round(orm_t / sql_t, 4)
                        pct = round((ratio - 1.0) * 100, 2)
                        absd = round(orm_t - sql_t, 4)

                    if sql is None and orm is None:
                        # A cell the campaign chain refused to measure because
                        # the validator did not pass it (C23) says so, with the
                        # verdict, ahead of any standing reason for the system.
                        gate = val.get((dbkey, schema, qid)) if bench == "tpch" else None
                        if gate and any(x not in ("pass", "not_recorded") for x in gate[:5]):
                            note = ("not_run: gated by validation (C23) - ORM?=%s MATCH=%s "
                                    "SQL==%s ORM=SQL=%s ROWS>0=%s [%s]" % gate)
                        else:
                            note = (BLOCKED_QUERY.get((dbkey, schema, qid))
                                    or BLOCKED.get((dbkey, bench), "not_run"))
                    else:
                        note = " | ".join(x.get("note", "") for x in (sql, orm)
                                          if x and x.get("note"))

                    for _fw, _p in (("django", "sql"), ("django", "orm"),
                                    ("sqlalchemy", "sql"), ("sqlalchemy", "orm")):
                        if _fw != fw:
                            continue
                        rr = NEEDS_RERUN.get((dbkey, schema, qid, _fw, _p))
                        if rr:
                            note = f"{rr} | {note}" if note else rr

                    # Only annotate cells that were actually measured; a not_run
                    # cell already carries the reason it was not run, and adding
                    # a machine caveat to it would displace that.
                    xm = (CROSS_MACHINE_QUERY.get((dbkey, qid))
                          or CROSS_MACHINE.get(dbkey))
                    if xm and (sql is not None or orm is not None):
                        note = f"{note} | {xm}" if note else xm

                    bad = INVALIDATED.get((dbkey, qid))
                    if bad and (sql is not None or orm is not None):
                        note = bad if not note else f"{bad} | {note}"
                        # the overhead figure is meaningless if the query is
                        # not the query, so it does not get published
                        ratio = pct = absd = None

                    qo = qerr.get((dbkey, schema, qid, fw, "orm"), {})
                    qsq = qerr.get((dbkey, schema, qid, fw, "sql"), {})
                    pf = f"execution_plans/{schema}/{qid}_{fw}_%s.json"

                    # PROVENANCE, PROVENANCE_QUERY and the B1a override record
                    # which machine and which run produced each SF10 cell (C22,
                    # C30). They are that campaign's history, not a property of
                    # the grid, so at any other scale factor the campaign is the
                    # one being built. Applying them here is how a rerun would
                    # inherit the retired sandbox's attribution.
                    if legacy:
                        campaign = (PROVENANCE_QUERY.get((dbkey, schema, qid))
                                    or PROVENANCE.get((dbkey, schema), args.campaign))
                        if (dbkey, schema, qid) in DBMS_VERSION_QUERY:
                            campaign = B1A_CAMPAIGN
                    else:
                        campaign = args.campaign

                    # The verdict the campaign's own validator recorded for this
                    # query on this system and schema. A cell that carries a
                    # timing but no passing verdict is not invalidated here -
                    # decision of 2026-08-29: keep the timing, say so on the row,
                    # disclose in the paper, re-validate when the database is
                    # reloaded. Timeouts on the validator's clock are not wrong
                    # answers, but they are not verified answers either, and the
                    # row is the place a reader finds that out. (C23)
                    vv = val.get((dbkey, schema, qid), NOT_RECORDED) if bench == "tpch" else NOT_RECORDED
                    if (sql_t is not None or orm_t is not None) and bench == "tpch" \
                            and any(x != "pass" and x != "not_recorded" for x in vv[:5]):
                        if "NotExpressible" in vv[0]:
                            # Django cannot state Q13 on this system (C17). The
                            # validator raises on that path and stops, so the
                            # other three paths of Q13 - SQLAlchemy's ORM and
                            # both hand-written baselines - were never checked
                            # against each other. The Django cell carries C17
                            # as its own status; this note is for the ones that
                            # were measured and never verified.
                            c23 = ("checks never ran (C23): the validator stops at "
                                   "Django's Q13NotExpressible (C17) before comparing "
                                   "this path [%s]" % vv[5])
                        else:
                            c23 = ("measured without a passing validation (C23): "
                                   "ORM?=%s MATCH=%s SQL==%s ORM=SQL=%s ROWS>0=%s [%s]"
                                   % vv)
                        note = f"{c23} | {note}" if note else c23

                    row = dict(CONST)
                    row.update({
                        "benchmark": bench,
                        "orm": fw_label,
                        # The qualifier follows the campaign with no surviving
                        # log, not a machine: see PROVENANCE and C30.
                        "orm_version": NOT_YET_RECORDED if not legacy else
                                       fwver + (UNLOGGED_ORM_QUALIFIER
                                                if (dbkey, schema) == ("mysql", "non-indexed")
                                                else ""),
                        "query_id": qid, "query_name": qname,
                        "complexity_band": band,
                        "dbms": dblabel,
                        "dbms_version": ((DBMS_VERSION_QUERY.get((dbkey, schema, qid))
                                          or DBMS_VERSION.get((dbkey, schema), dbver))
                                         if legacy else NOT_YET_RECORDED),
                        "dataset_size_gb": DATASET_GB[dbkey],
                        "schema_config": schema_label,
                        "direct_sql_execution_s": sql_t if sql_t is not None else "",
                        "total_orm_execution_s": orm_t if orm_t is not None else "",
                        "overhead_ratio": ratio if ratio is not None else "",
                        "overhead_percentage": pct if pct is not None else "",
                        "overhead_abs_s": absd if absd is not None else "",
                        "rows_returned": (orm or sql or {}).get("rows_returned", ""),
                        "sql_min_s": f(sql, "min_s") or "", "sql_max_s": f(sql, "max_s") or "",
                        "sql_cv_pct": f(sql, "cv_pct") if sql else "",
                        "orm_min_s": f(orm, "min_s") or "", "orm_max_s": f(orm, "max_s") or "",
                        "orm_cv_pct": f(orm, "cv_pct") if orm else "",
                        "repetitions_measured": (orm or sql or {}).get("repetitions_measured", ""),
                        "sql_status": ("invalid" if bad and sql else
                                       (sql.get("status") if sql else "not_run")),
                        "orm_status": ("invalid" if bad and orm else
                                       (orm.get("status") if orm else "not_run")),
                        "status_note": note[:300],
                        "orm_plan_operators": qo.get("operators", ""),
                        "orm_median_qerror": qo.get("median_qerror", ""),
                        "orm_max_qerror": qo.get("max_qerror", ""),
                        "orm_operators_qerror_gt_10": qo.get("operators_qerror_gt_10", ""),
                        "orm_underestimate_rate_pct": qo.get("underestimate_rate_pct", ""),
                        "sql_plan_operators": qsq.get("operators", ""),
                        "sql_median_qerror": qsq.get("median_qerror", ""),
                        "sql_max_qerror": qsq.get("max_qerror", ""),
                        "sql_operators_qerror_gt_10": qsq.get("operators_qerror_gt_10", ""),
                        "sql_underestimate_rate_pct": qsq.get("underestimate_rate_pct", ""),
                        "orm_plan_file": pf % "orm" if qo else "",
                        "sql_plan_file": pf % "sql" if qsq else "",
                        "validated_orm_path_is_orm": vv[0],
                        "validated_results_match": vv[1],
                        "validated_baselines_match": vv[2],
                        "validated_orm_equals_sql": vv[3],
                        "validated_rows_nonzero": vv[4],
                        "validation_source": vv[5],
                        "campaign_id": campaign,
                    })
                    rows.append(row)

    expected = len(DBMS) * len(SCHEMAS) * len(WORKLOAD) * len(ORMS)
    assert len(rows) == expected, f"grid is {len(rows)} rows, expected {expected}"

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    # ------------------------------------------------------------- report
    complete = [r for r in rows if r["overhead_percentage"] != ""]
    notrun = [r for r in rows if r["sql_status"] == "not_run"
              and r["orm_status"] == "not_run"]
    partial = [r for r in rows if r["overhead_percentage"] == "" and r not in notrun]
    withq = [r for r in rows if r["orm_median_qerror"] != ""]

    # The campaign writes its state next to the results tree, not inside the
    # measurements directory, so look in both rather than reporting "idle" while
    # a campaign is plainly running.
    state = next((c for c in (os.path.join(args.measurements, ".campaign_state"),
                              os.path.join(os.path.dirname(args.measurements.rstrip("/")),
                                           ".campaign_state"),
                              os.path.join(args.qerror, ".campaign_state"))
                  if os.path.exists(c)), None)
    if rewrite_plan(args.plan, status_markdown(rows, state)):
        print(f"refreshed the status block in {args.plan}")

    print(f"wrote {args.out}")
    print(f"  {len(rows)} rows = {len(DBMS)} DBMS x {len(ORMS)} frameworks x "
          f"{len(SCHEMAS)} schemas x {len(WORKLOAD)} queries")
    print(f"  {len(complete):>3d} complete   (both paths measured, overhead computed)")
    print(f"  {len(partial):>3d} partial    (attempted, at least one path timed out or errored)")
    print(f"  {len(notrun):>3d} not_run    (reason in status_note)")
    print(f"  {len(withq):>3d} carry q-error from a collected execution plan")
    print()
    print(f"  {'dbms':12s} {'bench':6s} {'schema':12s} {'complete':>9s} "
          f"{'partial':>8s} {'not_run':>8s}")
    for _, dblabel, _ in DBMS:
        for bench in ("tpch", "tpcc"):
            for _, schema_label in SCHEMAS:
                sub = [r for r in rows if r["dbms"] == dblabel
                       and r["benchmark"] == bench
                       and r["schema_config"] == schema_label]
                c = sum(1 for r in sub if r["overhead_percentage"] != "")
                nr = sum(1 for r in sub if r["sql_status"] == "not_run"
                         and r["orm_status"] == "not_run")
                print(f"  {dblabel:12s} {bench:6s} {schema_label:12s} "
                      f"{c:>9d} {len(sub)-c-nr:>8d} {nr:>8d}")
    print()
    for _, dblabel, _ in DBMS:
        for _, schema_label in SCHEMAS:
            for _, fwl, _ in ORMS:
                v = [float(r["overhead_percentage"]) for r in rows
                     if r["dbms"] == dblabel and r["schema_config"] == schema_label
                     and r["orm"] == fwl and r["overhead_percentage"] != ""]
                if v:
                    print(f"  {dblabel:12s} {fwl:11s} {schema_label:12s} "
                          f"median overhead {statistics.median(v):>7.1f}%  n={len(v)}")
    return 0


def progress_line(state_path):
    """What the campaign says it is doing, written by the campaign itself.

    The narrative lines at the top of PLAN.md went stale between pushes because
    they were prose and prose does not update itself. The campaign script writes
    one line to a state file as it enters each stage; this folds that line into
    the generated block, so 'doing right now' is as current as the numbers are.
    """
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    doing = "idle"
    if state_path and os.path.exists(state_path):
        try:
            doing = open(state_path).read().strip() or doing
        except Exception:
            pass
    return ("*Generated %s.* **Doing right now:** %s" % (now, doing))


# The order the remaining systems are worked in, and why each is where it is.
# Generated into the plan so the queue is always visible and always current.
# These strings are the one hand-maintained part of a generated block, so they go
# stale silently: for three campaigns this table said MySQL was "in progress" and
# SQL Server was "next" while both were finished. Update them when a system's
# state changes. The counts beside them are computed and always correct - if the
# prose and the numbers disagree, the numbers are right.
WORK_ORDER = [
    ("PostgreSQL", "TPC-H", "re-measured at 8 parallel workers; the 2-worker "
                            "sandbox rows are archived under measurements/superseded/"),
    ("MySQL", "TPC-H", "done - single-threaded per query, which no setting "
                       "changes (docs/PARALLELISM.md)"),
    ("SQL Server", "TPC-H", "done - MAXDOP 8, under x86-64 emulation; Q13's "
                            "Django ORM cell is inexpressible (C17)"),
    ("Oracle", "TPC-H", "done as far as the licence allows - 12 GB cap, run per "
                        "query group; indexed is reachable only for the 5 queries "
                        "that never read LINEITEM"),
]


def remaining_markdown(rows):
    """A queue, generated from the data rather than described in prose."""
    lines = ["### What is left, in order", "",
             "| System | Benchmark | Measured | Left | State |",
             "|---|---|---:|---:|---|"]
    for dblabel, bench_label, note in WORK_ORDER:
        bench = "tpch" if bench_label == "TPC-H" else "tpcc"
        sub = [r for r in rows if r["dbms"] == dblabel and r["benchmark"] == bench]
        done = sum(1 for r in sub
                   if r["overhead_percentage"] != ""
                   or (r["sql_status"] not in ("not_run", "")
                       and r["orm_status"] not in ("not_run", "")))
        lines.append("| %s | %s | %d | %d | %s |"
                     % (dblabel, bench_label, done, len(sub) - done, note))
    # Counted, not asserted. This row used to hardcode a measured count of 0 and
    # a note saying TPC-C "needs schema, load and measurement", and went on
    # saying it after all 80 cells were measured - inside a block whose whole
    # purpose is that the plan cannot disagree with the data. The same mistake
    # the comment on WORK_ORDER warns about, in the one line that was exempt
    # from the loop that avoids it.
    tpcc = [r for r in rows if r["benchmark"] == "tpcc"]
    tpcc_done = sum(1 for r in tpcc
                    if r["overhead_percentage"] != ""
                    or (r["sql_status"] not in ("not_run", "")
                        and r["orm_status"] not in ("not_run", "")))
    tpcc_left = len(tpcc) - tpcc_done
    note = ("done - latency in this grid, QPM at concurrency 50 in "
            "measurements/tpcc_throughput.csv (Oracle QPM outstanding)"
            if tpcc_left == 0 else
            "in progress - %d of %d cells still to measure" % (tpcc_left, len(tpcc)))
    lines.append("| all four | TPC-C | %d | %d | %s |" % (tpcc_done, tpcc_left, note))
    return "\n".join(lines)


def status_markdown(rows, state_path=None):
    """The status block for PLAN.md, generated from the file that was just
    written so the plan and the data cannot disagree."""
    def bucket(r):
        if r["sql_status"] == "invalid" or r["orm_status"] == "invalid":
            return "invalid"
        if r["overhead_percentage"] != "":
            return "complete"
        if r["sql_status"] == "not_run" and r["orm_status"] == "not_run":
            return "not_run"
        return "partial"

    counts = {}
    for r in rows:
        counts[bucket(r)] = counts.get(bucket(r), 0) + 1
    withq = sum(1 for r in rows if r["orm_median_qerror"] != "")
    measured = counts.get("complete", 0)

    out = []
    out.append(progress_line(state_path))
    out.append("")
    out.append(remaining_markdown(rows))
    out.append("")
    out.append("## Status: %d of %d rows emitted, %d measured (%.0f%%), %d with q-error"
               % (len(rows), len(rows), measured, 100.0 * measured / len(rows), withq))
    out.append("")
    out.append("This block is regenerated by `scripts/4-analysis/make_all_results.py`")
    out.append("every time the results file is rebuilt. It is never edited by hand.")
    out.append("")
    out.append("| DBMS | Bench | Schema | Complete | Partial | Invalid | Not run |")
    out.append("|---|---|---|---:|---:|---:|---:|")
    for _, dblabel, _ in DBMS:
        for bench in ("tpch", "tpcc"):
            for _, schema_label in SCHEMAS:
                sub = [r for r in rows if r["dbms"] == dblabel
                       and r["benchmark"] == bench
                       and r["schema_config"] == schema_label]
                if not sub:
                    continue
                b = [bucket(r) for r in sub]
                out.append("| %s | %s | %s | %d | %d | %d | %d |"
                           % (dblabel, bench.upper().replace("TPCH", "TPC-H")
                              .replace("TPCC", "TPC-C"), schema_label,
                              b.count("complete"), b.count("partial"),
                              b.count("invalid"), b.count("not_run")))
    out.append("")
    out.append("*Complete* = both paths measured, overhead computed. *Partial* = attempted,")
    out.append("one path timed out or errored. *Invalid* = measured, but the measurement does")
    out.append("not answer the question it claims to. *Not run* = never attempted. Every one")
    out.append("of these carries its reason in `status_note`, in words, not as a blank cell.")
    out.append("")
    out.append("**Median ORM overhead against that framework's own hand-written SQL:**")
    out.append("")
    out.append("| DBMS | Schema | Django | SQLAlchemy |")
    out.append("|---|---|---:|---:|")
    for _, dblabel, _ in DBMS:
        for _, schema_label in SCHEMAS:
            cells = []
            for _, fwl, _ in ORMS:
                v = [float(r["overhead_percentage"]) for r in rows
                     if r["dbms"] == dblabel and r["schema_config"] == schema_label
                     and r["orm"] == fwl and r["overhead_percentage"] != ""]
                cells.append("%+.1f%% (n=%d)" % (statistics.median(v), len(v)) if v else "—")
            if any(c != "—" for c in cells):
                out.append("| %s | %s | %s | %s |"
                           % (dblabel, schema_label, cells[0], cells[1]))
    return "\n".join(out)


def rewrite_plan(path, block):
    """Replace the text between the STATUS markers. Silent if absent."""
    B, E = "<!-- STATUS:BEGIN -->", "<!-- STATUS:END -->"
    if not path or not os.path.exists(path):
        return False
    s = open(path).read()
    if B not in s or E not in s:
        return False
    head, rest = s.split(B, 1)
    _, tail = rest.split(E, 1)
    open(path, "w").write(head + B + "\n" + block + "\n" + E + tail)
    return True


if __name__ == "__main__":
    sys.exit(main())
