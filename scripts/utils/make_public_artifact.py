#!/usr/bin/env python3
"""Build the depositable subset of this artifact, with no result attributable
to the licence-restricted system.

    python3 scripts/utils/make_public_artifact.py --out ../public-artifact

Why an export and not a public mirror
-------------------------------------
`anonymise.py` already reasoned this out: the raw files and the git history
carry the vendor's real name on every campaign, so making this repository
public is a disclosure in itself and no rename fixes a history. The answer is a
scrubbed export built from the working tree, which is what this writes.

What the licence actually forbids
---------------------------------
Section 6 of the SQL Server Developer Edition EULA forbids disclosing benchmark
*results* for that product without written approval. It does not forbid saying
the harness supports it. That distinction decides the whole shape of this
export, because the vendor's name is in `settings_sqlserver.py`, in twelve
per-vendor query modules, in `docker-compose.yml` and in the schema files, and
scrubbing those would ship a harness that cannot run the campaign it documents
while withholding nothing that the licence protects.

So: the code ships whole, and no number attributable to that system ships at
all.

What that costs
---------------
The paper reports the system as "Commercial System A". This export makes the
identification easy, because a reader sees which system's rows are withheld.
That inference is already available from the paper - Section 3 says two of the
four systems restrict publication and names Oracle as the other - and the
anonymisation exists to keep results from being *attributed* to the product,
not to keep the product secret. Withholding the numbers is the part that
matters and is the part this enforces.

Absence is not silent
---------------------
The 108 restricted cells stay in `all_results.csv` as rows. Their measurement
columns are emptied and their `status_note` says why. Dropping them would leave
a 324-row file whose shape a reader cannot check against the paper's 432, which
is the failure mode Section 4 of the paper calls the fifth one.

The gate
--------
`verify()` re-reads everything written and fails the build if any exported data
file carries a timing, ratio or percentage on a restricted row, or if a
restricted raw measurement file was copied. A withheld-by-convention export is
the kind of check this repository has been wrong about before (C43, C44), so it
runs over the whole export rather than over the part that suggested it.
"""
import argparse
import csv
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
sys.path.insert(0, HERE)

import anonymise                                              # noqa: E402

# Every name the restricted system appears under in a results file. The
# anonymised label is here on purpose. `overhead_summary.csv` and
# `overhead_by_query.csv` are written already anonymised, so a rule that
# matched only the vendor's real name would have shipped that system's
# per-cell overheads under the label the paper uses and reported a clean
# export, which is C43's shape exactly: a check that passes because it did not
# look where the answer was.
#
# Shipping them would in fact be arguable. The paper prints those same
# anonymised figures in Tables IV, VI and VII, so the licence position that
# permits the paper permits the CSV. This export does not take that position,
# for two reasons. The harness ships whole and names the vendor in a dozen
# paths, so an anonymised number sitting beside `settings_sqlserver.py` is
# anonymised in form only. And the choice is the authors' to make against
# their own licence rather than a default for a script to pick. Withholding is
# the option that cannot be wrong; MANIFEST.md records the other one so the
# decision stays visible.
RESTRICTED = {"SQL Server", "sqlserver", "Commercial System A"}

# Columns that carry a measurement of that system's performance. Emptied on a
# restricted row. `rows_returned` is deliberately not here: it is how many rows
# the query answered, not how fast, and the paper already publishes it for that
# system in the outlier table.
MEASUREMENT_COLUMNS = (
    "direct_sql_execution_s", "total_orm_execution_s",
    "overhead_ratio", "overhead_percentage", "overhead_abs_s",
    "sql_min_s", "sql_max_s", "sql_cv_pct",
    "orm_min_s", "orm_max_s", "orm_cv_pct", "repetitions_measured",
    "orm_median_qerror", "orm_max_qerror", "orm_underestimate_rate_pct",
    "sql_median_qerror", "sql_max_qerror", "sql_underestimate_rate_pct",
    "elapsed_s", "median_s", "qpm", "qps", "p50_ms", "p95_ms", "cv_pct",
    "committed", "aborted", "abort_pct", "overhead_pct",
    "ci_low_pct", "ci_high_pct",
)

WITHHELD_NOTE = ("withheld: section 6 of this system's developer licence "
                 "forbids disclosing benchmark results for it without the "
                 "vendor's written approval")

