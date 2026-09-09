#!/usr/bin/env python3
"""Verify the public release and reproduce all four systems without a database."""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SYSTEMS = ("postgresql", "mysql", "oracle", "commercial_a")
SCHEMAS = ("indexed", "non-indexed")
FRAMEWORKS = ("django", "sqlalchemy")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalized(value: str) -> str:
    key = value.lower().replace(" ", "")
    return "commercial_a" if key == "commercialsystema" else key


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal_numbers(expected, actual) -> bool:
    """Allow only insignificant floating-point differences across math libraries."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and expected.keys() == actual.keys()
            and all(
                equal_numbers(value, actual[key]) for key, value in expected.items()
            )
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(equal_numbers(a, b) for a, b in zip(expected, actual))
        )
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        return (
            math.isfinite(expected)
            and math.isfinite(actual)
            and math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-12)
        )
    return expected == actual


def reference_matches(expected: Path, actual: Path) -> bool:
    if expected.read_bytes() == actual.read_bytes():
        return True
    if expected.suffix == ".json":
        return equal_numbers(
            json.loads(expected.read_text()), json.loads(actual.read_text())
        )
    if expected.suffix == ".csv":
        with expected.open(newline="") as handle:
            left = list(csv.reader(handle))
        with actual.open(newline="") as handle:
            right = list(csv.reader(handle))
        if len(left) != len(right) or not left or left[0] != right[0]:
            return False
        for arow, brow in zip(left[1:], right[1:]):
            if len(arow) != len(brow):
                return False
            for a, b in zip(arow, brow):
                if a == b:
                    continue
                try:
                    if not equal_numbers(float(a), float(b)):
                        return False
                except ValueError:
                    return False
        return True
    return False


def verify() -> dict:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    require(manifest["algorithm"] == "sha256", "Unsupported manifest algorithm")
    for rel, expected in manifest["files"].items():
        path = ROOT / rel
        require(
            not path.is_symlink() and path.is_file(), f"Missing regular file: {rel}"
        )
        require(path.resolve().is_relative_to(ROOT), f"Invalid manifest path: {rel}")
        require(
            file_hash(path) == expected, f"File differs from the review package: {rel}"
        )
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=rel)

    data = ROOT / "results/sf1/measurements"
    expected_files = set()
    for db in SYSTEMS:
        for schema in SCHEMAS:
            suffix = schema.replace("-", "_")
            expected_files.update(
                {
                    f"{db}_{suffix}.csv",
                    f"{db}_tpcc_{suffix}.csv",
                    f"{db}_tpcc_throughput_{suffix}.csv",
                }
            )
    require(
        {p.name for p in data.iterdir()} == expected_files,
        "Unexpected or missing data files",
    )
    require(
        {"results/sf1/all_results.csv"}
        | {"results/sf1/measurements/" + name for name in expected_files}
        <= manifest["files"].keys(),
        "Every measurement input must be included in the release manifest",
    )
    coverage = read_csv(ROOT / "results/sf1/all_results.csv")
    keys = {
        (
            normalized(r["dbms"]),
            r["schema_config"].lower(),
            r["query_id"],
            r["orm"].lower(),
        )
        for r in coverage
    }
    planned = {
        (db, sc, q, fw)
        for db in SYSTEMS
        for sc in SCHEMAS
        for q in [*(f"Q{i:02d}" for i in range(1, 23)), *(f"T{i}" for i in range(1, 6))]
        for fw in FRAMEWORKS
    }
    require(
        len(coverage) == 432 and keys == planned,
        "Coverage is not the unique 432-cell design",
    )
    require(
        {r["scale_factor"] for r in coverage} == {"1"}, "Coverage mixes scale factors"
    )
    statuses = Counter(r["orm_status"] for r in coverage)
    require(
        statuses == {"ok": 416, "timeout": 12, "not_expressible": 4},
        f"Coverage differs from the complete four-system design: {dict(statuses)}",
    )

    commercial = [row for row in coverage if normalized(row["dbms"]) == "commercial_a"]
    require(
        len(commercial) == 108, "Expected all 108 Commercial System A coverage rows"
    )
    require(
        all(row["dbms"] == "Commercial System A" for row in commercial),
        "Expected anonymous database label",
    )
    for row in coverage:
        if row["orm_status"] == "ok":
            require(
                all(
                    row[field]
                    for field in (
                        "direct_sql_execution_s",
                        "total_orm_execution_s",
                        "overhead_percentage",
                    )
                ),
                "Measured coverage row is missing measurement values",
            )

    blocks = defaultdict(dict)
    analytical_rows = 0
    for db in SYSTEMS:
        for schema in SCHEMAS:
            for row in read_csv(data / f"{db}_{schema.replace('-', '_')}.csv"):
                analytical_rows += 1
                require(
                    row["scale_factor"] == "1", "Analytical input mixes scale factors"
                )
                require(
                    (row["dbms"], row["schema_config"]) == (db, schema),
                    "Mislabeled input file",
                )
                if row["status"] != "ok" or row["is_warmup"] != "0":
                    continue
                key = (db, schema, row["query_id"], row["framework"], int(row["block"]))
                require(row["path"] in {"orm", "sql"}, "Unknown access path")
                require(
                    row["path"] not in blocks[key], f"Duplicate analytical path: {key}"
                )
                elapsed = float(row["elapsed_s"])
                require(
                    math.isfinite(elapsed) and elapsed > 0,
                    f"Invalid elapsed time: {key}",
                )
                blocks[key][row["path"]] = (elapsed, row["param_set_id"])
    paired = Counter()
    for key, paths in blocks.items():
        if set(paths) == {"orm", "sql"}:
            require(paths["orm"][1] == paths["sql"][1], f"Unpaired parameters: {key}")
            paired[key[:-1]] += 1
    require(
        len(paired) == 336 and set(paired.values()) == {8},
        "Expected 336 cells with eight paired blocks",
    )
    measured_analytical = {
        (
            normalized(r["dbms"]),
            r["schema_config"].lower(),
            r["query_id"],
            r["orm"].lower(),
        )
        for r in coverage
        if r["benchmark"] == "tpch" and r["orm_status"] == "ok"
    }
    require(
        set(paired) == measured_analytical,
        "Raw analytical cells disagree with coverage",
    )

    transaction_paths = set()
    throughput_rows = 0
    for db in SYSTEMS:
        for schema in SCHEMAS:
            suffix = schema.replace("-", "_")
            for row in read_csv(data / f"{db}_tpcc_{suffix}.csv"):
                key = (db, schema, row["query_id"], row["framework"], row["path"])
                require(
                    key not in transaction_paths, f"Duplicate transaction path: {key}"
                )
                require(
                    row["status"] == "ok" and row["repetitions_measured"] == "3",
                    f"Unexpected transaction protocol: {key}",
                )
                require(
                    row["scale_factor"] == "1",
                    "Transactional input mixes scale factors",
                )
                require(
                    (row["dbms"], row["schema_config"]) == (db, schema),
                    "Mislabeled transaction file",
                )
                value = float(row["median_s"])
                require(
                    math.isfinite(value) and value > 0,
                    f"Invalid transaction latency: {key}",
                )
                transaction_paths.add(key)
            throughput_rows += len(
                read_csv(data / f"{db}_tpcc_throughput_{suffix}.csv")
            )
    expected_paths = {
        (db, sc, f"T{i}", fw, path)
        for db in SYSTEMS
        for sc in SCHEMAS
        for i in range(1, 6)
        for fw in FRAMEWORKS
        for path in ("orm", "sql")
    }
    require(
        transaction_paths == expected_paths,
        "Expected 80 transaction cells on both paths",
    )
    require(throughput_rows == 960, "Expected 960 public throughput records")
    report = {
        "files_verified": len(manifest["files"]),
        "coverage_cells": 432,
        "scope": "complete four-system results",
        "coverage_statuses": dict(statuses),
        "analytical_raw_rows": analytical_rows,
        "analytical_cells": len(paired),
        "paired_blocks_per_cell": 8,
        "transactional_cells": len(transaction_paths) // 2,
        "throughput_rows": throughput_rows,
    }
    print(json.dumps(report, indent=2))
    return report


def reproduce() -> None:
    report = verify()
    output = ROOT / "outputs"
    # Do not follow a user-created symlink out of the review folder.
    require(not output.is_symlink(), "outputs must be a regular directory")
    if output.exists():
        require(
            not any(p.is_symlink() for p in output.rglob("*")),
            "outputs contains a symlink",
        )
    env = dict(os.environ)
    env.update(
        {
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(output / ".matplotlib"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_DATE_EPOCH": "1788912000",
        }
    )
    subprocess.run(
        [sys.executable, "analysis/rebuild.py"], cwd=ROOT, env=env, check=True
    )
    reference = ROOT / "analysis/reference"
    required_outputs = {
        *(
            "derived/" + name
            for name in (
                "cases.csv",
                "cells.csv",
                "systems.csv",
                "summary.json",
                "input-sha256.json",
                "tpcc_cells.csv",
                "tpcc_summary.json",
            )
        ),
        *(
            "tables_paper/four_system_" + name + ".tex"
            for name in (
                "cases",
                "coverage",
                "headline",
                "sensitivity",
                "tpcc",
            )
        ),
    }
    require(
        {
            p.relative_to(reference).as_posix()
            for p in reference.rglob("*")
            if p.is_file()
        }
        == required_outputs,
        "Expected all 12 public reference outputs",
    )
    checked = []
    for expected in sorted(reference.rglob("*")):
        if not expected.is_file():
            continue
        rel = expected.relative_to(reference)
        actual = output / rel
        require(actual.is_file(), f"Rebuild did not produce {rel}")
        # Numeric tolerance accommodates platform math libraries; tables remain exact.
        require(
            reference_matches(expected, actual),
            f"Rebuild differs from the public reference: {rel}",
        )
        checked.append(rel.as_posix())
    figures = sorted((output / "figures").glob("*.pdf"))
    require(len(figures) == 3, "Expected three regenerated figures")
    for figure in figures:
        require(
            figure.read_bytes().startswith(b"%PDF-") and figure.stat().st_size > 1000,
            f"Invalid figure: {figure.name}",
        )
    report.update(
        {
            "reference_outputs_matched": checked,
            "figures_generated": [p.name for p in figures],
            "python": sys.version.split()[0],
            "database_queries_executed": False,
            "numeric_relative_tolerance": 1e-12,
            "numeric_absolute_tolerance": 1e-12,
        }
    )
    (output / "verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"PASS: {len(checked)} retained outputs match the reference; {len(figures)} figures rebuilt."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("verify", "reproduce"), nargs="?", default="verify"
    )
    args = parser.parse_args()
    try:
        if args.command == "reproduce":
            reproduce()
        else:
            verify()
    except (
        OSError,
        ValueError,
        KeyError,
        SyntaxError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
