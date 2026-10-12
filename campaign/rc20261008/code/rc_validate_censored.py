#!/usr/bin/env python3
"""Result validation of the censored cells (reviewer item R1-2), on the Mac.

Reviewer 1 asked for validation of the cells above +100 % *and the censored
cells*. Phase A checks the result of every timed call, but a censored path
never returns a result inside the 900 s ceiling, so its cell has nothing to
check. These are the twelve framework cells the historical SF1 campaign
censored (results/sf1/all_results.csv): PostgreSQL non-indexed Q13 Django,
Q17, Q20, Q21 (both frameworks); MySQL non-indexed Q13 Django, Q17, Q20 (both).

Each cell runs once, on the input it was censored on (the cell-warmup
instance), all four paths, SQL paths first, with the ceiling raised from 900 s
to a 4 h safety cap (protocol rc20261008-V-v1). The results go through the same
comparison code and policy as every phase A block (compare_block, policy v3,
ORM path check). Result equivalence is a property of the statements and the
data, not of the machine: the data is content-identical to the host's
(fingerprint 3ca615ff..., checked before and after), the engine, Python and
library versions are the host's. The elapsed times are recorded but are not
measurements under the eight-block design and are never used as overheads.

A path still running at the cap stays unvalidated and says so.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402
from rc_g import SecondServer  # noqa: E402

# SQL paths first: they show the work is finite before the slower ORM paths run
ORDER = ('django/sql', 'sqlalchemy/sql', 'sqlalchemy/orm', 'django/orm')


class Validator(SecondServer):
    def inventory(self, label):
        inv = super().inventory(label)
        inv['code_hashes']['rc_validate_censored.py'] = C.file_sha256(HERE / 'rc_validate_censored.py')
        return inv

    def gate(self, inv):
        # Nothing is timed here, so other containers in the VM do not affect the
        # outcome; they are recorded in the inventory, not refused.
        return [p for p in super().gate(inv) if not p.startswith('other containers running')]

    def run_cell(self, q):
        cdir = self.run_dir / f'q{q:02d}'
        if (cdir / 'cell-done.json').exists():
            self.event('cell_skip_done', query=q)
            return
        self.mods = self.modules(q)
        inp = self.inputs['queries'][str(q)]
        att = self._attempt(cdir / 'validate')
        recs = {}
        for pos, path in enumerate(ORDER):
            ctx = {'kind': 'validation', 'block': 0, 'attempt': att, 'sequence_id': None, 'position': pos,
                   'input_id': f'q{q:02d}warm', 'limit': self.a.timeout}
            r = self.execute(q, path, inp['warmup'], ctx)
            self.record(f'q{q:02d}/validate/a{att}/{path.replace("/", "-")}.json.gz', r)
            recs[path] = r
        cmp_ = self.compare_block(q, recs)
        verdicts = {}
        for fw in ('django', 'sqlalchemy'):
            c = cmp_[fw]
            st = {p: recs[p]['status'] for p in (f'{fw}/sql', f'{fw}/orm')}
            if c.get('classification') == 'unavailable':
                verdicts[fw] = {'validated': False, 'reason': f'no result to compare: {st}'}
            else:
                ok = c['accepted'] and c['orm_path_check']['passed']
                verdicts[fw] = {'validated': ok, 'classification': c['classification'],
                                'orm_path_check': c['orm_path_check']['passed'],
                                'reason': 'ORM result accepted against its SQL baseline' if ok else
                                f"not accepted: {c['classification']}"}
        out = {'query': q, 'input_id': f'q{q:02d}warm', 'parameters': inp['warmup'], 'ceiling_s': self.a.timeout,
               'statuses': {p: recs[p]['status'] for p in ORDER},
               'elapsed_s': {p: recs[p]['elapsed_s'] for p in ORDER},
               'rows': {p: recs[p].get('rows_returned') for p in ORDER},
               'comparisons': cmp_, 'verdicts': verdicts,
               'records': {p: f'validate/a{att}/{p.replace("/", "-")}.json.gz' for p in ORDER},
               'note': 'validation only: elapsed times are single executions, not measurements', **C.stamps()}
        C.save(cdir / 'validation.json', out, immutable=True)
        # the runner's end-of-run bookkeeping reads cell-done.json; 'complete'
        # means the validation run finished, the verdicts are in validation.json
        C.save(cdir / 'cell-done.json', {'query': q, 'status': 'complete', 'verdicts': verdicts, **C.stamps()},
               immutable=True)
        self.event('validation_done', query=q, verdicts={k: v['validated'] for k, v in verdicts.items()},
                   cross={k: cmp_[k]['classification'] for k in ('cross_sql', 'cross_orm')})


def main():
    ap = argparse.ArgumentParser()
    for x in ('--campaign-dir', '--run-dir', '--protocol'):
        ap.add_argument(x, type=Path, required=True)
    ap.add_argument('--src', type=Path, default=Path.home() / 'rc20261008-client' / 'src')
    ap.add_argument('--phase', default='V')
    ap.add_argument('--dbms', required=True, choices=['postgresql', 'mysql'])
    ap.add_argument('--schema', default='non-indexed', choices=['non-indexed'])
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--database-label', default='mac-tpch')
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--timeout', type=float, default=14400)
    ap.add_argument('--blocks', type=int, default=0)
    ap.add_argument('--mode', default='main')
    ap.add_argument('--client-mode', default='second-server-mac')
    ap.add_argument('--client-cpus', default='')
    ap.add_argument('--cancel-wait', type=float, default=60)
    ap.add_argument('--crash-at', type=int, default=0)
    ap.add_argument('--cancel-test-query', type=int, default=0)
    ap.add_argument('--resume', action='store_true')
    Validator(ap.parse_args()).main()


if __name__ == '__main__':
    main()
