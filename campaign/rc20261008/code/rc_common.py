"""Shared evidence, result-check and record helpers for campaign rc20261008.

No database dependency. Imported by the analytical runner, the transaction
runner, the offline verifier and the analysis, so that a record is written,
re-read and re-checked by one implementation of each rule.

Result policy (frozen in protocol rc20261008-A-v1 before any execution):

  E1 exact     named columns (canonical names), Python equality of every value,
               duplicates kept, strict row order. Python equality is exact
               across int/Decimal/float: Decimal('0.1') != 0.1.
  E2 date      a naive datetime at 00:00:00 equals the date with the same
               Y-M-D. Oracle returns DATE columns as datetimes through a raw
               cursor while the ORM converts them to dates; this is the one
               value normalisation applied before comparison.
  E3 ties      rows whose ORDER BY key tuples are equal may legally appear in
               either order. Accepted as tie_equivalent only when the sequence
               of key tuples is identical and every run of equal keys is an
               identical multiset of complete rows. Never sorts inside a row.
  E4 numeric   a float on one side and an exact number on the other compare as
               representation-equal only if float(exact) == the float, i.e. the
               float is the correctly rounded double of the exact value. No
               tolerance, no rounding. Reported separately.
  R  review    a LIMIT query whose final run of equal keys differs is
               limit_boundary_tie; any other difference is mismatch. Neither is
               accepted by the runner.

Amendment v2 (added 2026-10-08 after pilot P-v1 observed it on Commercial System A Q14,
before any main-phase execution; v1 decisions keep their v1 classification):

  E5 scale    an exact Decimal d whose own scale s has at least 4 fractional
               digits, against a value x carrying more fractional digits (a
               float, or a Decimal of larger scale): scale_equivalent if x,
               expanded exactly and cut to s digits by truncation or by
               round-half-even, equals d. Observed cause: Commercial System A types
               100.00 * SUM(..) / SUM(..) as DECIMAL with scale 6 and truncates
               the quotient (16.380778), while both ORMs bind 100.0 as a float
               and return 16.3807786263... The rule is exact at the baseline's
               own declared scale; it never applies to values with fewer than 4
               fractional digits (money columns must agree exactly), and pairs
               accepted under it are counted separately.

Amendment v3 (2026-10-08, after the PostgreSQL pilot, before any main-phase
execution). Acceptance is unchanged; only rejected pairs are split:

  numeric_mismatch  same row count and order, every non-numeric value and
               every ORDER BY key identical, and only numeric values differ.
               Rejected, with the largest relative difference recorded. Seen:
               SQLAlchemy 2.0 renders `/` on Numeric(15,2) operands as
               `x / CAST(y AS NUMERIC(15, 2))`, rounding a scale-4 denominator,
               so Q8 and Q14 differ from the baseline near the 11th digit.
  mismatch     anything else (rows, keys, strings, counts). Rejected.
"""
import datetime as dt
from decimal import Decimal
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

POLICY_VERSION = 'rc20261008-results-v3'
POLICY_V1 = 'rc20261008-results-v1'
POLICY_V2 = 'rc20261008-results-v2'

