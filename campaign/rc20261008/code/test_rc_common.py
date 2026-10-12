"""Local checks of the frozen result policy; no database."""
import datetime as dt
from decimal import Decimal
import rc_common as C

def r11(k, v): return {'ps_partkey': k, 'value': v}

def test_exact_and_aliases():
    a = [{'orderpriority': '1-URGENT', 'order_count': 5}]
    b = [{'o_orderpriority': '1-URGENT', 'ORDER_COUNT': Decimal(5)}]
    assert C.compare(4, a, b)['classification'] == 'exact'

def test_date_normalisation():
    a = [{'o_year': 1995, 'mkt_share': Decimal('0.03')}]
    assert C.compare(8, a, a)['classification'] == 'exact'
    x = [{'l_orderkey': 1, 'revenue': Decimal('1.5'), 'o_orderdate': dt.date(1995, 3, 1), 'o_shippriority': 0}]
    y = [{'l_orderkey': 1, 'revenue': Decimal('1.50'), 'o_orderdate': dt.datetime(1995, 3, 1), 'o_shippriority': 0}]
    assert C.compare(3, x, y)['classification'] == 'exact'

def test_tie_permutation_accepted():
    a = [r11(1, Decimal('10')), r11(2, Decimal('5')), r11(3, Decimal('5')), r11(4, Decimal('1'))]
    b = [r11(1, Decimal('10')), r11(3, Decimal('5')), r11(2, Decimal('5')), r11(4, Decimal('1'))]
    c = C.compare(11, a, b)
    assert c['classification'] == 'tie_equivalent' and c['accepted']

def test_untied_swap_rejected():
    a = [r11(1, Decimal('10')), r11(2, Decimal('5'))]
    b = [r11(2, Decimal('5')), r11(1, Decimal('10'))]
    assert C.compare(11, a, b)['classification'] == 'mismatch'

def test_value_difference_rejected_no_rounding():
    a = [{'revenue': Decimal('123.4500')}]
    b = [{'revenue': Decimal('123.45')}]
    assert C.compare(6, a, b)['classification'] == 'exact'
    b2 = [{'revenue': Decimal('123.46')}]
    assert C.compare(6, a, b2)['classification'] == 'numeric_mismatch'  # v3: rejected, numeric-only

def test_float_representation():
    a = [{'revenue': Decimal('0.1')}]
    assert C.compare(6, a, [{'revenue': 0.1}])['classification'] == 'numeric_representation'
    assert C.compare(6, a, [{'revenue': 0.1000000001}])['classification'] == 'numeric_mismatch'  # v3: rejected, numeric-only

def test_duplicates_kept():
    a = [r11(1, Decimal('5')), r11(1, Decimal('5'))]
    b = [r11(1, Decimal('5'))]
    assert C.compare(11, a, b)['classification'] == 'mismatch'

def test_schema_error():
    assert C.compare(6, [{'rev': 1}], [{'revenue': 1}])['classification'] == 'schema_error'
    assert C.compare(6, [], [], ['revenue'], ['revenue'])['classification'] == 'exact'
    assert C.compare(6, [], [], None, ['revenue'])['classification'] == 'schema_error'

def test_limit_boundary():
    row = lambda k, rev: {'l_orderkey': k, 'revenue': Decimal(rev), 'o_orderdate': dt.date(1995, 1, 1), 'o_shippriority': 0}
    a = [row(i, 100 - i) for i in range(9)] + [row(50, 1)]
    b = [row(i, 100 - i) for i in range(9)] + [row(51, 1)]
    assert C.compare(3, a, b)['classification'] == 'limit_boundary_tie'
    # Q21's key includes s_name, so different names are not a tie.
    x = [{'s_name': f'a{i:03d}', 'numwait': 2} for i in range(99)] + [{'s_name': 'z1', 'numwait': 1}]
    y = [{'s_name': f'a{i:03d}', 'numwait': 2} for i in range(99)] + [{'s_name': 'z2', 'numwait': 1}]
    assert C.compare(21, x, y)['classification'] == 'mismatch'

def test_bool_not_int():
    assert C.value_relation(True, 1) == 'different'

def test_williams_and_plan():
    assert C.verify_williams()
    s1, p1 = C.block_plan('x'); s2, p2 = C.block_plan('x')
    assert (s1, p1) == (s2, p2) and sorted(p1[:4]) == [0, 1, 2, 3]

def test_typed_roundtrip():
    v = {'a': Decimal('1.20'), 'b': dt.date(2020, 1, 2), 'c': dt.datetime(2020, 1, 2, 3, 4), 'd': 1.5, 'e': None}
    assert C.untyped(C.typed(v)) == v and C.digest(v) == C.digest(C.untyped(C.typed(v)))

def test_scale_equivalence_v2_only():
    a = [{'promo_revenue': Decimal('16.380778')}]
    f = [{'promo_revenue': 16.380778626378337}]
    d = [{'promo_revenue': Decimal('16.380778626395539276927593164145946502685546875')}]
    assert C.compare(14, a, f)['classification'] == 'scale_equivalent'
    assert C.compare(14, a, d)['classification'] == 'scale_equivalent'
    assert C.compare(14, a, f, policy=C.POLICY_V1)['classification'] == 'mismatch'
    assert C.compare(14, [{'promo_revenue': Decimal('16.380779')}], f)['classification'] == 'scale_equivalent'
    assert C.compare(14, [{'promo_revenue': Decimal('16.380777')}], f)['classification'] == 'numeric_mismatch'  # v3: rejected, numeric-only
    # money scale (2 digits) never relaxed
    assert C.compare(6, [{'revenue': Decimal('123.45')}], [{'revenue': 123.4512}])['classification'] == 'numeric_mismatch'  # v3: rejected, numeric-only
    # two fine values that differ stay different
    assert C.compare(14, d, f)['classification'] == 'numeric_mismatch'  # v3: rejected, numeric-only

def test_numeric_mismatch_v3():
    a = [{'o_year': 1995, 'mkt_share': Decimal('0.04629733969631475796')}]
    b = [{'o_year': 1995, 'mkt_share': Decimal('0.04629733969364761170')}]
    c = C.compare(8, a, b)
    assert c['classification'] == 'numeric_mismatch' and not c['accepted'] and c['max_relative_difference'] < 1e-9
    assert C.compare(8, a, b, policy=C.POLICY_V2)['classification'] == 'mismatch'
    # a key differing is structural
    assert C.compare(8, a, [{'o_year': 1996, 'mkt_share': Decimal('0.04629733969631475796')}])['classification'] == 'mismatch'
    # strings differing is structural
    x = [{'n_name': 'PERU', 'revenue': Decimal('1.00')}]
    assert C.compare(5, x, [{'n_name': 'CHINA', 'revenue': Decimal('1.00')}])['classification'] == 'mismatch'

if __name__ == '__main__':
    import sys
    fails = 0
    for k, f in list(globals().items()):
        if k.startswith('test_'):
            try: f(); print('ok  ', k)
            except AssertionError as e: fails += 1; print('FAIL', k, e)
    sys.exit(1 if fails else 0)
