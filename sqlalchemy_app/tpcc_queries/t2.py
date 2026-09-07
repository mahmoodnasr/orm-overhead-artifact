"""
TPC-C Transaction 2: Payment (SQLAlchemy)
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from decimal import Decimal
import random

from tpcc_config import pick_keys


def run_transaction_orm(session: Session):
    """Execute TPC-C T2 (Payment) via SQLAlchemy ORM"""
    from sqlalchemy_app.tpcc_models import Warehouse, District, Customer, History

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # The w_id range did not match the 100 warehouses loaded, so all workers
    # updated the same 10 warehouse rows. Ranges now come from tpcc_config.
    # pick_keys also returns an order-line count, which Payment does not use.
    w_id, d_id, c_id, _ = pick_keys(random)
    payment = random.uniform(1.0, 5000.0)
    # Convert to Decimal to match database column types
    payment_decimal = Decimal(str(payment))

    # The session autobegins a transaction on the first query below and it stays
    # open until the single commit at the end. Was: the same single commit but
    # with no rollback on failure, which left the session in a failed
    # transaction for whatever ran next on it.
    try:
        warehouse = session.query(Warehouse).filter_by(w_id=w_id).first()
        district = session.query(District).filter_by(d_w_id=w_id, d_id=d_id).first()
        customer = session.query(Customer).filter_by(c_w_id=w_id, c_d_id=d_id, c_id=c_id).first()

        warehouse.w_ytd += payment_decimal
        district.d_ytd += payment_decimal
        customer.c_balance -= payment_decimal
        customer.c_ytd_payment += payment_decimal
        customer.c_payment_cnt += 1

        # Truncate h_data to max 24 characters (TPC-C spec)
        h_data = f"Customer {c_id} paid {payment}"[:24]

        history = History(
            h_c_id=c_id, h_c_d_id=d_id, h_c_w_id=w_id,
            h_d_id=d_id, h_w_id=w_id, h_date=datetime.now(),
            h_amount=payment, h_data=h_data
        )
        session.add(history)
        session.commit()

        return {
            'w_id': w_id, 'd_id': d_id, 'c_id': c_id,
            'payment': payment, 'c_balance': float(customer.c_balance)
        }
    except Exception:
        session.rollback()
        raise


def run_transaction_sql(session: Session):
    """Execute TPC-C T2 (Payment) via direct SQL"""
    import random
    from sqlalchemy import text
    from datetime import datetime
    from .db_utils import get_current_timestamp

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # Same 10-warehouse problem as the ORM path above.
    w_id, d_id, c_id, _ = pick_keys(random)
    payment = random.uniform(1.0, 5000.0)

    now_func = get_current_timestamp(session)

    # Was: a single commit reached only on the success path, and no rollback on
    # failure. See the ORM path above.
    try:
        # Execute updates separately
        session.execute(text("""
            UPDATE warehouse SET w_ytd = w_ytd + :payment WHERE w_id = :w_id
        """), {'payment': payment, 'w_id': w_id})

        session.execute(text("""
            UPDATE district SET d_ytd = d_ytd + :payment WHERE d_w_id = :w_id AND d_id = :d_id
        """), {'payment': payment, 'w_id': w_id, 'd_id': d_id})

        session.execute(text("""
            UPDATE customer SET
                c_balance = c_balance - :payment,
                c_ytd_payment = c_ytd_payment + :payment,
                c_payment_cnt = c_payment_cnt + 1
            WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = :c_id
        """), {'payment': payment, 'w_id': w_id, 'd_id': d_id, 'c_id': c_id})

        # Truncate h_data to max 24 characters (TPC-C spec)
        h_data = f'Customer {c_id} paid {payment}'[:24]

        session.execute(text(f"""
            INSERT INTO history (h_c_id, h_c_d_id, h_c_w_id, h_d_id, h_w_id, h_date, h_amount, h_data)
            VALUES (:c_id, :d_id, :w_id, :d_id, :w_id, {now_func}, :payment, :data)
        """), {
            'c_id': c_id, 'd_id': d_id, 'w_id': w_id,
            'payment': payment,
            'data': h_data
        })

        # Get customer balance
        result = session.execute(text("""
            SELECT c_balance, c_ytd_payment FROM customer
            WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = :c_id
        """), {'w_id': w_id, 'd_id': d_id, 'c_id': c_id})

        row = result.first()
        if row:
            session.commit()
            return {
                'w_id': w_id, 'd_id': d_id, 'c_id': c_id,
                'payment': payment, 'c_balance': float(row[0]),
                'c_ytd_payment': float(row[1])
            }
        # Was: an early return that left the four writes above sitting in an open
        # transaction, neither committed nor rolled back. Committing here matches
        # what Django's raw-SQL path does on the same branch, which is what keeps
        # the two comparable. Note that both then commit a payment that debited
        # no customer; that is a pre-existing problem in both, not one this
        # change introduces.
        session.commit()
        return {'error': 'Customer not found'}
    except Exception:
        session.rollback()
        raise
