#!/usr/bin/env python3
"""Which timed calls overlapped a scheduled job on the host, and does it change anything?

Found 2026-10-11 22:30 (decision log): the host's own systemd timers stayed
enabled through the campaign (disabling apt-daily and apt-daily-upgrade had been
asked for on 2026-10-09 and was not done). They include:
  - apt-daily-upgrade: unattended upgrades; 2 min 15 s, 119 s CPU on 2026-10-09
    06:01 Cairo, during phase A;
  - apt-daily: up to 26 s, 19 s CPU, nine runs;
  - ua-timer, man-db, fwupd-refresh and others.
They run outside the engine's cgroup and can take CPU or disk from a measured
call. The paper's measurements ran on the same host with the same timers.

Inputs:
  - the jobs' start and end, from a journal extract
    (evidence/background-jobs/host-journal-jobs-*.txt; `journalctl -o short-iso -u
    <unit>`, lines Starting / Finished / Deactivated successfully / Failed /
    Consumed, prefixed '<unit> | ');
  - every timed call's start and end, from the records.
A call overlaps a job if it starts before the job's end + 1 s (the journal has
whole seconds) and ends after the job's start.

Reports:
  - every accepted block (one ORM/SQL pair per framework) with a timed call
    overlapping a job;
  - for each A, D, E and C cell with such a block, the paired estimate with and
    without those blocks;
  - the pooled medians of A, D and E without the touched blocks;
  - for F and B, overlap counts only.
This is evidence, not a new estimate: the estimand stays as defined.

Usage: python code/rc_background_overlap.py --journal evidence/background-jobs/host-journal-jobs-20261007-20261011.txt --out <json>
"""
import argparse
import collections
import datetime as dt
import glob
import gzip
import json
import math
from pathlib import Path
import re
import statistics as st
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

CAMP = HERE.parent
pct = lambda x: 100 * math.expm1(x)
SECOND = dt.timedelta(seconds=1)


def jobs(path):
    """One job per 'Starting' line, ending at the unit's last line before its next start
    (Deactivated / Finished / Failed / Consumed all belong to the run they follow)."""
    out, cur = [], {}
    for line in Path(path).read_text().splitlines():
        unit, rest = line.split(' | ', 1)
        if unit == 'anacron':          # hourly wrapper; its cron.daily scripts defer to the systemd units listed here
            continue
        ts = dt.datetime.fromisoformat(rest[:25])
        if ' Starting ' in rest:
            if unit in cur:
                out.append(cur.pop(unit))
            cur[unit] = {'unit': unit, 'start': ts, 'end': ts, 'cpu': None}
        elif unit in cur:
            cur[unit]['end'] = max(cur[unit]['end'], ts)
            m = re.search(r'Consumed (.*?) CPU time', rest)
            if m:
                cur[unit]['cpu'] = sum(float(v) * {'h': 3600, 'min': 60, 's': 1, 'ms': 0.001}[u]
                                       for v, u in re.findall(r'([\d.]+)(min|ms|s|h)', m.group(1)))
    out += cur.values()
    return sorted(out, key=lambda j: j['start'])


def when(rec):
    return dt.datetime.fromisoformat(rec['start']['utc']), dt.datetime.fromisoformat(rec['end']['utc'])


def hits(rec, J):
    s, e = when(rec)
    return [f"{j['unit']}@{j['start'].isoformat(timespec='seconds')}" for j in J
            if s < j['end'] + SECOND and e > j['start']]


def analytical(run_dir, J):
    """A, D, E records: qNN/bN/decision.json, timed_records per path."""
    cells, touched = [], []
    for cdir in sorted(run_dir.glob('q[0-9][0-9]')):
        for fw in ('django', 'sqlalchemy'):
            pairs = []
            for b in range(1, 9):
                d = cdir / f'b{b}' / 'decision.json'
                if not d.exists():
                    continue
                dec = C.load(d)
                if not dec['frameworks'][fw]['accepted']:
                    continue
                so = C.load(d.parent / dec['timed_records'][f'{fw}/sql'])
                oo = C.load(d.parent / dec['timed_records'][f'{fw}/orm'])
                h = sorted(set(hits(so, J) + hits(oo, J)))
                pairs.append((b, math.log(oo['elapsed_s'] / so['elapsed_s']), h))
            if any(h for _, _, h in pairs):
                touched += [{'run': str(run_dir.relative_to(CAMP)), 'query': cdir.name, 'framework': fw,
                             'block': b, 'jobs': h} for b, _, h in pairs if h]
            if len(pairs) == 8:
                clean = [t for _, t, h in pairs if not h]
                cells.append({'run': str(run_dir.relative_to(CAMP)), 'query': cdir.name, 'framework': fw,
                              'theta': st.median(t for _, t, _ in pairs),
                              'theta_clean': st.median(clean) if clean else None,
                              'touched_blocks': sum(1 for *_, h in pairs if h)})
    return cells, touched


