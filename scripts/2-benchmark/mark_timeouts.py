#!/usr/bin/env python3
"""Record queries that validation already proved cannot finish, without paying
to prove it a second time.

Validation runs each query once per access path under a ceiling. If a query
blows that ceiling, measuring it afterwards buys nothing: the campaign runs it
four more times, each one waiting out the full measurement ceiling, and records
exactly the fact validation already established. On MySQL SF10 non-indexed that
is four queries x four paths x 900 seconds = four hours of deliberate waiting.

This writes the timeout rows straight from the validation evidence, so --resume
skips those queries. The row says what it is: a timeout, at a named ceiling,
established by validation rather than by measurement.

    python3 mark_timeouts.py --validation mysql_non-indexed.validate.log \\
        --out results_sf10/measurements/mysql_non_indexed.csv \\
        --dbms mysql --schema non-indexed --ceiling 300
"""
import argparse, csv, os, re, sys

BANDS = {
    **{q: "Simple" for q in (6, 14, 19)},
    **{q: "Medium" for q in (1, 3, 4, 11, 12, 16)},
    **{q: "Complex" for q in (2, 5, 7, 10, 13, 15, 17, 18, 20)},
    **{q: "Very Complex" for q in (8, 9, 21, 22)},
}
FIELDS = ["benchmark", "query_id", "band", "dbms", "schema_config", "framework",
          "path", "median_s", "min_s", "max_s", "cv_pct", "rows_returned",
          "repetitions_measured", "status", "note"]

# Only these mean "ran out of clock". Anything else is a real error and must not
# be silently converted into a timeout row.
TIMEOUT_SIGNS = ("maximum statement execution time exceeded",
                 "call timeout of", "canceling statement due to statement timeout",
                 "QueryCanceled", "DPY-4024", "3024")


def timed_out(line):
    return any(sig in line for sig in TIMEOUT_SIGNS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validation", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dbms", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--ceiling", type=float, required=True,
                    help="the validation ceiling these queries exceeded, seconds")
    args = ap.parse_args()

    hits = []
    for line in open(args.validation):
        m = re.match(r"^(q\d\d)\s+ERROR\s+(.*)$", line.strip())
        if m and timed_out(m.group(2)):
            hits.append((int(m.group(1)[1:]), m.group(2)[:90]))

    if not hits:
        print("no timeout failures in", args.validation)
        return 0

    done = set()
    if os.path.exists(args.out):
        for r in csv.DictReader(open(args.out)):
            done.add(r["query_id"])

    rows = []
    for n, msg in hits:
        qid = "Q%02d" % n
        if qid in done:
            print(f"{qid}: already recorded, leaving alone")
            continue
        for fw in ("django", "sqlalchemy"):
            for path in ("sql", "orm"):
                rows.append({
                    "benchmark": "tpch", "query_id": qid, "band": BANDS[n],
                    "dbms": args.dbms, "schema_config": args.schema,
                    "framework": fw, "path": path,
                    "median_s": "", "min_s": "", "max_s": "", "cv_pct": "",
                    "rows_returned": "", "repetitions_measured": 0,
                    "status": "timeout",
                    "note": ("exceeded the %.0fs ceiling during validation, so it was "
                             "not measured: four paths x four repetitions would have "
                             "waited out the ceiling each time to record the fact "
                             "validation already established. %s"
                             % (args.ceiling, msg)),
                })
        print(f"{qid}: recorded as timeout at {args.ceiling:.0f}s")

    if rows:
        new = not os.path.exists(args.out)
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
