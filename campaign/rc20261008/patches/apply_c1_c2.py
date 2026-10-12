"""Apply the two confirmed TPC-C baseline corrections in the src-c worktree."""
from pathlib import Path
import sys
root = Path(sys.argv[1])
p = root / "django_app/tpcc_queries/t2_payment.py"; s = p.read_text()
old = '''            # Prepare h_data (truncate to 24 chars max)
            h_data = f"C{c_id}P{payment:.2f}"[:24]'''
new = '''            # Prepare h_data (truncate to 24 chars max). The same text the
            # other three Payment paths write: this baseline wrote
            # "C<c_id>P<payment:.2f>", so for identical inputs its committed
            # HISTORY row differed from the ORM path's in h_data alone
            # (campaign rc20261008 transaction pilot, Oracle T2 blocks 1-2).
            h_data = f"Customer {c_id} paid {payment}"[:24]'''
assert s.count(old) == 1, "t2 pattern"; p.write_text(s.replace(old, new))
p = root / "sqlalchemy_app/tpcc_queries/t3.py"; s = p.read_text()
old = '''        session.commit()
        return {
            'w_id': w_id, 'd_id': d_id, 'c_id': c_id,
            'c_first': customer_row[0], 'c_last': customer_row[1],
            'c_balance': float(customer_row[2]),
            'o_id': order_row[0],
            'o_entry_d': order_row[1].isoformat() if order_row[1] else None,
            'o_carrier_id': order_row[2]
        }'''
new = '''        # Order-Status returns the order lines (TPC-C 2.6.2.2). This baseline
        # stopped after the ORDER row, so it did less work than the ORM path
        # it was compared with (campaign rc20261008 transaction pilot:
        # statements touched customer, order vs customer, order, order_line).
        result = session.execute(text("""
            SELECT ol_i_id, ol_supply_w_id, ol_quantity, ol_amount, ol_delivery_d
            FROM order_line
            WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id = :o_id
            ORDER BY ol_number
        """), {'w_id': w_id, 'd_id': d_id, 'o_id': order_row[0]})
        order_lines = result.fetchall()

        session.commit()
        return {
            'w_id': w_id, 'd_id': d_id, 'c_id': c_id,
            'c_first': customer_row[0], 'c_last': customer_row[1],
            'c_balance': float(customer_row[2]),
            'o_id': order_row[0],
            'o_entry_d': order_row[1].isoformat() if order_row[1] else None,
            'o_carrier_id': order_row[2],
            'order_lines': len(order_lines)
        }'''
assert s.count(old) == 1, "t3 pattern"; p.write_text(s.replace(old, new))
print("applied")
