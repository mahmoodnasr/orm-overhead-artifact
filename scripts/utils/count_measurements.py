#!/usr/bin/env python3
"""Count the measurements in a per-campaign CSV, correctly.

    python3 count_measurements.py results/corrected/measurements/mysql_indexed.csv
    python3 count_measurements.py FILE --require 80        # exit 1 if fewer
    python3 count_measurements.py FILE --field paths       # just the number

Exists because `wc -l` is wrong on these files and the error is silent.

psycopg2, oracledb and pyodbc all embed newlines in their exception text, and
`run_query.py` writes that text into the `status_note` column. So a failed path's
record spans several physical lines, and one line is not one record. Measured on
a real file: 88 records occupied 102 lines, and a line-oriented count of non-`ok`
rows reported 12 failures against an actual 5 -- it was counting continuation
lines as failed measurements.

Both directions of that error matter. Over-reporting failures sends someone
looking for a defect that is not there. Under-reporting completeness is worse:
the campaign chain scripts gate the index build on "did the previous campaign
finish", and an inflated line count can carry an *incomplete* campaign past that
gate. The indexed configuration would then be built on top of a half-measured
non-indexed one, with nothing in the output to say so.

Counts unique (query_id, framework, path) with last-wins, which is exactly how
`load_measurements()` in make_all_results.py reads the same file, so this and the
results file can never disagree about how much is done.
"""
import argparse
import csv
import sys


def count(path):
    """-> (paths, ok, non_ok, [(query, framework, path, status), ...])."""
    seen = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("query_id") or not row.get("framework"):
                continue
            seen[(row["query_id"], row["framework"], row["path"])] = row
    bad = sorted((q, f, p, r["status"])
                 for (q, f, p), r in seen.items() if r.get("status") != "ok")
    return len(seen), len(seen) - len(bad), len(bad), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--require", type=int, default=0,
                    help="exit 1 if fewer than this many paths are recorded")
    ap.add_argument("--field", choices=["paths", "ok", "non_ok"],
                    help="print only this number, for use in a shell guard")
    args = ap.parse_args()

    try:
        paths, ok, non_ok, bad = count(args.csv)
    except FileNotFoundError:
        # A guard asking about a campaign that has not started should fail, not
        # crash: print a count of zero and let --require decide.
        if args.field:
            print(0)
        else:
            print("%s: missing" % args.csv)
        return 1 if args.require else 0

    if args.field:
        print({"paths": paths, "ok": ok, "non_ok": non_ok}[args.field])
    else:
        print("paths=%d/88  ok=%d  non_ok=%d" % (paths, ok, non_ok))
        for q, f, p, st in bad:
            print("   %-5s %-11s %-4s %s" % (q, f, p, st))

    if args.require and paths < args.require:
        print("FAIL: %d paths recorded, %d required" % (paths, args.require),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
