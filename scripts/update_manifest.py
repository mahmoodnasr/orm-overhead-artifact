#!/usr/bin/env python3
"""Refresh the public file manifest after reviewing intentional release edits."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    ".env",
    ".git",
    ".DS_Store",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "outputs",
    "dist",
    "venv",
    "PROVENANCE.json",
}
PRIVATE_PATTERNS = (
    r"/(?:Users|home)/[A-Za-z0-9_.-]+/",
    r"192\.168\.100\.79",
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"AKIA[A-Z0-9]{16}",
)


def main():
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    files = {}
    for name in sorted(set(filter(None, names))):
        path = ROOT / name
        if name == "MANIFEST.json" or not path.exists():
            continue
        if path.is_symlink() or FORBIDDEN.intersection(path.relative_to(ROOT).parts):
            raise ValueError(f"Local/private artifact in release selection: {name}")
        if path.suffix in {".zip", ".gz", ".bak", ".duckdb", ".pyc", ".log"}:
            raise ValueError(f"Unexpected generated or backup file: {name}")
        content = path.read_bytes()
        text = content.decode("utf-8")
        if any(re.search(pattern, text) for pattern in PRIVATE_PATTERNS):
            raise ValueError(
                f"Private material found in {name}; inspect before releasing"
            )
        files[name] = hashlib.sha256(content).hexdigest()
    manifest = ROOT / "MANIFEST.json"
    previous = manifest.read_bytes() if manifest.exists() else None
    manifest.write_text(
        json.dumps({"algorithm": "sha256", "files": files}, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        subprocess.run([sys.executable, str(ROOT / "review.py"), "verify"], check=True)
    except BaseException:
        if previous is None:
            manifest.unlink()
        else:
            manifest.write_bytes(previous)
        raise
    print(f"Recorded {len(files)} public release files")


if __name__ == "__main__":
    main()
