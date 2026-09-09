"""The distribution verifier must reject damaged data, even with refreshed hashes."""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package(tmp_path):
    shutil.copyfile(ROOT / "review.py", tmp_path / "review.py")
    shutil.copytree(ROOT / "results/sf1", tmp_path / "results/sf1")
    refresh_manifest(tmp_path)
    return tmp_path


def refresh_manifest(package):
    paths = [package / "review.py", *sorted((package / "results/sf1").rglob("*.csv"))]
    value = {
        "algorithm": "sha256",
        "files": {
            p.relative_to(package).as_posix(): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in paths
        },
    }
    (package / "MANIFEST.json").write_text(json.dumps(value), encoding="utf-8")


def run_verify(package):
    return subprocess.run(
        [sys.executable, str(package / "review.py"), "verify"],
        cwd=package,
        capture_output=True,
        text=True,
    )


def change_measurement(package, change):
    path = package / "results/sf1/measurements/postgresql_indexed.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    index = next(
        i
        for i, row in enumerate(rows)
        if row["is_warmup"] == "0" and row["status"] == "ok"
    )
    change(rows, index)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    refresh_manifest(package)


def test_intact_inputs_pass(package):
    result = run_verify(package)
    assert result.returncode == 0, result.stderr


def test_changed_file_fails_hash_check(package):
    path = package / "results/sf1/all_results.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    result = run_verify(package)
    assert result.returncode != 0
    assert "File differs from the review package" in result.stderr


def test_missing_pair_fails_even_with_updated_hashes(package):
    change_measurement(package, lambda rows, i: rows.pop(i))
    result = run_verify(package)
    assert result.returncode != 0
    assert "Expected 336 cells with eight paired blocks" in result.stderr


def test_zero_timing_fails_even_with_updated_hashes(package):
    change_measurement(package, lambda rows, i: rows[i].update(elapsed_s="0"))
    result = run_verify(package)
    assert result.returncode != 0
    assert "Invalid elapsed time" in result.stderr


def test_duplicate_path_fails_even_with_updated_hashes(package):
    change_measurement(package, lambda rows, i: rows.append(dict(rows[i])))
    result = run_verify(package)
    assert result.returncode != 0
    assert "Duplicate analytical path" in result.stderr


def test_missing_commercial_measurement_fails_even_with_updated_hashes(package):
    path = package / "results/sf1/all_results.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    row = next(row for row in rows if row["dbms"] == "Commercial System A")
    row["direct_sql_execution_s"] = ""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    refresh_manifest(package)
    result = run_verify(package)
    assert result.returncode != 0
    assert "Measured coverage row is missing measurement values" in result.stderr


def test_missing_commercial_raw_file_is_rejected(package):
    path = package / "results/sf1/measurements/commercial_a_indexed.csv"
    path.unlink()
    refresh_manifest(package)
    result = run_verify(package)
    assert result.returncode != 0
    assert "Unexpected or missing data files" in result.stderr


def test_numeric_comparison_tolerates_only_roundoff():
    import review

    assert review.equal_numbers({"value": 1.0}, {"value": 1.0 + 1e-13})
    assert not review.equal_numbers({"value": 1.0}, {"value": 1.0 + 1e-6})
    assert not review.equal_numbers({"n": 250}, {"n": 251})
    assert not review.equal_numbers({"value": 1.0}, {"value": float("nan")})


def test_table_comparison_requires_exact_text(tmp_path):
    import review

    left = tmp_path / "reference.tex"
    right = tmp_path / "actual.tex"
    left.write_text("0.72")
    right.write_text("0.73")
    assert not review.reference_matches(left, right)
