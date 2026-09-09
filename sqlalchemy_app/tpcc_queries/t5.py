"""
TPC-C Transaction 5: StockLevel (SQLAlchemy)
"""

from sqlalchemy.orm import Session
from sqlalchemy import text, func
import random

from tpcc_config import DISTRICTS_PER_WAREHOUSE, WAREHOUSES


def run_transaction_orm(session: Session):
    """Execute TPC-C T5 (StockLevel) via SQLAlchemy ORM"""
    from sqlalchemy_app.tpcc_models import District, Order, OrderLine, Stock

    # Was: w_id = randint(1, 10), d_id = randint(1, 10) against a 100-warehouse
    # database, so this transaction only ever scanned a tenth of the stock
    # table. Ranges now come from tpcc_config.
    w_id = random.randint(1, WAREHOUSES)
    d_id = random.randint(1, DISTRICTS_PER_WAREHOUSE)
    # The stock threshold is fixed at 10..20 by the specification and does not
    # scale with the database, so it stays a literal.
    threshold = random.randint(10, 20)

    # Was: no commit or rollback anywhere in this function. The session
    # autobegins a transaction on the first query and it stayed open after the
    # function returned, so the next transaction on that session inherited this
    # one's snapshot and the connection sat idle in transaction between runs.
    try:
        last_orders = (
            session.query(Order)
            .filter_by(o_w_id=w_id, o_d_id=d_id)
            .order_by(Order.o_id.desc())
            .limit(20)
            .all()
        )

        if not last_orders:
            session.commit()
            return {
                "w_id": w_id,
                "d_id": d_id,
                "threshold": threshold,
                "low_stock_count": 0,
            }

        order_ids = [o.o_id for o in last_orders]
        order_lines = (
            session.query(OrderLine.ol_i_id)
            .filter(
                OrderLine.ol_w_id == w_id,
                OrderLine.ol_d_id == d_id,
                OrderLine.ol_o_id.in_(order_ids),
            )
            .distinct()
            .all()
        )

        item_ids = [ol[0] for ol in order_lines]

        if not item_ids:
            session.commit()
            return {
                "w_id": w_id,
                "d_id": d_id,
                "threshold": threshold,
                "low_stock_count": 0,
            }

        low_stock_count = (
            session.query(Stock)
            .filter(
                Stock.s_w_id == w_id,
                Stock.s_i_id.in_(item_ids),
                Stock.s_quantity < threshold,
            )
            .count()
        )

        session.commit()
        return {
            "w_id": w_id,
            "d_id": d_id,
            "threshold": threshold,
            "items_checked": len(item_ids),
            "low_stock_count": low_stock_count,
        }
    except Exception:
        session.rollback()
        raise


def run_transaction_sql(session: Session):
    """Execute TPC-C T5 (StockLevel) via direct SQL"""
    import random
    from sqlalchemy import text
    from .db_utils import get_table_name, get_any_operator, get_limit_clause

    # Was: w_id = randint(1, 10), d_id = randint(1, 10). Same problem as the ORM
    # path above.
    w_id = random.randint(1, WAREHOUSES)
    d_id = random.randint(1, DISTRICTS_PER_WAREHOUSE)
    # Threshold is a specification constant, not a key range. See above.
    threshold = random.randint(10, 20)

    order_table = get_table_name(session, "order")
    any_op, format_func = get_any_operator(session)
    limit_clause = get_limit_clause(session, 20)

    # Was: no commit or rollback anywhere in this function, so the three reads
    # below ran in a transaction that was never closed. See the ORM path above.
    try:
        # Get last 20 orders
        result = session.execute(
            text(f"""
            SELECT o_id FROM {order_table}
            WHERE o_w_id = :w_id AND o_d_id = :d_id
            ORDER BY o_id DESC
            {limit_clause}
        """),
            {"w_id": w_id, "d_id": d_id},
        )

        order_rows = result.fetchall()
        if not order_rows:
            session.commit()
            return {
                "w_id": w_id,
                "d_id": d_id,
                "threshold": threshold,
                "low_stock_count": 0,
            }

        order_ids = [row[0] for row in order_rows]

        # Get distinct items (handle vendor differences)
        if any_op == "IN":
            placeholders, params = format_func(order_ids)
            params.update({"w_id": w_id, "d_id": d_id})
            result = session.execute(
                text(f"""
                SELECT DISTINCT ol_i_id FROM order_line
                WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id IN ({placeholders})
            """),
                params,
            )
        else:
            placeholders, params = format_func(order_ids)
            params.update({"w_id": w_id, "d_id": d_id})
            result = session.execute(
                text(f"""
                SELECT DISTINCT ol_i_id FROM order_line
                WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id = {any_op}({placeholders})
            """),
                params,
            )

        item_rows = result.fetchall()
        item_ids = [row[0] for row in item_rows]

        if not item_ids:
            session.commit()
            return {
                "w_id": w_id,
                "d_id": d_id,
                "threshold": threshold,
                "low_stock_count": 0,
            }

        # Count low stock items (handle vendor differences)
        if any_op == "IN":
            placeholders, params = format_func(item_ids)
            params.update({"w_id": w_id, "threshold": threshold})
            result = session.execute(
                text(f"""
                SELECT COUNT(*) FROM stock
                WHERE s_w_id = :w_id AND s_i_id IN ({placeholders}) AND s_quantity < :threshold
            """),
                params,
            )
        else:
            placeholders, params = format_func(item_ids)
            params.update({"w_id": w_id, "threshold": threshold})
            result = session.execute(
                text(f"""
                SELECT COUNT(*) FROM stock
                WHERE s_w_id = :w_id AND s_i_id = {any_op}({placeholders}) AND s_quantity < :threshold
            """),
                params,
            )

        count = result.first()[0]
        session.commit()
        return {
            "w_id": w_id,
            "d_id": d_id,
            "threshold": threshold,
            "low_stock_count": count,
        }
    except Exception:
        session.rollback()
        raise