# Everything the harness needs to be run and read. Directories are copied
# whole; the excludes below apply inside them.
INCLUDE = (
    "django_app", "sqlalchemy_app", "scripts", "tests", "docs", "docker",
    "tpch_params.py", "tpch_paramsets.py", "tpch_domains.py", "tpcc_config.py",
    "settings_mysql.py", "settings_oracle.py", "settings_sqlserver.py",
    "odbc_driver.py", "mssql_decimal_fix.py",
    "docker-compose.yml", "requirements.txt", "requirements-sf1.txt",
    "requirements-lock.txt", "REPRODUCE.md", "PLAN.md",
    "SHAKEDOWN_PLAN.md", "LICENSE", "CITATION.cff",
    "run_reproducibility.sh", "setup_reproducibility.sh",
    "validate_reproducibility.sh",
)

# The pre-registered bounds live in the documents repository beside the paper,
# not in this one, and an export without them cannot show that section 8.1 was
# fixed before the pilot rather than after the data. Copied by absolute path
# because the two repositories are independent.
EXTERNAL = {"ANALYSIS_PLAN.md": os.path.join(REPO, os.pardir, os.pardir,
                                             "ANALYSIS_PLAN.md")}

# Session-continuity notes rather than artifact documentation. RESUME-HERE
# names both private repositories, records that they are private, and gives the
# host's sudo configuration and the Oracle account passwords; HANDOFF-PROMPT is
# a work order carrying an author's home directory. Neither documents the
# experiment, and both were written on the assumption that nobody outside would
# read them.
EXCLUDE_PATHS = {
    "docs/RESUME-HERE.md",
    "docs/superseded/HANDOFF-PROMPT.md",
}

# Strings that mean a file was written for the private repository rather than
# for a reader. `verify()` refuses to ship a file containing one, so the next
# working note that lands in docs/ fails the build instead of the review.
PRIVATE_MARKERS = (
    "NOPASSWD",
    "orm-overhead-thesis",
    "/Users/",
    "Both are private",
)

# Unfilled template text and a citation to a paper that does not exist. The
# repository's CITATION.cff was a template - "First Author", "yourusername" -
# whose preferred-citation named a VLDB Journal article, and three docs and two
# scripts repeated that title. None of it was ever true, and the first deposit
# published all of it before this check existed. A fabricated publication record
# naming real people is the one thing an artifact must not carry, so it fails
# the build rather than the review.
TEMPLATE_MARKERS = (
    "yourusername",
    "yourwebsite",
    "First Author",
    "Institution Name",
    "Framework Matters",
    "The VLDB Journal",
)

# Working notes, generated caches, the 21 GB of generated data, and the venv.
EXCLUDE_NAMES = {"__pycache__", ".pytest_cache", "venv", ".git", "_to_delete",
                 "data", "tpch-dbgen", "texput.log"}
EXCLUDE_SUFFIX = (".pyc", ".duckdb", ".log")


def is_restricted(row):
    for key in ("dbms", "system"):
        if row.get(key) in RESTRICTED:
            return True
    return False


def copy_tree(out):
    """The harness, whole. No results live under any of these paths."""
    copied = 0
    for name in INCLUDE:
        src = os.path.join(REPO, name)
        if not os.path.exists(src):
            print("  absent, skipped: %s" % name)
            continue
        dst = os.path.join(out, name)
        if os.path.isdir(src):
            shutil.copytree(
                src, dst, dirs_exist_ok=True,
                ignore=lambda _d, names: [
                    n for n in names
                    if n in EXCLUDE_NAMES or n.endswith(EXCLUDE_SUFFIX)])
            for rel in EXCLUDE_PATHS:
                gone = os.path.join(out, rel)
                if os.path.exists(gone):
                    os.remove(gone)
                    print("  withheld: %s" % rel)
            copied += sum(len(f) for _r, _d, f in os.walk(dst))
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    for name, src in EXTERNAL.items():
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, name))
            copied += 1
        else:
            print("  absent, skipped: %s" % name)
    return copied


