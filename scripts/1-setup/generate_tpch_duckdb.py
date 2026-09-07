#!/usr/bin/env python3
"""Generate the TPC-H dataset once, into a single DuckDB file.

    python3 generate_tpch_duckdb.py                # SF10, the study's scale
    python3 generate_tpch_duckdb.py --sf 1         # a quick smoke-test scale
    python3 generate_tpch_duckdb.py --out /tmp/x.duckdb

Every loader in this directory — `load_pg.py`, `load_mysql.py`,
`load_sqlserver.py`, `load_tpcc.py`'s TPC-H sibling and `oracle_groups.py` —
streams from this file. **Nothing else creates it.** The generation call lived
only inside `load_oracle.py`, so a reader starting from a clean clone and
following the documented path found four loaders that all required a file
nothing they had run would produce. This is that step, on its own, where it can
be seen.

DuckDB's `tpch` extension generates the specification's data from a fixed
generator, so the file is reproducible: the same scale factor gives the same
rows on any machine. That is why the study generates once and streams into each
system rather than exporting `.tbl` files per vendor — the alternative costs a
full extra pass over the data, tens of gigabytes of scratch, and a text format
to get wrong.

SF10 is 59,986,052 lineitem rows and about 2.5 GB as DuckDB stores it. Expect a
minute or two.
"""
import argparse
import os
import sys
import time

import duckdb

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DEFAULT = os.path.join(REPO, "tpch10.duckdb")

EXPECTED = {  # per scale factor, the row count that says the generation worked
    1: 6_001_215,
    0.01: 60_175,
    10: 59_986_052,
    100: 600_037_902,
}


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f TB" % n


def main():
    ap = argparse.ArgumentParser()
    # float, not int: the shakedown runs the whole matrix at SF0.01, where a
    # full 22-query eight-block campaign costs minutes instead of hours. An
    # int here made the smallest reachable dataset SF1, which is why every
    # defect so far had to be found at full size.
    ap.add_argument("--sf", type=float, default=10, help="scale factor (default 10)")
    ap.add_argument("--out", default=DEFAULT)
    ap.add_argument("--force", action="store_true",
                    help="regenerate even if the file exists")
    args = ap.parse_args()

    if os.path.exists(args.out) and not args.force:
        print("reusing %s (%s)" % (args.out, human(os.path.getsize(args.out))))
        print("  pass --force to regenerate")
        return 0

    if args.force and os.path.exists(args.out):
        os.remove(args.out)

    print("generating TPC-H SF%g into %s ..." % (args.sf, args.out))
    t0 = time.perf_counter()
    con = duckdb.connect(args.out)
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute("CALL dbgen(sf=%g)" % args.sf)

    # Check the row count rather than trusting that dbgen ran. A truncated or
    # half-written file would otherwise be discovered an hour later, by a loader.
    n = con.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0]
    con.close()

    want = EXPECTED.get(args.sf)
    print("  done in %.0fs, %s, lineitem = %s rows"
          % (time.perf_counter() - t0, human(os.path.getsize(args.out)), format(n, ",")))
    if want and n != want:
        print("FAIL: expected %s lineitem rows at SF%g" % (format(want, ","), args.sf),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
