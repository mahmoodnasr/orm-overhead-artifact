"""Verify and reproduce revision campaign rc20261008 from its released records.

No database is contacted and nothing under campaign/ is written: every rebuild
goes to outputs/campaign/ and is compared with the released reference outputs.
The campaign's own scripts in campaign/rc20261008/code/ do the arithmetic; this
module only selects their inputs and checks their outputs.
"""

from __future__ import annotations

from collections import Counter
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaign"
RC = CAMPAIGN / "rc20261008"
CODE = RC / "code"

# The analysis runs the manuscript reports. Other runs were not released.
FINAL = {
    "A-sf1": "analysis/run-20261011T2000/A-sf1",
    "D-sf2": "analysis/run-20261011T0400/D-sf2",
    "E-client": "analysis/run-20261011T2215/E-client",
}
ALL_PHASES = "analysis/run-20261011T2251/all-phases"
# The first separate-client run of this configuration is kept but superseded:
# it followed a long indexed workload on the same engine instance. The analysis
# uses the rerun on a freshly started engine.
SUPERSEDED = {
    ("E-client", "commercial_a", "non-indexed"): "commercial_a-non-indexed-r2"
}

EXPECTED_STATUSES = {
    ("A", "measured"): 332,
    ("A", "censored"): 12,
    ("A", "not_expressible"): 4,
    ("A", "numeric_mismatch"): 4,
    ("B", "lower_bound"): 2,
    ("C", "measured"): 64,
    ("C", "measured_with_rejections"): 16,
    ("D", "measured"): 53,
    ("D", "partial"): 14,
    ("D", "censored"): 3,
    ("D", "skipped_censored_on_host"): 10,
    ("E", "measured"): 70,
    ("E", "skipped_censored_on_host"): 10,
    ("F", "measured"): 41,
    ("F", "censored"): 1,
    ("G", "measured"): 70,
    ("G", "skipped_censored_on_host"): 10,
    ("V", "validated"): 8,
    ("V", "validated_by_twin"): 4,
}
# Phases whose runs read the analytical source snapshot (C uses its own pins).
SOURCE_BOUND = (
    "A-sf1",
    "B-censored",
    "D-sf2",
    "E-client",
    "F-fourpath",
    "G-mac-server",
    "V-censored",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rc_common():
    sys.path.insert(0, str(CODE))
    import rc_common  # noqa: PLC0415

    return rc_common


# ---------------------------------------------------------------- comparison
def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text and "e" not in text.lower() else 0


def same_value(expected: str, actual: str) -> bool:
    """Equal text, or numbers equal within platform math-library noise.

    A value printed with d decimals may also move by one unit in its last
    place: a last-bit difference in log/exp can cross a rounding boundary.
    """
    if expected == actual:
        return True
    try:
        a, b = float(expected), float(actual)
    except ValueError:
        return False
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    d = _decimals(expected)
    unit = 10.0**-d if d and d == _decimals(actual) else 0.0
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=max(1e-12, unit * 1.000001))


def same_json(expected, actual) -> bool:
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and expected.keys() == actual.keys()
            and all(same_json(expected[k], actual[k]) for k in expected)
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        if all(isinstance(v, str) for v in expected + actual):
            # Sorted label lists: the release relabels one system, which moves
            # its cells within an alphabetical order without changing a value.
            return sorted(expected) == sorted(actual)
        return all(same_json(a, b) for a, b in zip(expected, actual))
    if isinstance(expected, float) or isinstance(actual, float):
        return (
            isinstance(expected, (int, float))
            and isinstance(actual, (int, float))
            and math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-12)
        )
    return expected == actual


def same_csv(expected: Path, actual: Path, *, any_order: bool = False) -> bool:
    with expected.open(newline="", encoding="utf-8") as fh:
        left = list(csv.reader(fh))
    with actual.open(newline="", encoding="utf-8") as fh:
        right = list(csv.reader(fh))
    if left == right:
        return True  # includes two empty files
    if len(left) != len(right) or not left or left[0] != right[0]:
        return False
    body_l, body_r = left[1:], right[1:]
    if any_order:
        body_l, body_r = sorted(body_l), sorted(body_r)
    return all(
        len(x) == len(y) and all(same_value(a, b) for a, b in zip(x, y))
        for x, y in zip(body_l, body_r)
    )


def load_json(path: Path, drop=()) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    for key in drop:
        value.pop(key, None)
    return value


