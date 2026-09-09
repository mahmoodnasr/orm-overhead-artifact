"""
TPC-C Transaction 4: Delivery (SQLAlchemy)
"""

from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime
from decimal import Decimal
import random

from tpcc_config import DISTRICTS_PER_WAREHOUSE, WAREHOUSES


def run_transaction_orm(session: Session):
    """Execute TPC-C T4 (Delivery) via SQLAlchemy ORM"""
    from sqlalchemy_app.tpcc_models import NewOrder, Order, OrderLine, Customer

    # Was: w_id = randint(1, 10) against a 100-warehouse database, so every
    # worker delivered out of the same 10 warehouses. WAREHOUSES comes from
    # tpcc_config and tracks what was actually loaded.
    w_id = random.randint(1, WAREHOUSES)
    # The carrier id range is fixed at 1..10 by the specification and does not
    # scale with the database, so it stays a literal. It is only a coincidence
    # that it matches the old, incorrect warehouse range.
    carrier_id = random.randint(1, 10)

    # The session autobegins a transaction on the first query below and it stays
    # open until the single commit at the end. Was: the same single commit but
    # with no rollback on failure, which left the session holding partly applied
    # deliveries for whatever ran next on it.
    try:
        results = []
        # Was: range(1, 11) with the district count written into this file.
        for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
            new_order = (
                session.query(NewOrder)
                .filter_by(no_w_id=w_id, no_d_id=d_id)
                .order_by(NewOrder.no_o_id)
                .first()
            )

            if not new_order:
                continue

            o_id = new_order.no_o_id
            order = (
                session.query(Order)
                .filter_by(o_w_id=w_id, o_d_id=d_id, o_id=o_id)
                .first()
            )
            order.o_carrier_id = carrier_id

            order_lines = (
                session.query(OrderLine)
                .filter_by(ol_w_id=w_id, ol_d_id=d_id, ol_o_id=o_id)
                .all()
            )

            for ol in order_lines:
                ol.ol_delivery_d = datetime.now()

            total_amount = sum(float(ol.ol_amount) for ol in order_lines)

            customer = (
                session.query(Customer)
                .filter_by(c_w_id=w_id, c_d_id=d_id, c_id=order.o_c_id)
                .first()
            )
            # Convert to Decimal to match c_balance type
            customer.c_balance += Decimal(str(total_amount))
            customer.c_delivery_cnt += 1

            session.delete(new_order)
            results.append({"d_id": d_id, "o_id": o_id, "total_amount": total_amount})

        session.commit()
        return {
            "w_id": w_id,
            "carrier_id": carrier_id,
            "orders_delivered": len(results),
        }
    except Exception:
        session.rollback()
        raise


def run_transaction_sql(session: Session):
    """Execute TPC-C T4 (Delivery) via direct SQL"""
    import random
    from sqlalchemy import text
    from datetime import datetime
    from .db_utils import get_table_name, get_current_timestamp, get_limit_clause

    # Was: w_id = randint(1, 10) against a 100-warehouse database. Same problem
    # as the ORM path above.
    w_id = random.randint(1, WAREHOUSES)
    # Carrier id is a specification constant, not a key range. See above.
    carrier_id = random.randint(1, 10)

    order_table = get_table_name(session, "order")
    now_func = get_current_timestamp(session)
    limit_clause = get_limit_clause(session, 1)

    # Was: a single commit with no rollback on failure. See the ORM path above.
    try:
        results = []
        # Was: range(1, 11) with the district count written into this file.
        for d_id in range(1, DISTRICTS_PER_WAREHOUSE + 1):
            # Get oldest new order
            result = session.execute(
                text(f"""
                SELECT no_o_id FROM new_order
                WHERE no_w_id = :w_id AND no_d_id = :d_id
                ORDER BY no_o_id
                {limit_clause}
            """),
                {"w_id": w_id, "d_id": d_id},
            )

            row = result.first()
            if not row:
                continue

            o_id = row[0]

            # Update order
            session.execute(
                text(f"""
                UPDATE {order_table} SET o_carrier_id = :carrier_id
                WHERE o_w_id = :w_id AND o_d_id = :d_id AND o_id = :o_id
            """),
                {"carrier_id": carrier_id, "w_id": w_id, "d_id": d_id, "o_id": o_id},
            )

            # Update order lines
            session.execute(
                text(f"""
                UPDATE order_line SET ol_delivery_d = {now_func}
                WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id = :o_id
            """),
                {"w_id": w_id, "d_id": d_id, "o_id": o_id},
            )

            # Get total amount and customer
            result = session.execute(
                text(f"""
                SELECT SUM(ol_amount), o_c_id FROM order_line, {order_table}
                WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id = :o_id
                AND o_w_id = :w_id AND o_d_id = :d_id AND o_id = :o_id
                GROUP BY o_c_id
            """),
                {"w_id": w_id, "d_id": d_id, "o_id": o_id},
            )

            total_row = result.first()
            if total_row:
                total_amount = float(total_row[0]) if total_row[0] else 0.0
                c_id = total_row[1]

                # Update customer
                session.execute(
                    text("""
                    UPDATE customer SET
                        c_balance = c_balance + :amount,
                        c_delivery_cnt = c_delivery_cnt + 1
                    WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = :c_id
                """),
                    {"amount": total_amount, "w_id": w_id, "d_id": d_id, "c_id": c_id},
                )

            # Delete new_order
            session.execute(
                text("""
                DELETE FROM new_order
                WHERE no_w_id = :w_id AND no_d_id = :d_id AND no_o_id = :o_id
            """),
                {"w_id": w_id, "d_id": d_id, "o_id": o_id},
            )

            results.append(
                {
                    "d_id": d_id,
                    "o_id": o_id,
                    "total_amount": total_amount if total_row else 0.0,
                }
            )

        session.commit()
        return {
            "w_id": w_id,
            "carrier_id": carrier_id,
            "orders_delivered": len(results),
        }
    except Exception:
        session.rollback()
        raise