def export_results_file(src, dst):
    """All 432 rows. The restricted 108 keep their identity and lose their
    numbers, so the grid a reader checks against the paper is still 432."""
    rows = list(csv.DictReader(open(src)))
    fields = rows[0].keys() if rows else []
    # Counted before anything is emptied: how many cells the campaign measured,
    # which is not 432 minus the restricted 108. Sixteen cells carry no figure
    # because they were censored at the ceiling or are inexpressible, and those
    # are the ones the paper counts out.
    measured = sum(1 for r in rows if r.get("overhead_percentage"))
    held = 0
    for r in rows:
        if not is_restricted(r):
            continue
        held += 1
        for col in MEASUREMENT_COLUMNS:
            if col in r:
                r[col] = ""
        r["dbms"] = anonymise.PUBLIC_NAME.get(r["dbms"], r["dbms"])
        for col in ("sql_status", "orm_status"):
            if col in r:
                r[col] = "restricted"
        if "status_note" in r:
            r["status_note"] = WITHHELD_NOTE
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields))
        w.writeheader()
        w.writerows(rows)
    return len(rows), held, measured


def export_derived_csv(src, dst):
    """The per-query and summary CSVs, restricted rows dropped rather than
    blanked: unlike the results file these carry no grid a reader counts."""
    rows = list(csv.DictReader(open(src)))
    keep = [r for r in rows if not is_restricted(r)]
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(keep)
    return len(rows), len(rows) - len(keep)


def export_measurements(src_dir, dst_dir):
    """Raw per-block timings for the three unrestricted systems."""
    os.makedirs(dst_dir, exist_ok=True)
    copied, withheld = [], []
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".csv"):
            continue
        (withheld if fn.startswith("sqlserver") else copied).append(fn)
        if not fn.startswith("sqlserver"):
            shutil.copy2(os.path.join(src_dir, fn), os.path.join(dst_dir, fn))
    with open(os.path.join(dst_dir, "WITHHELD.md"), "w") as fh:
        fh.write("# Files not in this export\n\n%s\n\n" % WITHHELD_NOTE)
        for fn in withheld:
            fh.write("- `%s`\n" % fn)
        fh.write("\nThe cells they hold are still listed in "
                 "`results/sf1/all_results.csv`, with no timing and the reason "
                 "in `status_note`, so the 432-cell grid the paper reports is "
                 "countable from this export.\n")
    return copied, withheld


def write_readme(out, stats):
    """The deposit's front page.

    The repository's own README is not shipped. It describes the scale factor 10
    campaign - 376 measured cells, Django 4.2, PostgreSQL 14 - which the scale
    factor 1 rerun superseded and which this export does not contain, since only
    `results/sf1` is here. As a landing page it would tell a reader the wrong
    thing about every number in the paper, so the deposit gets one written for
    it and the detail stays in MANIFEST.md, PLAN.md and docs/.
    """
    with open(os.path.join(out, "README.md"), "w") as fh:
        fh.write("""# ORM overhead: Django and SQLAlchemy against hand-written SQL

The artifact for *Two Workloads, Two Orders of Magnitude: ORM Overhead on Four
Database Systems*.

    4 database systems
      x 2 frameworks (Django 6.0.8, SQLAlchemy 2.0.52)
      x 2 schema configurations (indexed, non-indexed)
      x 27 workloads (TPC-H Q01-Q22 + TPC-C T1-T5) at scale factor 1
    = %(rows)d cells, %(measured)d measured on both access paths

Every cell is emitted whether or not it was measured. One that was not carries a
status and a reason in words, because a gap and a zero that look alike is the
defect this harness was rebuilt to remove.

## Start here

- `MANIFEST.md` - what this export contains, what it withholds and why, and what
  running the analysis over it reproduces.
- `docs/CORRECTIONS.md` - the %(defects)d defects found while building,
  validating and reviewing the harness. This is the register the paper's
  Section 4 groups into six failure modes.
- `ANALYSIS_PLAN.md` - the resolution bounds, fixed before the pilot ran. Four
  campaigns fail them, which is only meaningful because they were fixed first.
- `PLAN.md` - the campaign as executed.

## Reproducing

    python3 -m venv venv && source venv/bin/activate
    pip install -r requirements-sf1.txt
    export PYTHONPATH=. TPCH_SF=1

    python3 scripts/4-analysis/sf1_analysis.py --scale 1
    python3 scripts/4-analysis/sf1_tables.py   --scale 1 --outdir tables
    python3 scripts/4-analysis/sf1_referee.py  --scale 1

The last of those prints the working behind the paper's prose claims: the
pre-registered bound on each campaign, whether the two frameworks' baselines
agree, the ceiling each campaign's rows record, what excluding Query 18 buys,
the clustered significance, the informative censoring, and the per-statement
figures.

`REPRODUCE.md` covers re-running the measurements, which needs the four engines
loaded under the envelope `docs/ENVIRONMENT.md` describes.

## One system's results are withheld

A vendor's developer licence forbids disclosing benchmark results for its system
without written approval. Its %(held)d cells are here as rows with empty
measurement columns and the reason in `status_note`, and its raw timing files
are not. `MANIFEST.md` gives the full account, including what the analysis
returns without them and why that number is already in the paper.

## Licence

MIT, see `LICENSE`. The TPC-H and TPC-C derived workloads are covered by the
TPC's fair-use policy: neither is a TPC benchmark and neither is comparable to
published TPC results.
""" % stats)


