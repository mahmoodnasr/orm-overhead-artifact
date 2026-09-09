"""
TPC-C Transaction 1: NewOrder
Creates a new order transaction
"""

from django.db import transaction
from django.db.models import F
from decimal import Decimal
from datetime import datetime
import random

from tpcc_config import ITEMS, LOCK_DISTRICT, district_lock_sql, pick_keys


def run_transaction_orm(using="default"):
    """
    Execute TPC-C T1 (NewOrder) via Django ORM

    This transaction creates a new order with random parameters.
    """
    from django_app.tpcc_models import (
        Warehouse,
        District,
        Customer,
        Item,
        Stock,
        Order,
        NewOrder,
        OrderLine,
    )

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000),
    # ol_cnt = randint(5, 15), with the ranges written into this file. The
    # database is loaded with 100 warehouses, so drawing w_id from 1..10 confined
    # every worker to the same 10 warehouse rows and the measured throughput was
    # largely a measure of contention on those rows. The ranges now come from
    # tpcc_config so both frameworks draw from the same key space.
    w_id, d_id, c_id, ol_cnt = pick_keys(random)

    try:
        # Was: no explicit transaction, so every statement below committed
        # separately under autocommit. TPC-C treats New-Order as a single
        # transaction, and the per-statement commits also gave Django a
        # different amount of durable work per business transaction than
        # SQLAlchemy, which committed once.
        with transaction.atomic(using=using):
            # Get warehouse and district
            warehouse = Warehouse.objects.using(using).get(w_id=w_id)

            district_qs = District.objects.using(using)
            if LOCK_DISTRICT:
                # Was: an unlocked read of the district row followed by an F()
                # increment, while SQLAlchemy took SELECT ... FOR UPDATE on the
                # same row. The two sides therefore serialised differently on
                # the hottest row in the workload. tpcc_config.LOCK_DISTRICT now
                # selects one policy for both frameworks.
                district_qs = district_qs.select_for_update()
            district = district_qs.get(d_w_id=w_id, d_id=d_id)

            customer = Customer.objects.using(using).get(
                c_w_id=w_id, c_d_id=d_id, c_id=c_id
            )

            # Get next order ID and increment
            next_o_id = district.d_next_o_id
            District.objects.using(using).filter(d_w_id=w_id, d_id=d_id).update(
                d_next_o_id=F("d_next_o_id") + 1
            )

            # Create order
            order = Order.objects.using(using).create(
                o_id=next_o_id,
                o_d_id=d_id,
                o_w_id=warehouse,
                o_c_id=c_id,
                o_entry_d=datetime.now(),
                o_carrier_id=None,
                o_ol_cnt=ol_cnt,
                o_all_local=1,
            )

            # Create new_order entry
            NewOrder.objects.using(using).create(
                no_o_id=next_o_id, no_d_id=d_id, no_w_id=warehouse
            )

            # Create order lines
            total_amount = Decimal("0.00")
            for ol_number in range(1, ol_cnt + 1):
                # Was: randint(1, 100000) with the item count written into this
                # file. ITEMS carries the same number, but from the shared config,
                # so a differently loaded database cannot silently make the two
                # frameworks read different item ranges.
                ol_i_id = random.randint(1, ITEMS)
                ol_supply_w_id = w_id  # Supply warehouse
                # Order-line quantity is fixed at 1..10 by the specification and
                # does not scale with the database, so it stays a literal.
                ol_quantity = random.randint(1, 10)

                # Get item and stock
                item = Item.objects.using(using).get(i_id=ol_i_id)
                stock = Stock.objects.using(using).get(s_w_id=w_id, s_i_id=ol_i_id)

                # Calculate amount
                ol_amount = item.i_price * ol_quantity

                # Create order line
                OrderLine.objects.using(using).create(
                    ol_o_id=next_o_id,
                    ol_d_id=d_id,
                    ol_w_id=warehouse,
                    ol_number=ol_number,
                    ol_i_id=ol_i_id,
                    ol_supply_w_id=ol_supply_w_id,
                    ol_delivery_d=None,
                    ol_quantity=ol_quantity,
                    ol_amount=ol_amount,
                    ol_dist_info=stock.s_dist_01,
                )

                total_amount += ol_amount

            return {
                "w_id": w_id,
                "d_id": d_id,
                "c_id": c_id,
                "o_id": next_o_id,
                "ol_cnt": ol_cnt,
                "total_amount": float(total_amount),
            }
    except Exception:
        # Was: `return {'error': str(e)}`. A returned dict is indistinguishable
        # from a completed transaction to a harness that measures what came back,
        # so every failure here was recorded as a successful New-Order and
        # Django's error rate read as zero. That hides deadlocks and
        # serialization failures, which are the whole point of measuring a
        # locking policy. SQLAlchemy's paths propagate and Django's own raw-SQL
        # path propagates, so this was also Django disagreeing with itself.
        # The atomic block has already rolled back by the time we get here.
        raise