EXPECTED = {
 1: 'l_returnflag l_linestatus sum_qty sum_base_price sum_disc_price sum_charge avg_qty avg_price avg_disc count_order',
 2: 's_acctbal s_name n_name p_partkey p_mfgr s_address s_phone s_comment',
 3: 'l_orderkey revenue o_orderdate o_shippriority', 4: 'o_orderpriority order_count',
 5: 'n_name revenue', 6: 'revenue', 7: 'supp_nation cust_nation l_year revenue',
 8: 'o_year mkt_share', 9: 'nation o_year sum_profit',
 10: 'c_custkey c_name revenue c_acctbal n_name c_address c_phone c_comment',
 11: 'ps_partkey value', 12: 'l_shipmode high_line_count low_line_count',
 13: 'c_count custdist', 14: 'promo_revenue',
 15: 's_suppkey s_name s_address s_phone total_revenue',
 16: 'p_brand p_type p_size supplier_cnt', 17: 'avg_yearly',
 18: 'c_name c_custkey o_orderkey o_orderdate o_totalprice total_qty',
 19: 'revenue', 20: 's_name s_address', 21: 's_name numwait',
 22: 'cntrycode numcust totacctbal',
}
# Output names the retained implementations use for the specification's
# columns. Reviewed against the sources by the October 8 draft; a name not in
# EXPECTED after mapping is a schema error, never silently ignored.
ALIASES = {
 1: {'returnflag': 'l_returnflag', 'linestatus': 'l_linestatus'},
 3: {'orderkey': 'l_orderkey', 'orderkey__orderdate': 'o_orderdate', 'orderkey__shippriority': 'o_shippriority'},
 4: {'orderpriority': 'o_orderpriority'}, 5: {'total_revenue': 'revenue'},
 10: {'total_revenue': 'revenue'}, 12: {'shipmode': 'l_shipmode'},
}
# ORDER BY of the specification, in canonical names; '-' marks DESC. Single-row
# aggregates have no key. LIMIT from the specification.
ORDER_KEYS = {
 1: ['l_returnflag', 'l_linestatus'], 2: ['-s_acctbal', 'n_name', 's_name', 'p_partkey'],
 3: ['-revenue', 'o_orderdate'], 4: ['o_orderpriority'], 5: ['-revenue'], 6: [],
 7: ['supp_nation', 'cust_nation', 'l_year'], 8: ['o_year'], 9: ['nation', '-o_year'],
 10: ['-revenue'], 11: ['-value'], 12: ['l_shipmode'], 13: ['-custdist', '-c_count'], 14: [],
 15: ['s_suppkey'], 16: ['-supplier_cnt', 'p_brand', 'p_type', 'p_size'], 17: [],
 18: ['-o_totalprice', 'o_orderdate'], 19: [], 20: ['s_name'], 21: ['-numwait', 's_name'],
 22: ['cntrycode'],
}
LIMITS = {2: 100, 3: 10, 10: 20, 18: 100, 21: 100}
ACCEPTED_CLASSES = ('exact', 'tie_equivalent', 'numeric_representation', 'scale_equivalent')


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def stamps():
    u = now_utc()
    cairo = u.astimezone(dt.timezone(dt.timedelta(hours=3)))
    try:
        from zoneinfo import ZoneInfo
        cairo = u.astimezone(ZoneInfo('Africa/Cairo'))
    except Exception:
        pass
    return {'utc': u.isoformat(), 'cairo': cairo.isoformat()}