def tpcc(run_dir, J):
    cells, touched = [], []
    for tdir in sorted(run_dir.glob('T[0-9]')):
        for fw in ('django', 'sqlalchemy'):
            pairs = []
            for d in sorted(tdir.glob('b[0-9][0-9]/decision.json')):
                dec = json.loads(d.read_text())
                if not dec['frameworks'].get(fw, {}).get('accepted'):
                    continue
                att = sorted(d.parent.glob('a*'))[-1]
                so = C.untyped(json.load(gzip.open(att / f'timed-{fw}-sql.json.gz')))
                oo = C.untyped(json.load(gzip.open(att / f'timed-{fw}-orm.json.gz')))
                h = sorted(set(hits(so, J) + hits(oo, J)))
                pairs.append((d.parent.name, math.log(oo['elapsed_s'] / so['elapsed_s']), h))
            touched += [{'run': str(run_dir.relative_to(CAMP)), 'query': tdir.name, 'framework': fw,
                         'block': b, 'jobs': h} for b, _, h in pairs if h]
            if pairs:
                clean = [t for _, t, h in pairs if not h]
                cells.append({'run': str(run_dir.relative_to(CAMP)), 'query': tdir.name, 'framework': fw,
                              'theta': st.median(t for _, t, _ in pairs),
                              'theta_clean': st.median(clean) if clean else None,
                              'touched_blocks': sum(1 for *_, h in pairs if h), 'blocks': len(pairs)})
    return cells, touched


def scan_only(pattern, J):
    out, n = [], 0
    for f in sorted(glob.glob(str(CAMP / pattern), recursive=True)):
        rec = C.untyped(json.load(gzip.open(f)))
        if 'start' not in rec:
            continue
        n += 1
        h = hits(rec, J)
        if h:
            out.append({'record': str(Path(f).relative_to(CAMP)), 'jobs': h})
    return n, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--journal', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    J = jobs(a.journal)
    runs = {
        'A': sorted(p for p in (CAMP / 'A-sf1').iterdir() if p.is_dir() and (p / 'completion.json').exists()),
        'D': sorted(p for p in (CAMP / 'D-sf2').iterdir() if p.is_dir() and (p / 'completion.json').exists()),
        # E: Commercial System A non-indexed from the re-measurement (08-commercial_a-separate-client.md)
        'E': sorted(CAMP / 'E-client' / f'{e}-{s}{"-r2" if (e, s) == ("sqlserver", "non-indexed") else ""}'
                    for e in ('postgresql', 'mysql', 'oracle', 'sqlserver') for s in ('indexed', 'non-indexed')),
    }
    rep = {'generated': C.stamps(), 'journal': str(a.journal), 'jobs': len(J),
           'jobs_by_unit': dict(collections.Counter(j['unit'] for j in J)), 'phases': {}}
    for ph, dirs in runs.items():
        cells, touched = [], []
        for r in dirs:
            c, t = analytical(r, J)
            cells += c
            touched += t
        changed = [c for c in cells if c['touched_blocks']]
        rep['phases'][ph] = {
            'runs': [str(r.relative_to(CAMP)) for r in dirs], 'cells': len(cells),
            'touched_blocks': len(touched), 'touched_cells': len(changed),
            'pooled_median_pct': pct(st.median(c['theta'] for c in cells)),
            'pooled_median_pct_without_touched_blocks': pct(st.median(c['theta_clean'] for c in cells)),
            'max_abs_cell_change_pct_points': max((abs(pct(c['theta_clean']) - pct(c['theta'])) for c in changed), default=0),
            'cells_touched': [dict(c, overhead_pct=pct(c['theta']), overhead_pct_without=pct(c['theta_clean'])) for c in changed],
            'blocks': touched}
    cells, touched = [], []
    for r in sorted(p for p in (CAMP / 'C-tpcc').iterdir() if p.is_dir() and p.name != 'oracle-non-indexed'):
        c, t = tpcc(r, J)
        cells += c
        touched += t
    changed = [c for c in cells if c['touched_blocks']]
    rep['phases']['C'] = {'cells': len(cells), 'touched_blocks': len(touched), 'touched_cells': len(changed),
                          'pooled_median_pct': pct(st.median(c['theta'] for c in cells)),
                          'pooled_median_pct_without_touched_blocks': pct(st.median(c['theta_clean'] for c in cells)),
                          'max_abs_cell_change_pct_points': max((abs(pct(c['theta_clean']) - pct(c['theta'])) for c in changed), default=0),
                          'cells_touched': [dict(c, overhead_pct=pct(c['theta']), overhead_pct_without=pct(c['theta_clean'])) for c in changed],
                          'blocks': touched}
    for ph, pattern in (('F', 'F-fourpath/**/timed-*.json.gz'), ('B', 'B-censored/**/probe-*.json.gz')):   # B's calls are probe-* records
        n, h = scan_only(pattern, J)
        rep['phases'][ph] = {'timed_records': n, 'overlapping_records': len(h), 'records': h}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'x') as fh:
        fh.write(json.dumps(rep, indent=1, default=str) + '\n')
    for ph, v in rep['phases'].items():
        print(ph, {k: (round(x, 3) if isinstance(x, float) else x) for k, x in v.items()
                   if k not in ('cells_touched', 'blocks', 'records', 'runs')})
    print('->', a.out)


if __name__ == '__main__':
    main()
