#!/usr/bin/env python3
"""Build a deterministic ZIP from the verified public release manifest."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.output.resolve()
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    if archive.exists() or checksum.exists():
        parser.error("Output exists; choose a new filename. Nothing was overwritten.")
    subprocess.run([sys.executable, str(ROOT / "review.py"), "verify"], check=True)
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        for rel in sorted([*manifest["files"], "MANIFEST.json"]):
            info = zipfile.ZipInfo(
                "orm-overhead-artifact/" + rel, (2026, 9, 9, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zf.writestr(info, (ROOT / rel).read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Created {archive.name} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