def run_transaction_sql(connection):
    """
    Execute TPC-C T1 (NewOrder) via direct SQL
    """
    import random
    from datetime import datetime
    from .db_utils import get_table_name, get_current_timestamp

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000)
    # here and ol_cnt = randint(5, 15) further down. Same 10-warehouse problem as
    # the ORM path above. ol_cnt is now drawn here with the other keys, and it
    # bounds the order-line loop below as well as going into the ORDER row.
    w_id, d_id, c_id, ol_cnt = pick_keys(random)

    # Get vendor-specific table name and timestamp function
    order_table = get_table_name(connection, "order")
    now_func = get_current_timestamp(connection)

    # Was: no explicit transaction. See the ORM path above.
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            # Was: this path read the district, wrote ORDER and NEW_ORDER, and
            # stopped. It never read WAREHOUSE, CUSTOMER, ITEM or STOCK and never
            # wrote a single ORDER_LINE, so it performed roughly a third of a
            # New-Order while the ORM path performed all of it. The overhead
            # column for T1 was therefore comparing a whole transaction against a
            # fragment, and the ORM necessarily looked slower. The statements
            # below now mirror run_transaction_orm one for one, in the same
            # order, so the difference between the two is the framework.
            cursor.execute(
                """
                SELECT w_tax FROM warehouse WHERE w_id = %s
            """,
                [w_id],
            )
            if cursor.fetchone() is None:
                raise LookupError(
                    f"warehouse {w_id} not found; tpcc_config "
                    f"does not describe the loaded database"
                )

            # Was: an unlocked read, while SQLAlchemy's ORM path held
            # SELECT ... FOR UPDATE on this row. Both raw-SQL paths now follow
            # tpcc_config.LOCK_DISTRICT, the same as the ORM paths.
            # FOR UPDATE is not portable; see tpcc_config.district_lock_sql.
            hint, lock_clause = district_lock_sql(connection.vendor)
            cursor.execute(
                f"""
                SELECT d_next_o_id FROM district{hint} WHERE d_w_id = %s AND d_id = %s{lock_clause}
            """,
                [w_id, d_id],
            )
            row = cursor.fetchone()
            if not row:
                # Was: `return {'error': 'District not found'}`. Returning a dict
                # made a failed transaction indistinguishable from a completed
                # one; see the ORM path's handler.
                raise LookupError(f"district ({w_id}, {d_id}) not found")

            next_o_id = row[0]

            cursor.execute(
                """
                SELECT c_discount FROM customer WHERE c_w_id = %s AND c_d_id = %s AND c_id = %s
            """,
                [w_id, d_id, c_id],
            )
            if cursor.fetchone() is None:
                raise LookupError(f"customer ({w_id}, {d_id}, {c_id}) not found")

            # Increment next order ID
            cursor.execute(
                """
                UPDATE district SET d_next_o_id = d_next_o_id + 1 WHERE d_w_id = %s AND d_id = %s
            """,
                [w_id, d_id],
            )

            # Create order. The timestamp is the only vendor difference and
            # get_current_timestamp already carries it; this was previously an
            # if/else on connection.vendor whose two branches were identical.
            cursor.execute(
                f"""
                INSERT INTO {order_table} (o_id, o_d_id, o_w_id, o_c_id, o_entry_d, o_carrier_id, o_ol_cnt, o_all_local)
                VALUES (%s, %s, %s, %s, {now_func}, NULL, %s, 1)
            """,
                [next_o_id, d_id, w_id, c_id, ol_cnt],
            )

            # Create new_order entry
            cursor.execute(
                """
                INSERT INTO new_order (no_o_id, no_d_id, no_w_id)
                VALUES (%s, %s, %s)
            """,
                [next_o_id, d_id, w_id],
            )

            # The order lines. Same loop, same draws in the same order and the
            # same two reads per line as the ORM path, so the two consume the
            # same values from `random` and touch the same rows.
            total_amount = Decimal("0.00")
            for ol_number in range(1, ol_cnt + 1):
                ol_i_id = random.randint(1, ITEMS)
                ol_supply_w_id = w_id
                ol_quantity = random.randint(1, 10)

                cursor.execute("SELECT i_price FROM item WHERE i_id = %s", [ol_i_id])
                item_row = cursor.fetchone()
                if item_row is None:
                    raise LookupError(f"item {ol_i_id} not found")
                i_price = item_row[0]

                cursor.execute(
                    """
                    SELECT s_dist_01 FROM stock WHERE s_w_id = %s AND s_i_id = %s
                """,
                    [w_id, ol_i_id],
                )
                stock_row = cursor.fetchone()
                if stock_row is None:
                    raise LookupError(f"stock ({w_id}, {ol_i_id}) not found")
                ol_dist_info = stock_row[0]

                ol_amount = i_price * ol_quantity

                cursor.execute(
                    """
                    INSERT INTO order_line (ol_o_id, ol_d_id, ol_w_id, ol_number,
                                            ol_i_id, ol_supply_w_id, ol_delivery_d,
                                            ol_quantity, ol_amount, ol_dist_info)
                    VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, %s)
                """,
                    [
                        next_o_id,
                        d_id,
                        w_id,
                        ol_number,
                        ol_i_id,
                        ol_supply_w_id,
                        ol_quantity,
                        ol_amount,
                        ol_dist_info,
                    ],
                )

                total_amount += ol_amount

            return {
                "w_id": w_id,
                "d_id": d_id,
                "c_id": c_id,
                "o_id": next_o_id,
                "ol_cnt": ol_cnt,
                "total_amount": float(total_amount),
            }


def get_transaction_info():
    """Return metadata about this transaction"""
    return {
        "number": 1,
        "name": "NewOrder",
        "complexity": "Medium",
        "description": "Creates a new order transaction",
        "tables": [
            "warehouse",
            "district",
            "customer",
            "item",
            "stock",
            "order",
            "new_order",
            "order_line",
        ],
        "writes": 3,
        "reads": 5,
    }
