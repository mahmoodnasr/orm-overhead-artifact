#!/usr/bin/env python3
"""Phase F, protocol F-v3: the F-v2 runner (rc_controlled2.py, unchanged)
with one correction for Oracle.

6. G's column assembly (F-v2 correction 1) matches column names without
   regard to case. Statements replayed on Oracle return the database's
   labels in upper case (S_SUPPKEY ... and TOTAL_REVENUE from the second
   statement), while the ORM's output names are lower case. F-v2 looked for
   'total_revenue' among the upper-case labels, found no column to add and
   returned the replay unassembled, so every block of Django Q15 on Oracle was
   classified schema_error against L (Mac test, 2026-10-09 22:15 Cairo; MySQL,
   PostgreSQL and Commercial System A label in lower case and were unaffected). The
   comparison already treats names case-insensitively (rc_common.cname); the
   assembly now does too, and the added column keeps the label of the
   statement it comes from.

Found by testing every remaining F cell on the Mac before the host reached
it. Nothing else changes: on every other engine, and for every other query,
F-v3 runs exactly as F-v2.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402
import rc_controlled as F1  # noqa: E402
import rc_controlled2 as F2  # noqa: E402


def assemble_ci(last, earlier, missing):
    """F2.assemble with column names matched without regard to case."""
    for i in range(len(earlier) - 1, -1, -1):
        rows = earlier[i]
        if not rows:
            continue
        names = {str(c).lower(): c for c in rows[0]}
        src = {k: names.get(str(k).lower()) for k in missing}
        if any(v is None for v in src.values()):
            continue
        for ek in rows[0]:
            if ek in src.values():
                continue
            ev = [r[ek] for r in rows]
            if len(set(ev)) != len(ev):
                continue
            for gk in last[0]:
                gv = [r[gk] for r in last]
                if len(set(gv)) == len(gv) and set(gv) <= set(ev):
                    idx = {r[ek]: r for r in rows}
                    out = [{**r, **{src[k]: idx[r[gk]][src[k]] for k in missing}} for r in last]
                    return out, {'from_statement': i, 'columns': {k: src[k] for k in missing},
                                 'joined_on': {'earlier_statement_column': ek, 'last_statement_column': gk}}
    return None, None


class Controlled3(F2.Controlled2):

    def inventory(self, label):
        inv = super().inventory(label)
        inv['code_hashes']['rc_controlled3.py'] = C.file_sha256(HERE / 'rc_controlled3.py')
        return inv

    def replay(self, fw, stmts):
        if fw != 'django':
            return super().replay(fw, stmts)
        results, rows = [], None
        for st in stmts:
            with self.dconn.cursor() as c:
                c.execute(st['sql'], st['params'])
                if c.description:
                    rows, _ = self.rows_from_cursor(c)
                    results.append(rows)
        self._g_results = results
        if rows and len(results) > 1 and self._g_columns:
            have = {str(c).lower() for c in rows[0]}
            missing = [k for k in self._g_columns if str(k).lower() not in have]
            if missing:
                out, how = assemble_ci(rows, results[:-1], missing)
                if out is not None:
                    self._g_assembly = how
                    return out
        return rows


if __name__ == '__main__':
    F1.Controlled = Controlled3        # F1.main() constructs the runner by this name
    F1.main()
