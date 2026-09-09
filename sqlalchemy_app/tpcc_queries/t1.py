"""
TPC-C Transaction 1: NewOrder (SQLAlchemy)
"""

from sqlalchemy.orm import Session
from datetime import datetime
import random

from tpcc_config import ITEMS, LOCK_DISTRICT, district_lock_sql, pick_keys


def run_transaction_orm(session: Session):
    """Execute TPC-C T1 (NewOrder) via SQLAlchemy ORM"""
    from sqlalchemy_app.tpcc_models import (
        Warehouse,
        District,
        Customer,
        Item,
        Stock,
        Order,
        NewOrder,
        OrderLine,
    )
    from sqlalchemy import text

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000),
    # ol_cnt = randint(5, 15), with the ranges written into this file. The
    # database is loaded with 100 warehouses, so drawing w_id from 1..10 confined
    # every worker to the same 10 warehouse rows and the measured throughput was
    # largely a measure of contention on those rows. The ranges now come from
    # tpcc_config so both frameworks draw from the same key space.
    w_id, d_id, c_id, ol_cnt = pick_keys(random)

    # The session autobegins a transaction on the first statement below and it
    # stays open until the single commit at the end. Was: the same single commit
    # but with no rollback on failure, which left the session in a failed
    # transaction for whatever ran next on it.
    try:
        warehouse = session.query(Warehouse).filter_by(w_id=w_id).first()
        customer = (
            session.query(Customer)
            .filter_by(c_w_id=w_id, c_d_id=d_id, c_id=c_id)
            .first()
        )

        # Was: a raw text() "SELECT d_next_o_id ... FOR UPDATE" that always
        # locked, while Django did an unlocked read. The lock is now under
        # tpcc_config.LOCK_DISTRICT so both frameworks follow one policy, and it
        # is expressed with with_for_update() rather than hand-written SQL.
        # one() rather than first() on purpose: first() appends a row limit, and
        # Oracle rejects a row-limiting clause combined with FOR UPDATE.
        district_q = session.query(District).filter_by(d_w_id=w_id, d_id=d_id)
        if LOCK_DISTRICT:
            # with_for_update() alone is not enough, because on SQL Server it
            # emits nothing at all - no FOR UPDATE, no table hint, no error.
            # Compiled against the mssql dialect the statement comes back as a
            # plain SELECT, so the district row is read unlocked and two
            # concurrent New-Orders take the same d_next_o_id. Measured at
            # concurrency 50: 522 of 6,778 transactions failed with
            # IntegrityError on the order primary key, a 7.7% abort rate, while
            # Django's select_for_update() on the same server emitted
            # `FROM [district] WITH (ROWLOCK, UPDLOCK)` and aborted none.
            #
            # That is a correctness difference between the two ORMs rather than
            # a performance one, and the dangerous half is that SQLAlchemy's is
            # silent: Django raises TransactionManagementError if you ask for
            # select_for_update() outside a transaction, whereas SQLAlchemy
            # returns a query that simply does not lock.
            if session.bind.dialect.name in ("mssql", "microsoft", "sqlserver"):
                district_q = district_q.with_hint(District, "WITH (UPDLOCK, ROWLOCK)")
            else:
                district_q = district_q.with_for_update()
        district = district_q.one()
        next_o_id = district.d_next_o_id

        # Now increment it. Left as an explicit statement so the UPDATE keeps the
        # same predicate and the same assignment it had before.
        session.execute(
            text(
                "UPDATE district SET d_next_o_id = :new_id WHERE d_w_id = :w_id AND d_id = :d_id"
            ),
            {"new_id": next_o_id + 1, "w_id": w_id, "d_id": d_id},
        )
        session.flush()

        order = Order(
            o_id=next_o_id,
            o_d_id=d_id,
            o_w_id=w_id,
            o_c_id=c_id,
            o_entry_d=datetime.now(),
            o_carrier_id=None,
            o_ol_cnt=ol_cnt,
            o_all_local=1,
        )
        session.add(order)

        new_order = NewOrder(no_o_id=next_o_id, no_d_id=d_id, no_w_id=w_id)
        session.add(new_order)

        total_amount = 0.0
        for ol_number in range(1, ol_cnt + 1):
            # Was: randint(1, 100000) with the item count written into this file.
            # ITEMS carries the same number, but from the shared config, so a
            # differently loaded database cannot silently make the two frameworks
            # read different item ranges.
            ol_i_id = random.randint(1, ITEMS)
            # Order-line quantity is fixed at 1..10 by the specification and does
            # not scale with the database, so it stays a literal.
            ol_quantity = random.randint(1, 10)

            item = session.query(Item).filter_by(i_id=ol_i_id).first()
            stock = session.query(Stock).filter_by(s_w_id=w_id, s_i_id=ol_i_id).first()

            ol_amount = float(item.i_price) * ol_quantity
            total_amount += ol_amount

            order_line = OrderLine(
                ol_o_id=next_o_id,
                ol_d_id=d_id,
                ol_w_id=w_id,
                ol_number=ol_number,
                ol_i_id=ol_i_id,
                ol_supply_w_id=w_id,
                ol_quantity=ol_quantity,
                ol_amount=ol_amount,
                ol_dist_info=stock.s_dist_01,
            )
            session.add(order_line)

        session.commit()
        return {
            "w_id": w_id,
            "d_id": d_id,
            "c_id": c_id,
            "o_id": next_o_id,
            "total_amount": total_amount,
        }
    except Exception:
        session.rollback()
        raise