def write_manifest(out, stats):
    """What is here, what is not, and the choice a reader should be able to see.

    An export that withholds something without saying so is the defect this
    repository has recorded most often. This file is the export's own
    status_note.
    """
    with open(os.path.join(out, "MANIFEST.md"), "w") as fh:
        fh.write("""# What is in this export, and what is not

This is the depositable subset of the artifact behind *Two Workloads, Two
Orders of Magnitude: ORM Overhead on Four Database Systems*. It is an export
rather than a mirror of the working repository, because that repository's files
and its git history name a system whose licence forbids disclosing benchmark
results for it.

## Here

- The harness: both frameworks' implementations of all 27 queries and
  transactions, the per-vendor overrides, the schema and load scripts, the
  block protocol, and the pre-flight checks.
- The five validation checks and the test suite.
- Every analysis script that produces a table or a figure in the paper.
- `docs/CORRECTIONS.md`, the register of %(defects)d defects.
- `ANALYSIS_PLAN.md`, which fixes the resolution bounds the paper reports four
  campaigns as failing. It is dated before the pilot; that is the whole reason
  those bounds could fail.
- `results/sf1/all_results.csv`: all %(rows)d cells.
- Raw per-block timings for PostgreSQL, MySQL and Oracle: %(measfiles)d files.

## Not here

%(held)d of the %(rows)d cells belong to one system. Section 6 of that system's
developer licence forbids disclosing benchmark results for it without the
vendor's written approval, so this export carries no timing, ratio or
percentage for it. The cells remain in `all_results.csv` as rows, with empty
measurement columns and the reason in `status_note`, so the grid stays
countable at %(rows)d rather than silently becoming %(kept)d.
`results/sf1/measurements/WITHHELD.md` lists the raw files that are absent.

The harness itself ships whole and names that vendor, because the licence
restricts disclosing results and not disclosing that the code supports it. A
reader can therefore tell which system is withheld. The paper says as much: two
of its four systems restrict publication and it names the other one. The
anonymisation keeps results from being attributed to the product, which is what
withholding the numbers enforces.

## What this subset reproduces

Running the analysis over this export does not return the paper's headline
numbers, and it should not. Six of the eight campaigns are here, so the pooled
analytical medians come back as +0.72%% for Django over 123 cells and +0.30%%
for SQLAlchemy over 127, against the paper's +1.13%% and +0.67%% over 165 and
171.

Those two figures are already in the paper. Table VII's sensitivity analysis
reports the pooled medians with Commercial System A removed, and the row reads
+0.72%% and +0.30%%. So this export reproduces a published row exactly, and the
difference between it and the headline is the quantity that table exists to
report rather than a discrepancy. The transactional medians come back as
+88.3%% and +71.2%% over 30 cells against +90.5%% and +69.2%% over 40.

## The choice this export made, so it can be revisited

The paper prints that system's overheads under its anonymous label in three
tables and one figure, and a journal will publish them. By that reading the
already-anonymised `results/sf1/analysis/*.csv` could ship too, and %(dropped)d
more rows would be here.

This export withholds them. Beside a harness that names the vendor in a dozen
paths, an anonymised number is anonymised in form only, and the reading is the
authors' to make against their own licence rather than a script's to assume.
Reversing it is one line: drop the anonymous label from `RESTRICTED` in
`scripts/utils/make_public_artifact.py` and rebuild.

## Rebuilding this

    python3 scripts/utils/make_public_artifact.py --out <dir>

The script re-reads everything it wrote and fails if any exported CSV carries a
measurement on a restricted row, over the whole export rather than the part
that suggested the check.
""" % stats)


