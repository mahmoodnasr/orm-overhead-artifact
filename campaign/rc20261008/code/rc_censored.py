#!/usr/bin/env python3
"""Phase B: matched-input probes for a path censored in phase A.

In phase A a path that exceeds the ceiling on the cell-warmup input is not run
on the eight measured inputs (historical protocol), so the cell has no
matched-input evidence. Here, for one framework of one cell, every one of the
eight saved inputs is run on BOTH arms in the same block, the counterpart
warmed first, the censored arm not warmed (its warmup would be another full
ceiling and adds nothing to a call that runs to the limit), arm order
alternating by the seeded plan.

Per input:
  both complete     -> results compared under the protocol's policy; an
                       accepted pair is a measured ratio
  ORM timed out     -> O/S >= L/S   (lower bound; L = the ceiling)
  SQL timed out     -> O/S <= O/L   (upper bound)
  both timed out    -> no bound, no equivalence
The cell-level statement is made only from inputs that all give a value or a
bound in one direction: if every input i satisfies r_i >= b_i, the median of r
is at least the median of b. Nothing else is inferred.
"""
import argparse
import math
import os
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402
from rc_analytical import Runner  # noqa: E402


class Probe(Runner):
    def inventory(self, label):
        # record this file's hash beside the runner's, so a phase B record names
        # the probe code that produced it (the gate compares it with the protocol)
        inv = super().inventory(label)
        inv['code_hashes']['rc_censored.py'] = C.file_sha256(HERE / 'rc_censored.py')
        return inv

    def run_cell(self, q):
        a = self.a
        fw = a.framework
        orm, sql = f'{fw}/orm', f'{fw}/sql'
        cdir = self.run_dir / f'q{q:02d}'   # one run dir per framework
        if (cdir / 'cell-done.json').exists():
            return
        self.mods = self.modules(q)
        inp = self.inputs['queries'][str(q)]
        seed, plan = C.block_plan(f"{self.protocol['protocol_id']}:{a.dbms}:{a.schema}:sf{a.scale}:{a.database_label}:q{q}:{fw}")
        if not (cdir / 'plan.json').exists():
            C.save(cdir / 'plan.json', {'seed': seed, 'plan': plan, 'censored_arm': a.censored_path})
        results = []
        for b in range(1, 9):
            bdir = cdir / f'b{b}'
            if (bdir / 'decision.json').exists():
                results.append(C.load(bdir / 'decision.json'))
                continue
            i = b - 1
            params, input_id = inp['sets'][i], inp['set_ids'][i]
            att = self._attempt(bdir)
            counterpart = sql if a.censored_path == orm else orm
            w = self.execute(q, counterpart, params, {'kind': 'block_warmup', 'block': b, 'attempt': att,
                                                       'sequence_id': None, 'position': -1, 'input_id': input_id})
            self.record(f'q{q:02d}/b{b}/a{att}/warm-{counterpart.replace("/", "-")}.json.gz', w)
            order = [counterpart, a.censored_path] if plan[i] % 2 == 0 else [a.censored_path, counterpart]
            recs = {}
            for pos, path in enumerate(order):
                r = self.execute(q, path, params, {'kind': 'probe', 'block': b, 'attempt': att, 'sequence_id': plan[i],
                                                   'position': pos, 'input_id': input_id})
                self.record(f'q{q:02d}/b{b}/a{att}/probe-{path.replace("/", "-")}.json.gz', r)
                recs[path] = r
            o, s = recs[orm], recs[sql]
            dec = {'query': q, 'framework': fw, 'block': b, 'attempt': att, 'input_id': input_id,
                   'order': order, 'status': [o['status'], s['status']], 'limit_s': a.timeout, **C.stamps()}
            if o['status'] == 'ok' and s['status'] == 'ok':
                c = C.compare(q, s['rows'], o['rows'], s.get('output_columns'), o.get('output_columns'),
                              policy=self.protocol['result_policy']['version'])
                dec.update(kind='measured' if c['accepted'] else 'mismatch', comparison=c,
                           ratio=o['elapsed_s'] / s['elapsed_s'])
            elif o['status'] == 'timeout' and s['status'] == 'ok':
                dec.update(kind='lower_bound', bound=a.timeout / s['elapsed_s'], sql_elapsed_s=s['elapsed_s'])
            elif s['status'] == 'timeout' and o['status'] == 'ok':
                dec.update(kind='upper_bound', bound=o['elapsed_s'] / a.timeout, orm_elapsed_s=o['elapsed_s'])
            elif o['status'] == 'timeout' and s['status'] == 'timeout':
                dec.update(kind='both_censored')
            else:
                dec.update(kind='error')
            C.save(bdir / 'decision.json', dec, immutable=True)
            results.append(dec)
            self.event('probe_decided', query=q, framework=fw, block=b, kind=dec['kind'])
        kinds = {r['kind'] for r in results}
        # 'status' is read by the phase A runner's end checks (rc_analytical.main);
        # B-v1 left it out, so a finished probe exited 1 with KeyError: 'status'
        # (Mac dry run, 2026-10-09 22:25) - fixed before any phase B run, as B-v2
        summary = {'query': q, 'framework': fw, 'status': 'complete', 'censored_arm': a.censored_path,
                   'inputs': len(results), 'kinds': sorted(kinds), **C.stamps()}
        vals = [r.get('ratio') or r.get('bound') for r in results]
        if kinds <= {'measured', 'lower_bound'} and len(results) == 8:
            summary['median_ratio_at_least'] = math.exp(statistics.median(math.log(v) for v in vals))
        elif kinds <= {'measured', 'upper_bound'} and len(results) == 8:
            summary['median_ratio_at_most'] = math.exp(statistics.median(math.log(v) for v in vals))
        else:
            summary['bound'] = 'none identifiable from these inputs'
        C.save(cdir / 'cell-done.json', summary, immutable=True)
        self.event('cell_done', query=q, framework=fw, summary=summary)


def main():
    ap = argparse.ArgumentParser()
    for x in ('--campaign-dir', '--run-dir', '--protocol'):
        ap.add_argument(x, type=Path, required=True)
    ap.add_argument('--src', type=Path)
    ap.add_argument('--phase', default='B')
    ap.add_argument('--dbms', required=True)
    ap.add_argument('--schema', required=True)
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--database-label', default='tpch')
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--framework', choices=['django', 'sqlalchemy'], required=True)
    ap.add_argument('--censored-path', required=True)
    ap.add_argument('--timeout', type=float, default=900)
    ap.add_argument('--mode', default='main')
    ap.add_argument('--blocks', type=int, default=8)
    ap.add_argument('--client-mode', default='same-host')
    ap.add_argument('--client-cpus', default='2,3')
    ap.add_argument('--cancel-wait', type=float, default=60)
    ap.add_argument('--crash-at', type=int, default=0)
    ap.add_argument('--cancel-test-query', type=int, default=0)
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()
    assert a.censored_path.startswith(a.framework + '/')
    Probe(a).main()


if __name__ == '__main__':
    main()