def run_transaction_sql(session: Session):
    """Execute TPC-C T1 (NewOrder) via direct SQL"""
    import random
    from sqlalchemy import text
    from datetime import datetime
    from .db_utils import get_table_name, get_current_timestamp

    # Was: w_id = randint(1, 10), d_id = randint(1, 10), c_id = randint(1, 3000)
    # here and ol_cnt = randint(5, 15) further down. Same 10-warehouse problem as
    # the ORM path above. ol_cnt is now drawn here with the other keys; it is
    # still only used in the INSERT below.
    w_id, d_id, c_id, ol_cnt = pick_keys(random)

    # Get vendor-specific table name and timestamp function
    order_table = get_table_name(session, "order")
    now_func = get_current_timestamp(session)

    # Was: a single commit with no rollback on failure. See the ORM path above.
    try:
        # Was: this path read the district, wrote ORDER and NEW_ORDER, and
        # stopped. It never read WAREHOUSE, CUSTOMER, ITEM or STOCK and never
        # wrote a single ORDER_LINE, so it performed roughly a third of a
        # New-Order while the ORM path performed all of it, and the T1 overhead
        # column compared a whole transaction against a fragment. The statements
        # below now mirror run_transaction_orm one for one, in the same order.
        row = session.execute(
            text("""
            SELECT w_tax FROM warehouse WHERE w_id = :w_id
        """),
            {"w_id": w_id},
        ).first()
        if row is None:
            raise LookupError(
                f"warehouse {w_id} not found; tpcc_config does not "
                f"describe the loaded database"
            )

        row = session.execute(
            text("""
            SELECT c_discount FROM customer
            WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = :c_id
        """),
            {"w_id": w_id, "d_id": d_id, "c_id": c_id},
        ).first()
        if row is None:
            raise LookupError(f"customer ({w_id}, {d_id}, {c_id}) not found")

        # Was: an unlocked read here even though this framework's ORM path held
        # FOR UPDATE on the same row. Both raw-SQL paths now follow
        # tpcc_config.LOCK_DISTRICT, the same as the ORM paths.
        # FOR UPDATE is not portable; see tpcc_config.district_lock_sql.
        hint, lock_clause = district_lock_sql(session.bind.dialect.name)
        result = session.execute(
            text(f"""
            SELECT d_next_o_id FROM district{hint} WHERE d_w_id = :w_id AND d_id = :d_id{lock_clause}
        """),
            {"w_id": w_id, "d_id": d_id},
        )
        row = result.first()
        if not row:
            # Was: a commit and `return {'error': 'District not found'}`. A
            # returned dict is indistinguishable from a completed transaction to
            # the harness; raising rolls back in the handler below instead.
            raise LookupError(f"district ({w_id}, {d_id}) not found")

        next_o_id = row[0]

        # Increment next order ID
        session.execute(
            text("""
            UPDATE district SET d_next_o_id = d_next_o_id + 1 WHERE d_w_id = :w_id AND d_id = :d_id
        """),
            {"w_id": w_id, "d_id": d_id},
        )

        # Create order. The timestamp is the only vendor difference and
        # get_current_timestamp already carries it; this was previously an
        # if/else on the dialect name whose two branches were identical.
        session.execute(
            text(f"""
            INSERT INTO {order_table} (o_id, o_d_id, o_w_id, o_c_id, o_entry_d, o_carrier_id, o_ol_cnt, o_all_local)
            VALUES (:o_id, :d_id, :w_id, :c_id, {now_func}, NULL, :ol_cnt, 1)
        """),
            {
                "o_id": next_o_id,
                "d_id": d_id,
                "w_id": w_id,
                "c_id": c_id,
                "ol_cnt": ol_cnt,
            },
        )

        # Create new_order entry
        session.execute(
            text("""
            INSERT INTO new_order (no_o_id, no_d_id, no_w_id)
            VALUES (:o_id, :d_id, :w_id)
        """),
            {"o_id": next_o_id, "d_id": d_id, "w_id": w_id},
        )

        # The order lines. Same loop, same draws in the same order and the same
        # two reads per line as the ORM path, so the two consume the same values
        # from `random` and touch the same rows.
        total_amount = 0.0
        for ol_number in range(1, ol_cnt + 1):
            ol_i_id = random.randint(1, ITEMS)
            ol_quantity = random.randint(1, 10)

            item_row = session.execute(
                text("SELECT i_price FROM item WHERE i_id = :i_id"), {"i_id": ol_i_id}
            ).first()
            if item_row is None:
                raise LookupError(f"item {ol_i_id} not found")

            stock_row = session.execute(
                text("""
                SELECT s_dist_01 FROM stock WHERE s_w_id = :w_id AND s_i_id = :i_id
            """),
                {"w_id": w_id, "i_id": ol_i_id},
            ).first()
            if stock_row is None:
                raise LookupError(f"stock ({w_id}, {ol_i_id}) not found")

            ol_amount = float(item_row[0]) * ol_quantity
            total_amount += ol_amount

            session.execute(
                text("""
                INSERT INTO order_line (ol_o_id, ol_d_id, ol_w_id, ol_number,
                                        ol_i_id, ol_supply_w_id, ol_delivery_d,
                                        ol_quantity, ol_amount, ol_dist_info)
                VALUES (:o_id, :d_id, :w_id, :ol_number, :i_id, :supply_w_id, NULL,
                        :qty, :amount, :dist_info)
            """),
                {
                    "o_id": next_o_id,
                    "d_id": d_id,
                    "w_id": w_id,
                    "ol_number": ol_number,
                    "i_id": ol_i_id,
                    "supply_w_id": w_id,
                    "qty": ol_quantity,
                    "amount": ol_amount,
                    "dist_info": stock_row[0],
                },
            )

        session.commit()
        return {
            "w_id": w_id,
            "d_id": d_id,
            "c_id": c_id,
            "o_id": next_o_id,
            "ol_cnt": ol_cnt,
            "total_amount": total_amount,
        }
    except Exception:
        session.rollback()
        raise