def verify(out):
    """Re-read the export and refuse to ship a restricted measurement.

    Over every CSV, not over the ones that motivated the check.
    """
    problems = []
    for root, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_NAMES]
        for fn in files:
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, out)
            if fn.startswith("sqlserver") and fn.endswith(".csv"):
                problems.append("restricted raw file shipped: %s" % rel)
                continue
            # This file is the one place the markers appear as data rather
            # than as a leak, because listing them is its job. Exempted by
            # exact path so the exemption cannot widen.
            if rel == os.path.join("scripts", "utils",
                                   "make_public_artifact.py"):
                continue
            if fn.endswith((".md", ".py", ".sh", ".yml", ".cff", ".txt")):
                try:
                    body = open(path, encoding="utf-8", errors="ignore").read()
                except OSError:
                    body = ""
                for marker in PRIVATE_MARKERS:
                    if marker in body:
                        problems.append("%s contains %r, which marks a file "
                                        "written for the private repository"
                                        % (rel, marker))
                for marker in TEMPLATE_MARKERS:
                    if marker in body:
                        problems.append("%s contains %r: unfilled template text "
                                        "or a citation to a paper that does not "
                                        "exist" % (rel, marker))
            if not fn.endswith(".csv"):
                continue
            try:
                rows = list(csv.DictReader(open(path)))
            except (UnicodeDecodeError, csv.Error):
                continue
            for i, r in enumerate(rows, 2):
                if not is_restricted(r) and r.get("dbms") != "Commercial System A":
                    continue
                for col in MEASUREMENT_COLUMNS:
                    if r.get(col):
                        problems.append("%s:%d %s=%s on a restricted row"
                                        % (rel, i, col, r[col]))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    if out.startswith(REPO + os.sep) or out == REPO:
        sys.exit("refusing to write the export inside the repository: %s" % out)
    if os.path.exists(out) and os.listdir(out) and not args.force:
        sys.exit("%s exists and is not empty; pass --force" % out)
    os.makedirs(out, exist_ok=True)

    print("export -> %s" % out)
    n = copy_tree(out)
    print("  harness: %d files" % n)

    total, held, measured = export_results_file(
        os.path.join(REPO, "results", "sf1", "all_results.csv"),
        os.path.join(out, "results", "sf1", "all_results.csv"))
    print("  all_results.csv: %d rows, %d with measurements withheld"
          % (total, held))

    dropped_derived = 0
    src_an = os.path.join(REPO, "results", "sf1", "analysis")
    for fn in sorted(os.listdir(src_an)) if os.path.isdir(src_an) else []:
        if fn.endswith(".csv"):
            t, d = export_derived_csv(os.path.join(src_an, fn),
                                      os.path.join(out, "results", "sf1",
                                                   "analysis", fn))
            dropped_derived += d
            print("  analysis/%s: %d rows, %d dropped" % (fn, t, d))

    copied, withheld = export_measurements(
        os.path.join(REPO, "results", "sf1", "measurements"),
        os.path.join(out, "results", "sf1", "measurements"))
    print("  measurements: %d files, %d withheld" % (len(copied), len(withheld)))

    for fn in ("README.md",):
        src = os.path.join(REPO, "results", "sf1", fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, "results", "sf1", fn))

    stats = dict(
        rows=total, held=held, kept=total - held, measfiles=len(copied),
        dropped=dropped_derived,
        defects=sum(1 for l in open(os.path.join(REPO, "docs",
                                                 "CORRECTIONS.md"))
                    if l.startswith("## C")))
    stats["measured"] = measured
    write_readme(out, stats)
    write_manifest(out, stats)

    problems = verify(out)
    if problems:
        print("\nGATE FAILED, %d problems:" % len(problems), file=sys.stderr)
        for p in problems[:20]:
            print("  " + p, file=sys.stderr)
        sys.exit(1)
    print("\ngate passed: no restricted measurement in the export")


if __name__ == "__main__":
    main()
