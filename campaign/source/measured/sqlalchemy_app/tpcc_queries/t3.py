"""
TPC-C Transaction 3: OrderStatus (SQLAlchemy)
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
import random

from tpcc_config import pick_keys


def run_transaction_orm(session: Session):
    """Execute TPC-C T3 (OrderStatus) via SQLAlchemy ORM"""
    from sqlalchemy_app.tpcc_models import Customer, Order, OrderLine

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # With 100 warehouses loaded, drawing w_id from 1..10 meant this read-only
    # transaction only ever touched a tenth of the data and ran against a much
    # hotter buffer cache than the loaded scale implies. Ranges now come from
    # tpcc_config. pick_keys also returns an order-line count, unused here.
    w_id, d_id, c_id, _ = pick_keys(random)

    # Was: no commit or rollback anywhere in this function. The session
    # autobegins a transaction on the first query and it stayed open after the
    # function returned, so the next transaction on that session inherited this
    # one's snapshot and the connection sat idle in transaction between runs.
    try:
        customer = session.query(Customer).filter_by(c_w_id=w_id, c_d_id=d_id, c_id=c_id).first()
        if not customer:
            session.commit()
            return {'error': 'Customer not found'}

        last_order = session.query(Order).filter_by(
            o_w_id=w_id, o_d_id=d_id, o_c_id=c_id
        ).order_by(Order.o_id.desc()).first()

        if not last_order:
            session.commit()
            return {'w_id': w_id, 'd_id': d_id, 'c_id': c_id, 'order_found': False}

        order_lines = session.query(OrderLine).filter_by(
            ol_w_id=w_id, ol_d_id=d_id, ol_o_id=last_order.o_id
        ).order_by(OrderLine.ol_number).all()

        result = {
            'w_id': w_id, 'd_id': d_id, 'c_id': c_id,
            'c_first': customer.c_first, 'c_last': customer.c_last,
            'c_balance': float(customer.c_balance),
            'o_id': last_order.o_id,
            'order_lines': len(order_lines)
        }
        # Read the attributes above before committing: the default expire_on_commit
        # would otherwise force a reload of customer and last_order after commit.
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def run_transaction_sql(session: Session):
    """Execute TPC-C T3 (OrderStatus) via direct SQL"""
    import random
    from sqlalchemy import text
    from .db_utils import get_table_name, get_limit_clause

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000).
    # Same 10-warehouse problem as the ORM path above.
    w_id, d_id, c_id, _ = pick_keys(random)

    order_table = get_table_name(session, 'order')
    limit_clause = get_limit_clause(session, 1)

    # Was: no commit or rollback anywhere in this function, so the three reads
    # below ran in a transaction that was never closed. See the ORM path above.
    try:
        result = session.execute(text("""
            SELECT c_first, c_last, c_balance FROM customer
            WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = :c_id
        """), {'w_id': w_id, 'd_id': d_id, 'c_id': c_id})

        customer_row = result.first()
        if not customer_row:
            session.commit()
            return {'error': 'Customer not found'}

        # Get last order
        result = session.execute(text(f"""
            SELECT o_id, o_entry_d, o_carrier_id
            FROM {order_table}
            WHERE o_w_id = :w_id AND o_d_id = :d_id AND o_c_id = :c_id
            ORDER BY o_id DESC
            {limit_clause}
        """), {'w_id': w_id, 'd_id': d_id, 'c_id': c_id})

        order_row = result.first()
        if not order_row:
            session.commit()
            return {
                'w_id': w_id, 'd_id': d_id, 'c_id': c_id,
                'c_first': customer_row[0], 'c_last': customer_row[1],
                'c_balance': float(customer_row[2]),
                'order_found': False
            }

        session.commit()
        return {
            'w_id': w_id, 'd_id': d_id, 'c_id': c_id,
            'c_first': customer_row[0], 'c_last': customer_row[1],
            'c_balance': float(customer_row[2]),
            'o_id': order_row[0],
            'o_entry_d': order_row[1].isoformat() if order_row[1] else None,
            'o_carrier_id': order_row[2]
        }
    except Exception:
        session.rollback()
        raise
