"""
TPC-C Transaction 3: OrderStatus
Retrieves the status of a customer's last order
"""

from django.db import transaction
from django.db.models import F, Max
import random

from tpcc_config import pick_keys


def run_transaction_orm(using="default"):
    """
    Execute TPC-C T3 (OrderStatus) via Django ORM
    """
    from django_app.tpcc_models import Customer, Order, OrderLine

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # With 100 warehouses loaded, drawing w_id from 1..10 meant this read-only
    # transaction only ever touched a tenth of the data and ran against a much
    # hotter buffer cache than the loaded scale implies. Ranges now come from
    # tpcc_config. pick_keys also returns an order-line count, unused here.
    w_id, d_id, c_id, _ = pick_keys(random)

    try:
        # Was: no explicit transaction, so the customer read, the order read and
        # the order-line read each ran in their own autocommit transaction and
        # could see three different database states. OrderStatus is a
        # transaction in TPC-C and needs one consistent snapshot.
        with transaction.atomic(using=using):
            # Get customer
            customer = Customer.objects.using(using).get(
                c_w_id=w_id, c_d_id=d_id, c_id=c_id
            )

            # Get last order
            last_order = (
                Order.objects.using(using)
                .filter(o_w_id=w_id, o_d_id=d_id, o_c_id=c_id)
                .order_by("-o_id")
                .first()
            )

            if not last_order:
                return {"w_id": w_id, "d_id": d_id, "c_id": c_id, "order_found": False}

            # Get order lines
            order_lines = (
                OrderLine.objects.using(using)
                .filter(ol_w_id=w_id, ol_d_id=d_id, ol_o_id=last_order.o_id)
                .order_by("ol_number")
            )

            # The order_lines queryset is lazy, so this return has to stay inside
            # the atomic block: moving it out would run that query after commit.
            return {
                "w_id": w_id,
                "d_id": d_id,
                "c_id": c_id,
                "c_first": customer.c_first,
                "c_middle": customer.c_middle,
                "c_last": customer.c_last,
                "c_balance": float(customer.c_balance),
                "o_id": last_order.o_id,
                "o_entry_d": last_order.o_entry_d.isoformat(),
                "o_carrier_id": last_order.o_carrier_id,
                "order_lines": [
                    {
                        "ol_number": ol.ol_number,
                        "ol_i_id": ol.ol_i_id,
                        "ol_amount": float(ol.ol_amount),
                        "ol_delivery_d": ol.ol_delivery_d.isoformat()
                        if ol.ol_delivery_d
                        else None,
                    }
                    for ol in order_lines
                ],
            }
    except Exception:
        # Was: `return {'error': str(e)}`, which reported a failed transaction as
        # a completed one. See t1_neworder.py for the full reasoning.
        raise


def run_transaction_sql(connection):
    """
    Execute TPC-C T3 (OrderStatus) via direct SQL
    """
    import random

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # Same 10-warehouse problem as the ORM path above.
    w_id, d_id, c_id, _ = pick_keys(random)

    # Was: no explicit transaction, so the three reads below could each see a
    # different database state. See the ORM path above.
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c_first, c_middle, c_last, c_balance
                FROM customer
                WHERE c_w_id = %s AND c_d_id = %s AND c_id = %s
            """,
                [w_id, d_id, c_id],
            )

            customer_row = cursor.fetchone()
            if not customer_row:
                return {"error": "Customer not found"}

            from .db_utils import get_table_name, get_limit_clause

            order_table = get_table_name(connection, "order")
            limit_clause = get_limit_clause(connection, 1)

            cursor.execute(
                f"""
                SELECT o_id, o_entry_d, o_carrier_id
                FROM {order_table}
                WHERE o_w_id = %s AND o_d_id = %s AND o_c_id = %s
                ORDER BY o_id DESC
                {limit_clause}
            """,
                [w_id, d_id, c_id],
            )

            order_row = cursor.fetchone()
            if not order_row:
                return {
                    "w_id": w_id,
                    "d_id": d_id,
                    "c_id": c_id,
                    "c_first": customer_row[0],
                    "c_middle": customer_row[1],
                    "c_last": customer_row[2],
                    "c_balance": float(customer_row[3]),
                    "order_found": False,
                }

            o_id = order_row[0]

            cursor.execute(
                """
                SELECT ol_number, ol_i_id, ol_amount, ol_delivery_d
                FROM order_line
                WHERE ol_w_id = %s AND ol_d_id = %s AND ol_o_id = %s
                ORDER BY ol_number
            """,
                [w_id, d_id, o_id],
            )

            order_lines = []
            for row in cursor.fetchall():
                # Handle date field - MySQL may return string or datetime object
                ol_delivery_d = row[3]
                if ol_delivery_d:
                    if isinstance(ol_delivery_d, str):
                        ol_delivery_d = ol_delivery_d  # Already a string, use as-is
                    else:
                        ol_delivery_d = ol_delivery_d.isoformat()  # datetime object
                else:
                    ol_delivery_d = None

                order_lines.append(
                    {
                        "ol_number": row[0],
                        "ol_i_id": row[1],
                        "ol_amount": float(row[2]),
                        "ol_delivery_d": ol_delivery_d,
                    }
                )

            return {
                "w_id": w_id,
                "d_id": d_id,
                "c_id": c_id,
                "c_first": customer_row[0],
                "c_middle": customer_row[1],
                "c_last": customer_row[2],
                "c_balance": float(customer_row[3]),
                "o_id": o_id,
                "o_entry_d": order_row[1].isoformat(),
                "o_carrier_id": order_row[2],
                "order_lines": order_lines,
            }


def get_transaction_info():
    """Return metadata about this transaction"""
    return {
        "number": 3,
        "name": "OrderStatus",
        "complexity": "Simple",
        "description": "Retrieves the status of a customer's last order",
        "tables": ["customer", "order", "order_line"],
        "writes": 0,
        "reads": 3,
    }