# ------------------------------------------------------------------ typed JSON
def typed(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {'type': 'float', 'value': repr(value)}
        return {'type': 'float', 'value': repr(value)}
    if isinstance(value, Decimal):
        return {'type': 'Decimal', 'value': str(value)}
    if isinstance(value, dt.datetime):
        return {'type': 'datetime', 'value': value.isoformat()}
    if isinstance(value, dt.date):
        return {'type': 'date', 'value': value.isoformat()}
    if isinstance(value, dt.time):
        return {'type': 'time', 'value': value.isoformat()}
    if isinstance(value, dt.timedelta):
        return {'type': 'timedelta', 'value': repr(value.total_seconds())}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'type': 'bytes', 'hex': bytes(value).hex()}
    if isinstance(value, dict):
        return {str(k): typed(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [typed(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return {'type': 'set', 'value': sorted((typed(v) for v in value), key=repr)}
    return {'type': 'repr:' + type(value).__name__, 'value': repr(value)}


_UNTYPE = {'float': float, 'Decimal': Decimal, 'date': dt.date.fromisoformat,
           'datetime': dt.datetime.fromisoformat, 'time': dt.time.fromisoformat}


def untyped(value):
    if isinstance(value, list):
        return [untyped(v) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {'type', 'value'} and value['type'] in _UNTYPE:
        return _UNTYPE[value['type']](value['value'])
    if set(value) == {'type', 'hex'} and value['type'] == 'bytes':
        return bytes.fromhex(value['hex'])
    return {k: untyped(v) for k, v in value.items()}


def canonical_json(value):
    return json.dumps(typed(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _fsync_dir(path):
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def save(path, value, immutable=False):
    """Atomic write. immutable=True refuses to replace an existing record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        raise FileExistsError(f'immutable record already exists: {path}')
    raw = (json.dumps(typed(value), indent=1, ensure_ascii=False) + '\n').encode()
    if path.suffix == '.gz':
        raw = gzip.compress(raw, mtime=0)
    tmp = path.with_name(path.name + f'.pending-{os.getpid()}')
    with open(tmp, 'wb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if immutable:
        # link() fails if the target exists, so two writers cannot both win.
        os.link(tmp, path)
        os.unlink(tmp)
    else:
        os.replace(tmp, path)
    _fsync_dir(path.parent)
    return hashlib.sha256(raw).hexdigest()


def load(path, raw=False):
    p = Path(path)
    data = p.read_bytes()
    if p.suffix == '.gz':
        data = gzip.decompress(data)
    obj = json.loads(data)
    return obj if raw else untyped(obj)


def append_jsonl(path, value):
    line = (json.dumps(typed(value), ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


# -------------------------------------------------------------- result checks
def cname(q, col):
    s = str(col).lower()
    return ALIASES.get(q, {}).get(s, s)


def _norm_value(v):
    if isinstance(v, dt.datetime):
        if v.tzinfo is None and v.time() == dt.time():
            return v.date()                                   # E2
        return v
    return v


def canonical_rows(q, rows, columns=None):
    """Rows as dicts keyed by canonical names. Raises on any schema problem."""
    if not isinstance(rows, list):
        raise ValueError('result is not a complete list of rows')
    expected = EXPECTED[q].split()
    if not rows:
        names = [cname(q, c) for c in (columns or [])]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError(f'empty result without verified column names: {names}')
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('unnamed output row')
        names = [cname(q, c) for c in row]
        if len(names) != len(set(names)):
            raise ValueError(f'duplicate canonical column in {list(row)}')
        if set(names) != set(expected):
            raise ValueError(f'columns {names} != expected {expected}')
        out.append({cname(q, k): _norm_value(v) for k, v in row.items()})
    return out


def _is_num(v):
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _scale_equivalent(a, b):
    """E5: exact Decimal at its own scale (>= 4 digits) vs a more precise value."""
    from decimal import ROUND_DOWN, ROUND_HALF_EVEN
    for d, x in ((a, b), (b, a)):
        if not isinstance(d, Decimal) or not d.is_finite():
            continue
        s = -d.as_tuple().exponent
        if s < 4:
            continue
        if isinstance(x, float):
            if not math.isfinite(x):
                continue
            xd = Decimal(x)
        elif isinstance(x, Decimal) and x.is_finite():
            xd = x
        else:
            continue
        if -xd.as_tuple().exponent <= s:
            continue
        import decimal as _dec
        with _dec.localcontext() as ctx:
            ctx.prec = 400
            q = Decimal(1).scaleb(-s)
            if xd.quantize(q, rounding=ROUND_DOWN) == d or xd.quantize(q, rounding=ROUND_HALF_EVEN) == d:
                return True
    return False


_POLICY = {'v': POLICY_VERSION}


def value_relation(a, b):
    """'equal', 'numeric_representation', 'scale_equivalent' or 'different'."""
    if isinstance(a, bool) != isinstance(b, bool):
        return 'different'
    if a == b:
        if _is_num(a) and _is_num(b) and (isinstance(a, float) != isinstance(b, float)):
            return 'numeric_representation'                     # exact equality, float involved
        return 'equal'
    if _is_num(a) and _is_num(b) and (isinstance(a, float) != isinstance(b, float)):
        f, x = (a, b) if isinstance(a, float) else (b, a)
        try:
            if math.isfinite(f) and float(x) == f:
                return 'numeric_representation'                 # E4
        except (OverflowError, ValueError):
            pass
    if _POLICY['v'] != POLICY_V1 and _is_num(a) and _is_num(b) and _scale_equivalent(a, b):
        return 'scale_equivalent'
    return 'different'


_RANK = {'equal': 0, 'numeric_representation': 1, 'scale_equivalent': 2, 'different': 9}


def _worse(a, b):
    return a if _RANK[a] >= _RANK[b] else b


def _row_relation(q, x, y):
    worst = 'equal'
    for k in EXPECTED[q].split():
        r = value_relation(x[k], y[k])
        if r == 'different':
            return 'different'
        worst = _worse(worst, r)
    return worst


def _key(q, row):
    return tuple(row[k.lstrip('-')] for k in ORDER_KEYS[q])


def _groups(q, rows):
    out = []
    for row in rows:
        k = _key(q, row)
        if out and _keys_equal(out[-1][0], k):
            out[-1][1].append(row)
        else:
            out.append((k, [row]))
    return out


def _keys_equal(a, b):
    return len(a) == len(b) and all(value_relation(x, y) != 'different' for x, y in zip(a, b))


def _multiset_match(q, xs, ys):
    """Match rows of two tied groups one-to-one. Returns worst relation or None."""
    if len(xs) != len(ys):
        return None
    remaining = list(ys)
    worst = 'equal'
    for x in xs:
        hit = None
        for i, y in enumerate(remaining):
            r = _row_relation(q, x, y)
            if r != 'different':
                hit = (i, r)
                if r == 'equal':
                    break
        if hit is None:
            return None
        worst = _worse(worst, hit[1])
        remaining.pop(hit[0])
    return worst


def compare(q, left, right, left_columns=None, right_columns=None, policy=None):
    """Classify the relation of two complete results of query q."""
    _POLICY['v'] = policy or POLICY_VERSION
    try:
        return _compare(q, left, right, left_columns, right_columns)
    finally:
        _POLICY['v'] = POLICY_VERSION


def _compare(q, left, right, left_columns=None, right_columns=None):
    res = {'policy': _POLICY['v'], 'query': q, 'rows': [len(left) if isinstance(left, list) else None,
                                                          len(right) if isinstance(right, list) else None]}
    try:
        a = canonical_rows(q, left, left_columns)
        b = canonical_rows(q, right, right_columns)
    except Exception as exc:
        res.update(classification='schema_error', accepted=False, detail=str(exc))
        return res
    diffs = []
    if len(a) == len(b):
        worst = 'equal'
        for i, (x, y) in enumerate(zip(a, b)):
            r = _row_relation(q, x, y)
            if r == 'different':
                if len(diffs) < 10:
                    diffs.append({'row': i, 'left': x, 'right': y})
                worst = 'different'
            elif r != 'equal' and worst != 'different':
                worst = _worse(worst, r)
        if worst == 'equal':
            res.update(classification='exact', accepted=True)
            return res
        if worst in ('numeric_representation', 'scale_equivalent'):
            res.update(classification=worst, accepted=True)
            return res
    else:
        diffs.append({'row_count': [len(a), len(b)]})
    # E3: legal permutation of tied rows.
    if ORDER_KEYS[q] and len(a) == len(b):
        ga, gb = _groups(q, a), _groups(q, b)
        if len(ga) == len(gb) and all(_keys_equal(x[0], y[0]) for x, y in zip(ga, gb)):
            rels = [_multiset_match(q, x[1], y[1]) for x, y in zip(ga, gb)]
            if all(r is not None for r in rels):
                res.update(classification='tie_equivalent',
                           accepted=True, tie_groups=sum(1 for g in ga if len(g[1]) > 1),
                           value_relations_in_ties=sorted(set(rels)))
                return res
            if q in LIMITS and len(a) == LIMITS[q] and all(r is not None for r in rels[:-1]):
                res.update(classification='limit_boundary_tie', accepted=False,
                           differences=diffs)
                return res
    if _POLICY['v'] not in (POLICY_V1, POLICY_V2) and len(a) == len(b):
        keys = {k.lstrip('-') for k in ORDER_KEYS[q]}
        numeric_only, rel = True, 0.0
        for x, y in zip(a, b):
            for k in EXPECTED[q].split():
                if value_relation(x[k], y[k]) == 'different':
                    if k in keys or not (_is_num(x[k]) and _is_num(y[k])):
                        numeric_only = False
                        break
                    try:
                        xv, yv = Decimal(x[k]) if not isinstance(x[k], Decimal) else x[k], \
                            Decimal(y[k]) if not isinstance(y[k], Decimal) else y[k]
                        den = max(abs(xv), abs(yv))
                        rel = max(rel, float(abs(xv - yv) / den) if den else float('inf'))
                    except Exception:
                        rel = float('inf')
            if not numeric_only:
                break
        if numeric_only:
            res.update(classification='numeric_mismatch', accepted=False, differences=diffs,
                       max_relative_difference=rel)
            return res
    res.update(classification='mismatch', accepted=False, differences=diffs)
    return res


# ------------------------------------------------------------ Williams design
WILLIAMS = (
    ('django/sql', 'django/orm', 'sqlalchemy/sql', 'sqlalchemy/orm'),
    ('django/orm', 'sqlalchemy/orm', 'django/sql', 'sqlalchemy/sql'),
    ('sqlalchemy/orm', 'sqlalchemy/sql', 'django/orm', 'django/sql'),
    ('sqlalchemy/sql', 'django/sql', 'sqlalchemy/orm', 'django/orm'),
)
PATHS = ('django/sql', 'django/orm', 'sqlalchemy/sql', 'sqlalchemy/orm')


def verify_williams():
    for pos in range(4):
        assert sorted(s[pos] for s in WILLIAMS) == sorted(PATHS), pos
    pairs = [(s[i], s[i + 1]) for s in WILLIAMS for i in range(3)]
    assert len(pairs) == len(set(pairs)) == 12
    return True


def block_plan(seed_text):
    """Eight blocks: two independent seeded permutations of the four sequences.

    The seed is derived from text with SHA-256 so the plan is identical on every
    interpreter (run_block.py used hash(), which PYTHONHASHSEED randomises).
    """
    import random
    seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16)
    r = random.Random(seed)
    first, second = [0, 1, 2, 3], [0, 1, 2, 3]
    r.shuffle(first)
    r.shuffle(second)
    plan = first + second
    # Each cycle uses every sequence once, so position and adjacent-order
    # balance hold within each cycle of four blocks.
    assert sorted(plan[:4]) == sorted(plan[4:]) == [0, 1, 2, 3]
    return seed, plan


def orm_path_check(orm, sql):
    """ORM path must emit ORM-built SQL, never the handwritten statement (C1)."""
    st = orm.get('statements') or []
    out = {'statements': len(st)}
    if not st:
        out.update(passed=False, reason='no statement captured')
        return out
    if orm['framework'] == 'sqlalchemy' and any(s.get('text_clause') for s in st):
        out.update(passed=False, reason='text() statement on the ORM path')
        return out
    norm = lambda x: ' '.join(str(x).split()).lower()
    hand = {norm(s['sql']) for s in (sql.get('statements') or [])}
    if any(norm(s['sql']) in hand for s in st):
        out.update(passed=False, reason='ORM path issued the handwritten statement')
        return out
    out['passed'] = True
    return out
