#!/usr/bin/env python3
"""Which queries may be measured: the ones the validator passed, and no others.

    validated_queries.py LOG [--want "1 2 3"]

Reads the table that scripts/validate_queries.py prints - kept per campaign as
results/corrected/<dbms>_<schema>.validate.log, or per group for Oracle - and
prints on stdout the query numbers that passed all five checks, space-separated
and without leading zeros, so a chain script can loop over exactly those.
Everything excluded is listed on stderr and in the log's sibling `.gate.log`,
each with the validator's reason, so the decision is on disk beside the
evidence for it.

Fails closed. A query with no row in the log was never validated and is not
printed. A missing or empty log exits 2 and prints nothing, so a chain that
captures the output measures nothing rather than everything.

Why this exists: defect C23. The four campaign chains piped the validator
through tee and then measured every query in their list, whatever it had just
printed. PostgreSQL Q18 timed out on the validator's clock in both schemas and
was timed anyway; Oracle Q08 returned a different result through Django's ORM
than through either hand-written baseline and was timed anyway, and sat in the
results file as a valid -0.6%. The rule "all five checks pass before any timing
is kept" was stated in three documents and enforced by none. This is the code.
"""
import os
import re
import sys

# One line per query, as validate_queries.py prints it:
#   q08    yes   DIFF   ok    DIFF     ok            2   36.550 ...
#   q18    ERROR  OperationalError: (psycopg2.errors.QueryCanceled) ...
# `n/a` appears when a check needed an access path that did not run - Django
# cannot express Q13 on SQL Server or Oracle, for instance. It is matched here
# so the row is read rather than skipped, and it is not in the accepted set
# below, so the query is still refused. Silence and "not checked" must not look
# alike to this gate.
ROW = re.compile(r"^(q\d\d)\s+(yes|NO|n/a)\s+(ok|DIFF|n/a)\s+(ok|DIFF|n/a)"
                 r"\s+(ok|DIFF|n/a)\s+(ok|EMPTY|n/a)\s")
ERR = re.compile(r"^(q\d\d)\s+ERROR\s+(.*)$")
NAMES = ("ORM?", "MATCH", "SQL=", "ORM=SQL", "ROWS>0")


def parse(path):
    """{query number: (state, reason)} with state in pass / fail / error."""
    verdict = {}
    with open(path, errors="replace") as fh:
        for line in fh:
            s = line.rstrip("\n")
            m = ROW.match(s)
            if m:
                cols = m.groups()
                bad = [(n + "(not checked)" if v == "n/a" else n)
                       for n, v in zip(NAMES, cols[1:]) if v not in ("yes", "ok")]
                verdict[int(cols[0][1:])] = ("pass", "") if not bad else ("fail", ", ".join(bad))
                continue
            m = ERR.match(s)
            if m:
                verdict[int(m.group(1)[1:])] = ("error", m.group(2).strip())
    return verdict


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: validated_queries.py LOG [--want \"1 2 3\"]", file=sys.stderr)
        return 2
    log = argv[1]
    want = None
    if "--want" in argv:
        raw = argv[argv.index("--want") + 1] if argv.index("--want") + 1 < len(argv) else ""
        want = [int(x.lstrip("qQ")) for x in raw.split()]

    if not os.path.exists(log):
        print(f"validated_queries: no validation log at {log}; nothing may be measured",
              file=sys.stderr)
        return 2
    verdict = parse(log)
    if not verdict:
        print(f"validated_queries: no validation table in {log}; nothing may be measured",
              file=sys.stderr)
        return 2

    nums = want if want is not None else sorted(verdict)
    passed, lines = [], []
    for n in nums:
        state, why = verdict.get(n, ("absent", "no row in the validation log - never validated"))
        if state == "pass":
            passed.append(n)
            lines.append(f"Q{n:02d}  measure")
        else:
            lines.append(f"Q{n:02d}  SKIP  {state}: {why}")

    gate_path = re.sub(r"\.log$", "", log) + ".gate.log"
    try:
        with open(gate_path, "w") as fh:
            fh.write(f"gate for {os.path.basename(log)}: {len(passed)} of {len(nums)} may be measured\n")
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass
    for ln in lines:
        print("  " + ln, file=sys.stderr)
    print(" ".join(str(n) for n in passed))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
