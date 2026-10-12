"""
TPC-C Transaction 5: StockLevel
Checks stock level for items
"""
from django.db import transaction
from django.db.models import Count, Q
import random

from tpcc_config import DISTRICTS_PER_WAREHOUSE, WAREHOUSES


def run_transaction_orm(using='default'):
    """
    Execute TPC-C T5 (StockLevel) via Django ORM
    """
    from django_app.tpcc_models import District, Order, OrderLine, Stock

    # Was: w_id = randint(1, 10), d_id = randint(1, 10) against a 100-warehouse
    # database, so this transaction only ever scanned a tenth of the stock
    # table. Ranges now come from tpcc_config.
    w_id = random.randint(1, WAREHOUSES)
    d_id = random.randint(1, DISTRICTS_PER_WAREHOUSE)
    # The stock threshold is fixed at 10..20 by the specification and does not
    # scale with the database, so it stays a literal.
    threshold = random.randint(10, 20)

    try:
        # Was: no explicit transaction, so the district read, the order read,
        # the order-line read and the stock count each ran in their own
        # autocommit transaction against a possibly different database state.
        with transaction.atomic(using=using):
            # Get district
            district = District.objects.using(using).get(d_w_id=w_id, d_id=d_id)

            # Get last L orders (L = 20 in TPC-C spec)
            last_orders = Order.objects.using(using).filter(
                o_w_id=w_id, o_d_id=d_id
            ).order_by('-o_id')[:20]

            if not last_orders:
                return {
                    'w_id': w_id,
                    'd_id': d_id,
                    'threshold': threshold,
                    'low_stock_count': 0
                }

            # Get order IDs
            order_ids = [o.o_id for o in last_orders]

            # Get distinct items from these orders
            order_lines = OrderLine.objects.using(using).filter(
                ol_w_id=w_id, ol_d_id=d_id, ol_o_id__in=order_ids
            ).values('ol_i_id').distinct()

            item_ids = [ol['ol_i_id'] for ol in order_lines]

            # Count items with stock below threshold
            low_stock_count = Stock.objects.using(using).filter(
                s_w_id=w_id, s_i_id__in=item_ids, s_quantity__lt=threshold
            ).count()

            return {
                'w_id': w_id,
                'd_id': d_id,
                'threshold': threshold,
                'items_checked': len(item_ids),
                'low_stock_count': low_stock_count
            }
    except Exception:
        # Was: `return {'error': str(e)}`, which reported a failed transaction as
        # a completed one. See t1_neworder.py for the full reasoning.
        raise


def run_transaction_sql(connection):
    """
    Execute TPC-C T5 (StockLevel) via direct SQL
    """
    import random

    # Was: w_id = randint(1, 10), d_id = randint(1, 10). Same problem as the ORM
    # path above.
    w_id = random.randint(1, WAREHOUSES)
    d_id = random.randint(1, DISTRICTS_PER_WAREHOUSE)
    # Threshold is a specification constant, not a key range. See above.
    threshold = random.randint(10, 20)

    # Was: no explicit transaction. See the ORM path above.
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            from .db_utils import get_table_name, get_any_operator, get_limit_clause
            order_table = get_table_name(connection, 'order')
            any_op, format_func = get_any_operator(connection)
            limit_clause = get_limit_clause(connection, 20)

            cursor.execute(f"""
                SELECT o_id FROM {order_table}
                WHERE o_w_id = %s AND o_d_id = %s
                ORDER BY o_id DESC
                {limit_clause}
            """, [w_id, d_id])

            order_rows = cursor.fetchall()
            if not order_rows:
                return {
                    'w_id': w_id,
                    'd_id': d_id,
                    'threshold': threshold,
                    'low_stock_count': 0
                }

            order_ids = [row[0] for row in order_rows]

            # Get distinct items (handle vendor differences)
            if any_op == 'IN':
                placeholders, params = format_func(order_ids)
                cursor.execute(f"""
                    SELECT DISTINCT ol_i_id FROM order_line
                    WHERE ol_w_id = %s AND ol_d_id = %s AND ol_o_id IN ({placeholders})
                """, [w_id, d_id] + params)
            elif connection.vendor == 'oracle':
                # Oracle: use IN with expanded placeholders (Oracle doesn't handle ANY with lists well)
                placeholders = ','.join(['%s'] * len(order_ids))
                cursor.execute(f"""
                    SELECT DISTINCT ol_i_id FROM order_line
                    WHERE ol_w_id = %s AND ol_d_id = %s AND ol_o_id IN ({placeholders})
                """, [w_id, d_id] + order_ids)
            else:
                # PostgreSQL: use ANY with array parameter
                placeholders, params = format_func(order_ids)
                cursor.execute(f"""
                    SELECT DISTINCT ol_i_id FROM order_line
                    WHERE ol_w_id = %s AND ol_d_id = %s AND ol_o_id = ANY({placeholders})
                """, [w_id, d_id] + params)

            item_rows = cursor.fetchall()
            item_ids = [row[0] for row in item_rows]

            if not item_ids:
                return {
                    'w_id': w_id,
                    'd_id': d_id,
                    'threshold': threshold,
                    'low_stock_count': 0
                }

            # Count low stock items (handle vendor differences)
            if any_op == 'IN':
                placeholders, params = format_func(item_ids)
                cursor.execute(f"""
                    SELECT COUNT(*) FROM stock
                    WHERE s_w_id = %s AND s_i_id IN ({placeholders}) AND s_quantity < %s
                """, [w_id] + params + [threshold])
            elif connection.vendor == 'oracle':
                # Oracle: use IN with expanded placeholders
                placeholders = ','.join(['%s'] * len(item_ids))
                cursor.execute(f"""
                    SELECT COUNT(*) FROM stock
                    WHERE s_w_id = %s AND s_i_id IN ({placeholders}) AND s_quantity < %s
                """, [w_id] + item_ids + [threshold])
            else:
                placeholders, params = format_func(item_ids)
                cursor.execute(f"""
                    SELECT COUNT(*) FROM stock
                    WHERE s_w_id = %s AND s_i_id = {any_op}({placeholders}) AND s_quantity < %s
                """, [w_id] + params + [threshold])

            low_stock_row = cursor.fetchone()
            low_stock_count = low_stock_row[0] if low_stock_row else 0

            return {
                'w_id': w_id,
                'd_id': d_id,
                'threshold': threshold,
                'items_checked': len(item_ids),
                'low_stock_count': low_stock_count
            }


def get_transaction_info():
    """Return metadata about this transaction"""
    return {
        'number': 5,
        'name': 'StockLevel',
        'complexity': 'Simple',
        'description': 'Checks stock level for items',
        'tables': ['district', 'order', 'order_line', 'stock'],
        'writes': 0,
        'reads': 3,
    }
