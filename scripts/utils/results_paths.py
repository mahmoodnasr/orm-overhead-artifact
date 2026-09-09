"""Where a campaign's results go, decided once, from the scale factor.

The SF10 campaign is complete and its files are frozen. The SF1 rerun produces
a second, independent set. The two must not share a file: measurement rows are
keyed by (dbms, schema_config, query_id, framework, path) and that key does not
contain the scale factor, so an SF1 row written into the SF10 directory
*replaces* the SF10 row for that cell in every rebuild afterwards, silently and
irreversibly. `make_all_results.py::load_measurements` already carries a
comment about this and a partial guard; the guard only works if the rows carry
a scale_factor, and the SF10 measurement files predate that column and do not.

So the separation is by path, and it is computed here rather than written into
each of the four campaign scripts and the two analysis entry points. Six
instances of "one decision recorded in two places, copies drifting" have been
found in this repository (C9 and the five in the phase 4 smoke test); a seventh
was not needed.

    SF10 (frozen)              SF1 and any other scale factor
    -------------------------  ---------------------------------
    results/all_results.csv    results/sf1/all_results.csv
    results/corrected/         results/sf1/
      measurements/              measurements/
      qerror/                    qerror/

SF10 keeps its historical layout exactly, including the `corrected/` level,
because renaming it would invalidate every path printed in the paper, in
`docs/CORRECTIONS.md` and in the plans. New scale factors get the simpler tree.
"""

import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# The scale factor the SF10 campaign ran at, and the only one whose files use
# the legacy layout.
LEGACY_SF = "10"


def scale_factor(explicit=None):
    """The campaign's scale factor as a string.

    TPCH_SF is already required for correctness — defect C6, where Q11's
    FRACTION is 0.0001/SF and a value held at the SF1 constant makes Q11 return
    zero rows at SF10 while still scanning and sorting, recording a plausible
    time for a query that is not Q11. Reading the same variable here means the
    results cannot land in a directory that disagrees with the parameters they
    were measured with.
    """
    sf = str(
        explicit if explicit not in (None, "") else os.environ.get("TPCH_SF", "")
    ).strip()
    if not sf:
        raise SystemExit(
            "TPCH_SF is not set. It selects both the query parameters (C6) and "
            "the results directory, so there is no safe default: guessing 10 "
            "would write SF1 measurements over the completed SF10 campaign."
        )
    return sf


def is_legacy(sf):
    return str(sf) == LEGACY_SF


def results_root(sf):
    """The directory holding everything produced at this scale factor."""
    return REPO if is_legacy(sf) else os.path.join(REPO, "results", "sf%s" % sf)


def measurements_dir(sf):
    if is_legacy(sf):
        return os.path.join(REPO, "results", "corrected", "measurements")
    return os.path.join(results_root(sf), "measurements")


def qerror_dir(sf):
    """The directory tree searched for qerror_by_query.csv."""
    if is_legacy(sf):
        return os.path.join(REPO, "results", "corrected")
    return results_root(sf)


def validation_logs_dir(sf):
    if is_legacy(sf):
        return os.path.join(REPO, "results", "corrected")
    return results_root(sf)


def all_results_path(sf):
    if is_legacy(sf):
        return os.path.join(REPO, "results", "all_results.csv")
    return os.path.join(results_root(sf), "all_results.csv")


def plan_path(sf):
    """The file whose generated status block this campaign owns, or "".

    PLAN.md's block describes the SF10 campaign. An SF1 rebuild must not
    rewrite it — the two campaigns have different grids and different counts,
    and a block that silently switched to describing the other one is the
    reporting equivalent of writing SF1 rows into the SF10 measurements.
    """
    return os.path.join(REPO, "PLAN.md") if is_legacy(sf) else ""


def campaign_id(sf, default_legacy="sf10-2026-07"):
    return default_legacy if is_legacy(sf) else "sf%s" % sf
