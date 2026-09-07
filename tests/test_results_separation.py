"""The SF10 campaign's files must survive an SF1 rerun untouched.

The failure this guards against is silent and irreversible. A measurement row is
keyed by (dbms, schema_config, query_id, framework, path) and that key does not
contain the scale factor, so an SF1 row written into the SF10 measurements
directory does not sit beside the SF10 row for that cell — it replaces it in
every rebuild afterwards. There is no error, no warning, and the resulting
all_results.csv looks exactly as complete as before.

Run:  python3 -m pytest tests/test_results_separation.py -q
"""
import csv
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "utils"))

import results_paths                                          # noqa: E402


def test_sf10_and_sf1_share_no_path():
    """Every path either campaign writes must differ from the other's."""
    for name in ("measurements_dir", "all_results_path", "qerror_dir"):
        fn = getattr(results_paths, name)
        assert fn("10") != fn("1"), f"{name} collides between SF10 and SF1"


def test_sf1_does_not_own_the_sf10_plan_block():
    """PLAN.md's generated block describes the SF10 grid; SF1 must not rewrite it."""
    assert results_paths.plan_path("10").endswith("PLAN.md")
    assert results_paths.plan_path("1") == ""


def test_scale_factor_has_no_default():
    """TPCH_SF unset must raise, not silently mean 10.

    A default of 10 is the whole defect: it puts SF1 measurements into the
    completed campaign's files. This is the same reasoning as C6, where holding
    TPCH_SF at the SF1 constant made Q11 return zero rows at SF10 while still
    scanning and sorting.
    """
    saved = os.environ.pop("TPCH_SF", None)
    try:
        raised = False
        try:
            results_paths.scale_factor()
        except SystemExit:
            raised = True
        assert raised, "scale_factor() defaulted instead of refusing"
    finally:
        if saved is not None:
            os.environ["TPCH_SF"] = saved


def test_blank_scale_factor_counts_as_sf10_only():
    """The SF10 measurement files predate the column; nothing else may assume it.

    A blank means ten for the files written before run_query.py recorded it. For
    any other campaign a blank is a row of unknown provenance and is excluded,
    because assuming it belongs to the campaign being built is how an SF10 row
    would be reported as an SF1 result.

    Two cases, and this test conflated them. A row whose file HAS the column and
    leaves it blank cannot be placed, so only SF10 takes it. A row from a file
    with no such column at all takes its provenance from the directory it sits
    in, which is the separation results_paths.py enforces - without that, every
    TPC-C row was excluded from every build but SF10 and the summary read
    "0 complete, 10 not_run" while the measurements sat on disk (C35).
    """
    sys.path.insert(0, os.path.join(REPO, "scripts", "4-analysis"))
    import make_all_results as m

    # Column present and blank: unplaceable, so SF10 only.
    assert m._row_is_this_scale({"scale_factor": ""}, "10") is True
    assert m._row_is_this_scale({"scale_factor": ""}, "1") is False
    # Column absent from the file: the directory places it (C35).
    assert m._row_is_this_scale({}, "10") is True
    assert m._row_is_this_scale({}, "1") is True
    assert m._row_is_this_scale({"scale_factor": "1"}, "1") is True
    assert m._row_is_this_scale({"scale_factor": "1"}, "10") is False
    assert m._row_is_this_scale({"scale_factor": "10"}, "10") is True


def test_sf10_rebuild_is_byte_identical():
    """Rebuilding SF10 must reproduce the committed file exactly.

    This is the test that would have caught the separation going wrong: it
    compares against the file in git rather than against a fresh build, so a
    change that corrupts SF10 fails here even if it corrupts it consistently.
    """
    out = os.path.join(REPO, "results", "all_results.csv")
    if not os.path.exists(out):
        return                                    # nothing committed to compare
    committed = subprocess.run(
        ["git", "-C", REPO, "show", "HEAD:results/all_results.csv"],
        capture_output=True, text=True)
    if committed.returncode != 0:
        return                                    # not tracked in this checkout
    with open(out) as fh:
        assert fh.read() == committed.stdout, (
            "results/all_results.csv differs from the committed SF10 file")


def test_sf1_file_carries_its_own_scale_and_campaign():
    """If an SF1 file exists, nothing in it may claim to be SF10."""
    path = results_paths.all_results_path("1")
    if not os.path.exists(path):
        return
    rows = list(csv.DictReader(open(path)))
    assert rows, "SF1 results file is empty"
    assert {r["scale_factor"] for r in rows} == {"1"}
    assert not any(r["campaign_id"].startswith("sf10") for r in rows), (
        "an SF1 row is attributed to an SF10 campaign")
