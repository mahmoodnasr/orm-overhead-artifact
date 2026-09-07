#!/usr/bin/env python3
"""Every number in the paper's prose, checked against something that produced it.

    python3 scripts/4-analysis/check_paper_numbers.py --paper ../../IJACSA_Paper

Why
---
The paper's numbers come from three places: the generated tables, the referee
script, and sentences a human typed. The third is where they rot. C46's fix
introduced a wrong p90 into two sections because the correction was typed
rather than computed; C47 printed one statistic as two intervals in two tables;
a caption once held a figure written as a constant that had gone stale.

Each of those is the same shape - a number that no longer matches what makes
it - and each was found by a person reading rather than by anything mechanical.
This is the mechanical version.

How
---
Every numeric token in the section files and the abstract is extracted and
matched against:

  * the generated tables in `<paper>/tables`, which come from `sf1_tables.py`;
  * the numbers `sf1_referee.py` prints, which is the working behind the prose
    claims that no table carries;
  * `docs/paper_prose_numbers.txt`, an allowlist of the numbers that are
    genuinely prose - counts of things, version strings, the grid's dimensions
    - each with the reason it cannot come from a table.

A token in none of the three is reported. That is not proof it is wrong; it is
a number nothing in the artifact accounts for, which is the state every defect
above passed through.
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))

# A minus sign, not a hyphen inside x86-64 or TPC-C. And not the exponent of
# 10^{-8}, which is a shape rather than a measurement.
NUM = re.compile(r"(?<![\w-])[-+]?\d[\d,]*(?:\.\d+)?")


def norm(tok):
    return tok.replace(",", "").replace("{", "").replace("}", "").lstrip("+").rstrip(".")


def numbers_in(text):
    return {norm(m.group()) for m in NUM.finditer(strip_exponents(text))}


def strip_exponents(t):
    """`10^{-8}` is a shape, not a measurement; its parts are not numbers.

    `204{,}000` is one number written the way LaTeX wants its thousands
    separator. Left alone the tokeniser reads it as 204 and 000, and then
    reports 204 as a figure nothing produced.
    """
    t = t.replace("{,}", "")
    return re.sub(r"\^\{?-?\d+\}?", " ", t)


def as_float(tok):
    try:
        return float(tok)
    except ValueError:
        return None


def explained_by(tok, known):
    """A prose number matches a computed one at the precision the prose states.

    The prose rounds. `sf1_referee.py` prints a pooled CV of 12.70 and Section 5
    says 12.7; the table prints +58.4 and the abstract says 58. Comparing the
    strings called both of those unaccounted for, which would have buried the
    real drift in a list of eighty false alarms.
    """
    v = as_float(tok)
    if v is None:
        return False
    dp = len(tok.split(".")[1]) if "." in tok else 0
    for k in known:
        if k is None:
            continue
        if round(k, dp) == round(v, dp):
            return True
        # The prose states direction in words where the data carries a sign:
        # Query 20 is -76.4% in the results file and "runs 76% faster" in
        # Section 5. Matching the magnitude keeps that from reading as drift.
        if round(abs(k), dp) == round(abs(v), dp):
            return True
        # The prose also rounds to significant figures: 21,260 is written
        # "21,300" and 41,572 "41,600". Matching only decimal places called
        # both of those unaccounted for.
        if sigfig(abs(k), sig_digits(tok)) == sigfig(abs(v), sig_digits(tok)):
            return True
    return False


def sig_digits(tok):
    d = tok.lstrip("+-").replace(".", "").lstrip("0")
    return max(1, len(d.rstrip("0")) or 1)


def sigfig(x, n):
    if x == 0:
        return 0.0
    import math as _m
    return round(x, -int(_m.floor(_m.log10(abs(x)))) + (n - 1))


def strip_latex(t):
    t = re.sub(r"(?<!\\)%.*", " ", t)
    t = re.sub(r"\\(label|ref|cite\w*|input|include)\s*\{[^{}]*\}", " ", t)
    return t


def prose_numbers(paper):
    """Section prose and the abstract, with LaTeX commands and comments gone."""
    out = {}
    files = sorted(f for f in os.listdir(os.path.join(paper, "sections"))
                   if f.endswith(".tex"))
    for fn in files:
        body = strip_exponents(strip_latex(
            open(os.path.join(paper, "sections", fn)).read()))
        for m in NUM.finditer(body):
            out.setdefault(norm(m.group()), set()).add(fn)
    main = open(os.path.join(paper, "main.tex")).read()
    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", main, re.S)
    if abstract:
        for m in NUM.finditer(strip_exponents(strip_latex(abstract.group(1)))):
            out.setdefault(norm(m.group()), set()).add("abstract")
    return out


def table_numbers(paper):
    got = set()
    tdir = os.path.join(paper, "tables")
    for fn in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        if fn.endswith(".tex"):
            got |= numbers_in(open(os.path.join(tdir, fn)).read())
    return got


def referee_numbers(scale):
    """Whatever sf1_referee.py prints, which is the working behind the prose."""
    r = subprocess.run([sys.executable,
                        os.path.join(HERE, "sf1_referee.py"), "--scale", scale],
                       capture_output=True, text=True, cwd=REPO,
                       env=dict(os.environ, PYTHONPATH=REPO))
    if r.returncode != 0:
        print("  sf1_referee.py failed; its numbers are not being checked",
              file=sys.stderr)
        return set()
    return numbers_in(r.stdout)


def allowlist():
    path = os.path.join(REPO, "docs", "paper_prose_numbers.txt")
    if not os.path.exists(path):
        return {}
    out = {}
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tok, _, why = line.partition("#")
        out[norm(tok.strip())] = why.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default=os.path.join(REPO, os.pardir, os.pardir,
                                                    "IJACSA_Paper"))
    ap.add_argument("--scale", default="1")
    args = ap.parse_args()
    paper = os.path.abspath(args.paper)
    if not os.path.isdir(os.path.join(paper, "sections")):
        print("no manuscript at %s; nothing to check. Pass --paper." % paper)
        return 0

    prose = prose_numbers(paper)
    tables = table_numbers(paper)
    referee = referee_numbers(args.scale)
    allowed = allowlist()
    computed = [as_float(t) for t in (tables | referee)]
    computed = [c for c in computed if c is not None]

    matched = {t for t in prose if explained_by(t, computed)}
    print("prose numbers: %d distinct" % len(prose))
    print("  produced by a table or the referee script: %d" % len(matched))
    print("  on the allowlist:                          %d"
          % sum(1 for t in prose if t not in matched and t in allowed))

    unexplained = sorted((t for t in prose
                          if t not in matched and t not in allowed),
                         key=lambda x: (len(x), x))
    if not unexplained:
        print("\nevery number in the prose is accounted for")
        return 0
    print("\n%d unaccounted for:" % len(unexplained))
    for t in unexplained:
        print("  %-12s %s" % (t, ", ".join(sorted(prose[t]))))
    return 1


if __name__ == "__main__":
    sys.exit(main())