# -------------------------------------------------------------------- verify
def verify() -> dict:
    """Checksums, coverage, evidence paths and source bindings. Standard library only."""
    sums = {}
    for line in (CAMPAIGN / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        sums[rel] = digest
    # README.md is written after the build and is covered by MANIFEST.json.
    present = {
        p.relative_to(CAMPAIGN).as_posix()
        for p in CAMPAIGN.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    } - {"SHA256SUMS", "README.md"}
    require(present == set(sums), "campaign/ differs from campaign/SHA256SUMS")
    for rel, digest in sums.items():
        path = CAMPAIGN / rel
        require(not path.is_symlink(), f"Symlink in campaign/: {rel}")
        require(sha256(path) == digest, f"Checksum mismatch: campaign/{rel}")

    withheld = json.loads((CAMPAIGN / "WITHHELD.json").read_text(encoding="utf-8"))
    for entry in withheld["files"]:
        require(
            not (ROOT / entry["path"]).exists(),
            f"Withheld file present: {entry['path']}",
        )
    provenance = json.loads(
        (CAMPAIGN / "release-provenance.json").read_text(encoding="utf-8")
    )
    for entry in provenance["changed_files"]:
        require(
            sha256(ROOT / entry["path"]) == entry["sha256"],
            f"Provenance mismatch: {entry['path']}",
        )

    with (RC / "results-all-phases.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    statuses = Counter((r["phase"], r["status"]) for r in rows)
    require(len(rows) == 728, f"Expected 728 campaign rows, found {len(rows)}")
    require(
        dict(statuses) == EXPECTED_STATUSES,
        f"Campaign statuses differ: {dict(statuses)}",
    )
    require(all(r["status_note"] for r in rows), "A campaign row has no reason")
    for r in rows:
        if r["evidence"]:
            target = (RC / r["evidence"]).resolve()
            require(
                target.is_relative_to(CAMPAIGN) and target.exists(),
                f"Missing evidence: {r['evidence']}",
            )

    # The source the runs hashed is released byte for byte. Each analytical
    # inventory lists these 109 hashes, and every record carries their digest
    # as source_sha256. The paper snapshot's 103 files are a subset.
    C = rc_common()
    measured = CAMPAIGN / "source" / "measured"
    hashes = {
        p.relative_to(measured).as_posix(): sha256(p)
        for p in sorted(measured.rglob("*"))
        if p.is_file()
    }
    pins = json.loads(
        (RC / "paper-snapshot-source-hashes.json").read_text(encoding="utf-8")
    )
    require(
        all(hashes.get(rel) == digest for rel, digest in pins.items()),
        "Paper snapshot source differs",
    )
    patched = {
        p.relative_to(CAMPAIGN / "source" / "tpcc-run").as_posix(): sha256(p)
        for p in sorted((CAMPAIGN / "source" / "tpcc-run").rglob("*"))
        if p.is_file()
    }
    tpcc = json.loads(
        (RC / "protocols/rc20261008-C-v1.json").read_text(encoding="utf-8")
    )["tpcc_source_hashes"]
    require(
        tpcc == {rel: patched.get(rel, hashes.get(rel)) for rel in tpcc},
        "Transaction source differs from protocol C-v1",
    )
    source_id = C.digest(hashes)
    inventories = Counter()
    for phase in (
        *SOURCE_BOUND,
        "C-tpcc",
        "pilot",
        "pilot-F",
        "pilot-F2",
        "pilot-tpcc",
        "pilot-tpcc-Cv1",
    ):
        for inv in (RC / phase).rglob("inventory-before-*.json"):
            listed = json.loads(inv.read_text(encoding="utf-8")).get("source_hashes")
            if listed is None:
                continue
            where = inv.relative_to(ROOT)
            if listed == hashes:
                inventories["analytical source"] += 1
            elif listed == tpcc:
                inventories["transaction source, corrected"] += 1
            else:
                require(
                    set(listed) == set(tpcc)
                    and all(
                        v in (hashes.get(k), patched.get(k)) for k, v in listed.items()
                    ),
                    f"Inventory lists source that is not released: {where}",
                )
                inventories["transaction source, before correction"] += 1
    for phase in SOURCE_BOUND:
        for record in sorted((RC / phase).rglob("timed-*.json.gz"))[::97]:
            stamped = json.loads(gzip.decompress(record.read_bytes())).get(
                "source_sha256"
            )
            require(
                stamped in (None, source_id),
                f"Record bound to unreleased source: {record.relative_to(ROOT)}",
            )
    return {
        "campaign_files": len(sums),
        "campaign_rows": len(rows),
        "campaign_statuses": {f"{p}/{s}": n for (p, s), n in sorted(statuses.items())},
        "withheld_files": len(withheld["files"]),
        "relabelled_or_redacted_files": len(provenance["changed_files"]),
        "measured_source_files": len(hashes),
        "measured_source_id": source_id,
        "inventories_bound_to_source": dict(inventories),
    }


# ----------------------------------------------------------------- reproduce
def _run(args: list, env: dict, log: Path) -> None:
    result = subprocess.run(
        [sys.executable, *map(str, args)],
        cwd=RC,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    with log.open("a", encoding="utf-8") as fh:
        fh.write("$ " + " ".join(map(str, args)) + "\n" + result.stdout + "\n")
    require(result.returncode == 0, f"{Path(args[0]).name} failed; see {log}")


def _ordered_runs(phase: str) -> list:
    """Run directories in the order of the original invocation.

    The bootstrap's resampling draws from queries in first-seen order, so the
    order of the input directories is part of the computation.
    """
    with (RC / FINAL[phase] / "coverage.csv").open(newline="", encoding="utf-8") as fh:
        order = list(
            dict.fromkeys((r["dbms"], r["schema"]) for r in csv.DictReader(fh))
        )
    return [
        RC / phase / SUPERSEDED.get((phase, db, schema), f"{db}-{schema}")
        for db, schema in order
    ]


def revalidate_decisions(phase: str) -> int:
    """Re-check every accepted pair from its stored full results."""
    C = rc_common()
    accepted = 0
    for run in _ordered_runs(phase):
        for path in sorted(run.glob("q*/b*/decision.json")):
            decision = C.load(path)
            for fw, verdict in decision["frameworks"].items():
                if not verdict.get("accepted"):
                    continue
                sql = C.load(path.parent / decision["timed_records"][fw + "/sql"])
                orm = C.load(path.parent / decision["timed_records"][fw + "/orm"])
                result = C.compare(
                    decision["query"],
                    sql["rows"],
                    orm["rows"],
                    sql.get("output_columns"),
                    orm.get("output_columns"),
                    policy=decision.get("policy") or C.POLICY_V1,
                )
                where = path.relative_to(ROOT)
                require(
                    result["accepted"],
                    f"Accepted pair no longer compares equal: {where} {fw}",
                )
                require(
                    result["classification"] == verdict["classification"],
                    f"Classification differs: {where} {fw}",
                )
                require(
                    C.orm_path_check(orm, sql)["passed"],
                    f"ORM path check fails: {where} {fw}",
                )
                for record in (sql, orm):
                    require(
                        C.digest(record["rows"]) == record["result_sha256"],
                        f"Result hash differs: {where} {fw}",
                    )
                accepted += 1
    return accepted


def reproduce(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    log = output / "reproduction.log"
    log.write_text("", encoding="utf-8")
    env = dict(os.environ, RC_OUT=str(output), PYTHONDONTWRITEBYTECODE="1")
    checked = []

    _run([CODE / "rc_collect.py"], env, log)
    require(
        same_csv(RC / "results-all-phases.csv", output / "results-all-phases.csv"),
        "results-all-phases.csv differs",
    )
    require(
        same_json(
            load_json(RC / "results-all-phases-summary.json", ["generated_utc"]),
            load_json(output / "results-all-phases-summary.json", ["generated_utc"]),
        ),
        "results-all-phases-summary.json differs",
    )
    checked += ["results-all-phases.csv", "results-all-phases-summary.json"]

    accepted = {}
    for phase, reference in FINAL.items():
        dest = output / phase
        _run([CODE / "rc_analyze.py", *_ordered_runs(phase), "--out", dest], env, log)
        for name in ("summary.json", "sensitivity.json"):
            require(
                same_json(load_json(RC / reference / name), load_json(dest / name)),
                f"{phase}/{name} differs",
            )
        for name in ("cells.csv", "coverage.csv", "path_cvs.csv", "censored.csv"):
            require(
                same_csv(RC / reference / name, dest / name, any_order=True),
                f"{phase}/{name} differs",
            )
        checked += [
            f"{reference}/{n}"
            for n in (
                "summary.json",
                "sensitivity.json",
                "cells.csv",
                "coverage.csv",
                "path_cvs.csv",
                "censored.csv",
            )
        ]
        accepted[phase] = revalidate_decisions(phase)

    dest = output / "all-phases"
    _run(
        [
            CODE / "rc_summary.py",
            "--a",
            output / "A-sf1",
            "--d",
            output / "D-sf2",
            "--e",
            output / "E-client",
            "--out",
            dest,
        ],
        env,
        log,
    )
    require(
        same_json(
            load_json(RC / ALL_PHASES / "summary.json", ["generated", "inputs"]),
            load_json(dest / "summary.json", ["generated", "inputs"]),
        ),
        "all-phases/summary.json differs",
    )
    for name in ("F-decomposition.csv", "C-path-cvs.csv"):
        require(
            same_csv(RC / ALL_PHASES / name, dest / name, any_order=True),
            f"all-phases/{name} differs",
        )
    checked += [
        f"{ALL_PHASES}/{n}"
        for n in ("summary.json", "F-decomposition.csv", "C-path-cvs.csv")
    ]
    return {
        "campaign_outputs_matched": checked,
        "campaign_accepted_pairs_revalidated": accepted,
    }
