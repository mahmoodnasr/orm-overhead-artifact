"""
TPC-C Transaction 4: Delivery
Processes delivery of orders
"""
from django.db import transaction
from django.db.models import F, Min
from datetime import datetime
import random

from tpcc_config import DISTRICTS_PER_WAREHOUSE, WAREHOUSES


def run_transaction_orm(using='default'):
    """
    Execute TPC-C T4 (Delivery) via Django ORM
    """
    from django_app.tpcc_models import NewOrder, Order, OrderLine, Customer

    # Was: w_id = randint(1, 10) against a 100-warehouse database, so every
    # worker delivered out of the same 10 warehouses. WAREHOUSES comes from
    # tpcc_config and tracks what was actually loaded.
    w_id = random.randint(1, WAREHOUSES)
    # The carrier id range is fixed at 1..10 by the specification and does not
    # scale with the database, so it stays a literal. It is only a coincidence
    # that it matches the old, incorrect warehouse range.
    carrier_id = random.randint(1, 10)

    try:
        # Was: no explicit transaction, so each district's order update, order
        # line update, customer update and new_order delete committed
        # separately. A failure part way through left some districts delivered
        # and the rest not, and each district's four writes were individually
        # durable rather than one unit.
        with transaction.atomic(using=using):
            # Get oldest new order for each district
            results = []
            # Was: range(1, 11) with the district count written into this file.
            for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
                # Get oldest new order
                new_order = NewOrder.objects.using(using).filter(
                    no_w_id=w_id, no_d_id=d_id
                ).order_by('no_o_id').first()

                if not new_order:
                    continue

                o_id = new_order.no_o_id

                # Get order
                order = Order.objects.using(using).get(
                    o_w_id=w_id, o_d_id=d_id, o_id=o_id
                )

                # Update order with carrier
                Order.objects.using(using).filter(
                    o_w_id=w_id, o_d_id=d_id, o_id=o_id
                ).update(o_carrier_id=carrier_id)

                # Update order lines with delivery date
                OrderLine.objects.using(using).filter(
                    ol_w_id=w_id, ol_d_id=d_id, ol_o_id=o_id
                ).update(ol_delivery_d=datetime.now())

                # Calculate total amount
                order_lines = OrderLine.objects.using(using).filter(
                    ol_w_id=w_id, ol_d_id=d_id, ol_o_id=o_id
                )
                total_amount = sum(float(ol.ol_amount) for ol in order_lines)

                # Update customer
                Customer.objects.using(using).filter(
                    c_w_id=w_id, c_d_id=d_id, c_id=order.o_c_id
                ).update(
                    c_balance=F('c_balance') + total_amount,
                    c_delivery_cnt=F('c_delivery_cnt') + 1
                )

                # Delete the new_order row through a filter on the whole key.
                # Was `new_order.delete()`. Django 4.2 cannot express TPC-C's
                # composite keys, so django_app/tpcc_models.py declares no_o_id
                # as the primary key; an instance delete would therefore issue
                # DELETE FROM new_order WHERE no_o_id = <id>, removing that order
                # number from every warehouse and district in the database
                # instead of the one row just delivered. See the module docstring
                # in tpcc_models.py.
                NewOrder.objects.using(using).filter(
                    no_w_id=w_id, no_d_id=d_id, no_o_id=o_id
                ).delete()

                results.append({
                    'd_id': d_id,
                    'o_id': o_id,
                    'total_amount': total_amount
                })

            return {
                'w_id': w_id,
                'carrier_id': carrier_id,
                'orders_delivered': len(results),
                'results': results
            }
    except Exception:
        # Was: `return {'error': str(e)}`, which reported a failed transaction as
        # a completed one. See t1_neworder.py for the full reasoning.
        raise


def run_transaction_sql(connection):
    """
    Execute TPC-C T4 (Delivery) via direct SQL
    """
    import random

    # Was: w_id = randint(1, 10) against a 100-warehouse database. Same problem
    # as the ORM path above.
    w_id = random.randint(1, WAREHOUSES)
    # Carrier id is a specification constant, not a key range. See above.
    carrier_id = random.randint(1, 10)

    # Was: no explicit transaction. See the ORM path above.
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            from .db_utils import get_table_name, get_current_timestamp
            order_table = get_table_name(connection, 'order')
            now_func = get_current_timestamp(connection)

            from .db_utils import get_limit_clause
            limit_clause = get_limit_clause(connection, 1)

            results = []
            # Was: range(1, 11) with the district count written into this file.
            for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
                # Get oldest new order
                cursor.execute(f"""
                    SELECT no_o_id FROM new_order
                    WHERE no_w_id = %s AND no_d_id = %s
                    ORDER BY no_o_id
                    {limit_clause}
                """, [w_id, d_id])

                row = cursor.fetchone()
                if not row:
                    continue

                o_id = row[0]

                # Update order
                cursor.execute(f"""
                    UPDATE {order_table} SET o_carrier_id = %s
                    WHERE o_w_id = %s AND o_d_id = %s AND o_id = %s
                """, [carrier_id, w_id, d_id, o_id])

                # Update order lines - handle Oracle separately
                if connection.vendor == 'oracle':
                    cursor.execute("""
                        UPDATE order_line SET ol_delivery_d = SYSDATE
                        WHERE ol_w_id = %s AND ol_d_id = %s AND ol_o_id = %s
                    """, [w_id, d_id, o_id])
                else:
                    cursor.execute(f"""
                        UPDATE order_line SET ol_delivery_d = {now_func}
                        WHERE ol_w_id = %s AND ol_d_id = %s AND ol_o_id = %s
                    """, [w_id, d_id, o_id])

                # Get total amount and customer
                cursor.execute(f"""
                    SELECT SUM(ol_amount), o_c_id FROM order_line, {order_table}
                    WHERE ol_w_id = %s AND ol_d_id = %s AND ol_o_id = %s
                    AND o_w_id = %s AND o_d_id = %s AND o_id = %s
                    GROUP BY o_c_id
                """, [w_id, d_id, o_id, w_id, d_id, o_id])

                total_row = cursor.fetchone()
                if total_row:
                    total_amount = float(total_row[0]) if total_row[0] else 0.0
                    c_id = total_row[1]

                    # Update customer
                    cursor.execute("""
                        UPDATE customer SET
                            c_balance = c_balance + %s,
                            c_delivery_cnt = c_delivery_cnt + 1
                        WHERE c_w_id = %s AND c_d_id = %s AND c_id = %s
                    """, [total_amount, w_id, d_id, c_id])

                # Delete new_order
                cursor.execute("""
                    DELETE FROM new_order
                    WHERE no_w_id = %s AND no_d_id = %s AND no_o_id = %s
                """, [w_id, d_id, o_id])

                results.append({
                    'd_id': d_id,
                    'o_id': o_id,
                    'total_amount': total_amount if total_row else 0.0
                })

            return {
                'w_id': w_id,
                'carrier_id': carrier_id,
                'orders_delivered': len(results),
                'results': results
            }


def get_transaction_info():
    """Return metadata about this transaction"""
    return {
        'number': 4,
        'name': 'Delivery',
        'complexity': 'Medium',
        'description': 'Processes delivery of orders',
        'tables': ['new_order', 'order', 'order_line', 'customer'],
        'writes': 4,
        'reads': 2,
    }
