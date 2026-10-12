"""
TPC-C Transaction 2: Payment
Processes a customer payment
"""
from django.db import transaction
from django.db.models import F
from decimal import Decimal
from datetime import datetime
import random

from tpcc_config import pick_keys


def run_transaction_orm(using='default'):
    """
    Execute TPC-C T2 (Payment) via Django ORM
    """
    from django_app.tpcc_models import Warehouse, District, Customer, History

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # The w_id range did not match the 100 warehouses loaded, so all workers
    # updated the same 10 warehouse rows. Ranges now come from tpcc_config.
    # pick_keys also returns an order-line count, which Payment does not use.
    w_id, d_id, c_id, _ = pick_keys(random)
    payment = Decimal(str(random.uniform(1.0, 5000.0)))

    try:
        # Was: no explicit transaction, so the three updates and the history
        # insert below each committed on their own. A partial failure could
        # leave the warehouse and district totals updated with no matching
        # history row.
        with transaction.atomic(using=using):
            # Get warehouse and district
            warehouse = Warehouse.objects.using(using).get(w_id=w_id)
            district = District.objects.using(using).get(d_w_id=w_id, d_id=d_id)
            customer = Customer.objects.using(using).get(c_w_id=w_id, c_d_id=d_id, c_id=c_id)

            # Update warehouse
            Warehouse.objects.using(using).filter(w_id=w_id).update(
                w_ytd=F('w_ytd') + payment
            )

            # Update district
            District.objects.using(using).filter(d_w_id=w_id, d_id=d_id).update(
                d_ytd=F('d_ytd') + payment
            )

            # Update customer
            Customer.objects.using(using).filter(c_w_id=w_id, c_d_id=d_id, c_id=c_id).update(
                c_balance=F('c_balance') - payment,
                c_ytd_payment=F('c_ytd_payment') + payment,
                c_payment_cnt=F('c_payment_cnt') + 1
            )

            # Create history entry
            History.objects.using(using).create(
                h_c_id=c_id,
                h_c_d_id=d_id,
                h_c_w_id=w_id,
                h_d_id=d_id,
                h_w_id=w_id,
                h_date=datetime.now(),
                h_amount=payment,
                h_data=f"Customer {c_id} paid {payment}"[:24]  # Truncate to 24 chars (TPC-C spec)
            )

            # Re-read the customer through the whole key.
            #
            # Was `customer.refresh_from_db()`, which re-fetches by primary key.
            # Django 4.2 cannot express TPC-C's composite keys, so
            # django_app/tpcc_models.py declares c_id as the primary key, and
            # c_id 1208 exists once in every one of the 100 (warehouse, district)
            # pairs. refresh_from_db therefore issued
            # `WHERE c_id = 1208` and died on MultipleObjectsReturned - "it
            # returned more than 20!" - rather than returning the wrong row,
            # which is the one piece of luck in this defect. See the module
            # docstring in tpcc_models.py.
            customer = Customer.objects.using(using).get(
                c_w_id=w_id, c_d_id=d_id, c_id=c_id
            )

            return {
                'w_id': w_id,
                'd_id': d_id,
                'c_id': c_id,
                'payment': float(payment),
                'c_balance': float(customer.c_balance),
                'c_ytd_payment': float(customer.c_ytd_payment)
            }
    except Exception:
        # Was: `return {'error': str(e)}`, which reported a failed transaction as
        # a completed one. See t1_neworder.py for the full reasoning.
        raise


def run_transaction_sql(connection):
    """
    Execute TPC-C T2 (Payment) via direct SQL
    """
    import random
    from datetime import datetime
    from .db_utils import get_current_timestamp

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # Same 10-warehouse problem as the ORM path above.
    w_id, d_id, c_id, _ = pick_keys(random)
    payment = random.uniform(1.0, 5000.0)

    now_func = get_current_timestamp(connection)

    # Was: no explicit transaction. See the ORM path above.
    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            # Execute updates separately (MySQL doesn't support multi-statement in single execute)
            cursor.execute(
                "UPDATE warehouse SET w_ytd = w_ytd + %s WHERE w_id = %s",
                [payment, w_id]
            )
            cursor.execute(
                "UPDATE district SET d_ytd = d_ytd + %s WHERE d_w_id = %s AND d_id = %s",
                [payment, w_id, d_id]
            )
            cursor.execute(
                """UPDATE customer SET
                    c_balance = c_balance - %s,
                    c_ytd_payment = c_ytd_payment + %s,
                    c_payment_cnt = c_payment_cnt + 1
                WHERE c_w_id = %s AND c_d_id = %s AND c_id = %s""",
                [payment, payment, w_id, d_id, c_id]
            )
            # Prepare h_data (truncate to 24 chars max)
            h_data = f"C{c_id}P{payment:.2f}"[:24]

            # Use vendor-specific timestamp function
            if connection.vendor == 'oracle':
                # Oracle: Use SYSDATE directly in SQL, Django converts %s to :1, :2, etc.
                cursor.execute(
                    """INSERT INTO history (h_c_id, h_c_d_id, h_c_w_id, h_d_id, h_w_id, h_date, h_amount, h_data)
                    VALUES (%s, %s, %s, %s, %s, SYSDATE, %s, %s)""",
                    [c_id, d_id, w_id, d_id, w_id, payment, h_data]
                )
            else:
                # PostgreSQL, MySQL: Use NOW() in SQL
                cursor.execute(
                    f"""INSERT INTO history (h_c_id, h_c_d_id, h_c_w_id, h_d_id, h_w_id, h_date, h_amount, h_data)
                    VALUES (%s, %s, %s, %s, %s, {now_func}, %s, %s)""",
                    [c_id, d_id, w_id, d_id, w_id, payment, h_data]
                )

            # Get customer balance
            cursor.execute(
                "SELECT c_balance, c_ytd_payment FROM customer WHERE c_w_id = %s AND c_d_id = %s AND c_id = %s",
                [w_id, d_id, c_id]
            )

            row = cursor.fetchone()
            if row:
                return {
                    'w_id': w_id,
                    'd_id': d_id,
                    'c_id': c_id,
                    'payment': payment,
                    'c_balance': float(row[0]),
                    'c_ytd_payment': float(row[1])
                }
            return {'error': 'Customer not found'}


def get_transaction_info():
    """Return metadata about this transaction"""
    return {
        'number': 2,
        'name': 'Payment',
        'complexity': 'Simple',
        'description': 'Processes a customer payment',
        'tables': ['warehouse', 'district', 'customer', 'history'],
        'writes': 4,
        'reads': 3,
    }
