"""Genuine SQLAlchemy ORM implementations of the 22 TPC-H queries.

Every function here builds its statement from the mapped classes in
`sqlalchemy_app.models`. None of them falls back to a text() literal, which is
the defect that made the original SQLAlchemy measurements meaningless: 18 of the
22 original `run_query_orm` functions immediately called `run_query_sql`, so the
harness timed the same raw-SQL function twice and reported the difference as
"ORM overhead".

Every function takes the block's substitution-parameter set `p` as its second
argument, from tpch_paramsets. Both frameworks and both access paths read the
same set within a block, which is what makes the paired log ratio taken inside
that block a comparison of the same work rather than of two different queries.
Passing set 0 reproduces the TPC-H validation instance, which is what every
measurement taken before the eight-block protocol used.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, and_, or_, case, distinct, select, literal_column, String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.expression import FunctionElement

from tpch_params import Q11_FRACTION

from sqlalchemy_app.models import (
    Region, Nation, Supplier, Part, PartSupp, Customer, Orders, LineItem,
)


def _dicts(rows, keys):
    return [dict(zip(keys, r)) for r in rows]


# ---------------------------------------------------------------- Q1
def q01(session: Session, p):
    rows = (
        session.query(
            LineItem.returnflag, LineItem.linestatus,
            func.sum(LineItem.quantity).label("sum_qty"),
            func.sum(LineItem.extendedprice).label("sum_base_price"),
            func.sum(LineItem.extendedprice * (1 - LineItem.discount)).label("sum_disc_price"),
            func.sum(LineItem.extendedprice * (1 - LineItem.discount) * (1 + LineItem.tax)).label("sum_charge"),
            func.avg(LineItem.quantity).label("avg_qty"),
            func.avg(LineItem.extendedprice).label("avg_price"),
            func.avg(LineItem.discount).label("avg_disc"),
            func.count().label("count_order"),
        )
        .filter(LineItem.shipdate <= p["date"])
        .group_by(LineItem.returnflag, LineItem.linestatus)
        .order_by(LineItem.returnflag, LineItem.linestatus)
        .all()
    )
    return _dicts(rows, ["l_returnflag", "l_linestatus", "sum_qty", "sum_base_price",
                         "sum_disc_price", "sum_charge", "avg_qty", "avg_price",
                         "avg_disc", "count_order"])


# ---------------------------------------------------------------- Q2
def q02(session: Session, p):
    ps2, s2, n2, r2 = aliased(PartSupp), aliased(Supplier), aliased(Nation), aliased(Region)
    min_cost = (
        select(func.min(ps2.supplycost))
        .where(and_(ps2.partkey_id == Part.partkey,
                    s2.suppkey == ps2.suppkey_id,
                    s2.nationkey_id == n2.nationkey,
                    n2.regionkey_id == r2.regionkey,
                    r2.name == p["region"]))
        .scalar_subquery()
    )
    rows = (
        session.query(Supplier.acctbal, Supplier.name, Nation.name, Part.partkey,
                      Part.mfgr, Supplier.address, Supplier.phone, Supplier.comment)
        .filter(Part.partkey == PartSupp.partkey_id,
                Supplier.suppkey == PartSupp.suppkey_id,
                Part.size == p["size"],
                Part.type.like("%%%s" % p["type_suffix"]),
                Supplier.nationkey_id == Nation.nationkey,
                Nation.regionkey_id == Region.regionkey,
                Region.name == p["region"],
                PartSupp.supplycost == min_cost)
        .order_by(Supplier.acctbal.desc(), Nation.name, Supplier.name, Part.partkey)
        .limit(100)
        .all()
    )
    return _dicts(rows, ["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr",
                         "s_address", "s_phone", "s_comment"])


# ---------------------------------------------------------------- Q3
def q03(session: Session, p):
    rows = (
        session.query(LineItem.orderkey_id,
                      func.sum(LineItem.extendedprice * (1 - LineItem.discount)).label("revenue"),
                      Orders.orderdate, Orders.shippriority)
        .filter(Customer.mktsegment == p["segment"],
                Customer.custkey == Orders.custkey_id,
                LineItem.orderkey_id == Orders.orderkey,
                Orders.orderdate < p["date"],
                LineItem.shipdate > p["date"])
        .group_by(LineItem.orderkey_id, Orders.orderdate, Orders.shippriority)
        .order_by(func.sum(LineItem.extendedprice * (1 - LineItem.discount)).desc(),
                  Orders.orderdate)
        .limit(10)
        .all()
    )
    return _dicts(rows, ["l_orderkey", "revenue", "o_orderdate", "o_shippriority"])


# ---------------------------------------------------------------- Q4
def q04(session: Session, p):
    exists_q = (
        select(literal_column("1"))
        .where(and_(LineItem.orderkey_id == Orders.orderkey,
                    LineItem.commitdate < LineItem.receiptdate))
        .exists()
    )
    rows = (
        session.query(Orders.orderpriority, func.count().label("order_count"))
        .filter(Orders.orderdate >= p["date"],
                Orders.orderdate < p["date_end"],
                exists_q)
        .group_by(Orders.orderpriority)
        .order_by(Orders.orderpriority)
        .all()
    )
    return _dicts(rows, ["o_orderpriority", "order_count"])


# ---------------------------------------------------------------- Q5
def q05(session: Session, p):
    rows = (
        session.query(Nation.name,
                      func.sum(LineItem.extendedprice * (1 - LineItem.discount)).label("revenue"))
        .filter(Customer.custkey == Orders.custkey_id,
                LineItem.orderkey_id == Orders.orderkey,
                LineItem.suppkey_id == Supplier.suppkey,
                Customer.nationkey_id == Supplier.nationkey_id,
                Supplier.nationkey_id == Nation.nationkey,
                Nation.regionkey_id == Region.regionkey,
                Region.name == p["region"],
                Orders.orderdate >= p["date"],
                Orders.orderdate < p["date_end"])
        .group_by(Nation.name)
        .order_by(func.sum(LineItem.extendedprice * (1 - LineItem.discount)).desc())
        .all()
    )
    return _dicts(rows, ["n_name", "revenue"])


# ---------------------------------------------------------------- Q6
def q06(session: Session, p):
    row = (
        session.query(func.sum(LineItem.extendedprice * LineItem.discount).label("revenue"))
        .filter(LineItem.shipdate >= p["date"],
                LineItem.shipdate < p["date_end"],
                LineItem.discount >= p["disc_lo"],
                LineItem.discount <= p["disc_hi"],
                LineItem.quantity < p["quantity"])
        .one()
    )
    return [{"revenue": row[0]}]


# ---------------------------------------------------------------- Q7
def q07(session: Session, p):
    n1, n2 = aliased(Nation), aliased(Nation)
    year = func.extract("year", LineItem.shipdate).label("l_year")
    volume = (LineItem.extendedprice * (1 - LineItem.discount))
    rows = (
        session.query(n1.name.label("supp_nation"), n2.name.label("cust_nation"),
                      year, func.sum(volume).label("revenue"))
        .filter(Supplier.suppkey == LineItem.suppkey_id,
                Orders.orderkey == LineItem.orderkey_id,
                Customer.custkey == Orders.custkey_id,
                Supplier.nationkey_id == n1.nationkey,
                Customer.nationkey_id == n2.nationkey,
                or_(and_(n1.name == p["nation1"], n2.name == p["nation2"]),
                    and_(n1.name == p["nation2"], n2.name == p["nation1"])),
                LineItem.shipdate.between(date(1995, 1, 1), date(1996, 12, 31)))
        .group_by(n1.name, n2.name, year)
        .order_by(n1.name, n2.name, year)
        .all()
    )
    return _dicts(rows, ["supp_nation", "cust_nation", "l_year", "revenue"])


# ---------------------------------------------------------------- Q8
def q08(session: Session, p):
    n1, n2 = aliased(Nation), aliased(Nation)
    year = func.extract("year", Orders.orderdate).label("o_year")
    volume = (LineItem.extendedprice * (1 - LineItem.discount))
    # Named for the parameter, not for BRAZIL: the nation is set 0's value,
    # not the query's definition.
    nation_volume = func.sum(case((n2.name == p["nation"], volume), else_=0))
    rows = (
        session.query(year, (nation_volume / func.sum(volume)).label("mkt_share"))
        .filter(Part.partkey == LineItem.partkey_id,
                Supplier.suppkey == LineItem.suppkey_id,
                LineItem.orderkey_id == Orders.orderkey,
                Orders.custkey_id == Customer.custkey,
                Customer.nationkey_id == n1.nationkey,
                n1.regionkey_id == Region.regionkey,
                Region.name == p["region"],
                Supplier.nationkey_id == n2.nationkey,
                Orders.orderdate.between(date(1995, 1, 1), date(1996, 12, 31)),
                Part.type == p["type"])
        .group_by(year)
        .order_by(year)
        .all()
    )
    return _dicts(rows, ["o_year", "mkt_share"])


# ---------------------------------------------------------------- Q9
def q09(session: Session, p):
    year = func.extract("year", Orders.orderdate).label("o_year")
    amount = (LineItem.extendedprice * (1 - LineItem.discount)
              - PartSupp.supplycost * LineItem.quantity)
    rows = (
        session.query(Nation.name.label("nation"), year,
                      func.sum(amount).label("sum_profit"))
        .filter(Supplier.suppkey == LineItem.suppkey_id,
                PartSupp.suppkey_id == LineItem.suppkey_id,
                PartSupp.partkey_id == LineItem.partkey_id,
                Part.partkey == LineItem.partkey_id,
                Orders.orderkey == LineItem.orderkey_id,
                Supplier.nationkey_id == Nation.nationkey,
                Part.name.like("%%%s%%" % p["color"]))
        .group_by(Nation.name, year)
        .order_by(Nation.name, year.desc())
        .all()
    )
    return _dicts(rows, ["nation", "o_year", "sum_profit"])


# ---------------------------------------------------------------- Q10
def q10(session: Session, p):
    revenue = func.sum(LineItem.extendedprice * (1 - LineItem.discount))
    rows = (
        session.query(Customer.custkey, Customer.name, revenue.label("revenue"),
                      Customer.acctbal, Nation.name, Customer.address,
                      Customer.phone, Customer.comment)
        .filter(Customer.custkey == Orders.custkey_id,
                LineItem.orderkey_id == Orders.orderkey,
                Orders.orderdate >= p["date"],
                Orders.orderdate < p["date_end"],
                LineItem.returnflag == "R",
                Customer.nationkey_id == Nation.nationkey)
        .group_by(Customer.custkey, Customer.name, Customer.acctbal,
                  Customer.phone, Nation.name, Customer.address, Customer.comment)
        .order_by(revenue.desc())
        .limit(20)
        .all()
    )
    return _dicts(rows, ["c_custkey", "c_name", "revenue", "c_acctbal",
                         "n_name", "c_address", "c_phone", "c_comment"])


# ---------------------------------------------------------------- Q11
def q11(session: Session, p):
    ps2, s2, n2 = aliased(PartSupp), aliased(Supplier), aliased(Nation)
    threshold = (
        # FRACTION is 0.0001/SF, not 0.0001. See _sql.Q11_FRACTION.
        select(func.sum(ps2.supplycost * ps2.availqty)
               * Decimal(repr(Q11_FRACTION)))
        .where(and_(ps2.suppkey_id == s2.suppkey,
                    s2.nationkey_id == n2.nationkey,
                    n2.name == p["nation"]))
        .scalar_subquery()
    )
    value = func.sum(PartSupp.supplycost * PartSupp.availqty)
    rows = (
        session.query(PartSupp.partkey_id, value.label("value"))
        .filter(PartSupp.suppkey_id == Supplier.suppkey,
                Supplier.nationkey_id == Nation.nationkey,
                Nation.name == p["nation"])
        .group_by(PartSupp.partkey_id)
        .having(value > threshold)
        .order_by(value.desc())
        .all()
    )
    return _dicts(rows, ["ps_partkey", "value"])


# ---------------------------------------------------------------- Q12
def q12(session: Session, p):
    high = func.sum(case((or_(Orders.orderpriority == "1-URGENT",
                              Orders.orderpriority == "2-HIGH"), 1), else_=0))
    low = func.sum(case((and_(Orders.orderpriority != "1-URGENT",
                              Orders.orderpriority != "2-HIGH"), 1), else_=0))
    rows = (
        session.query(LineItem.shipmode, high.label("high_line_count"),
                      low.label("low_line_count"))
        .filter(Orders.orderkey == LineItem.orderkey_id,
                LineItem.shipmode.in_([p["shipmode1"], p["shipmode2"]]),
                LineItem.commitdate < LineItem.receiptdate,
                LineItem.shipdate < LineItem.commitdate,
                LineItem.receiptdate >= p["date"],
                LineItem.receiptdate < p["date_end"])
        .group_by(LineItem.shipmode)
        .order_by(LineItem.shipmode)
        .all()
    )
    return _dicts(rows, ["l_shipmode", "high_line_count", "low_line_count"])


# ---------------------------------------------------------------- Q13
def q13(session: Session, p):
    inner = (
        session.query(Customer.custkey.label("c_custkey"),
                      func.count(Orders.orderkey).label("c_count"))
        .outerjoin(Orders, and_(Customer.custkey == Orders.custkey_id,
                                Orders.comment.notlike("%%%s%%%s%%" % (p["word1"], p["word2"]))))
        .group_by(Customer.custkey)
        .subquery()
    )
    rows = (
        session.query(inner.c.c_count, func.count().label("custdist"))
        .group_by(inner.c.c_count)
        .order_by(func.count().desc(), inner.c.c_count.desc())
        .all()
    )
    return _dicts(rows, ["c_count", "custdist"])


# ---------------------------------------------------------------- Q14
def q14(session: Session, p):
    disc = LineItem.extendedprice * (1 - LineItem.discount)
    promo = func.sum(case((Part.type.like("PROMO%"), disc), else_=0))
    row = (
        session.query((100.00 * promo / func.sum(disc)).label("promo_revenue"))
        .filter(LineItem.partkey_id == Part.partkey,
                LineItem.shipdate >= p["date"],
                LineItem.shipdate < p["date_end"])
        .one()
    )
    return [{"promo_revenue": row[0]}]


# ---------------------------------------------------------------- Q15
def q15(session: Session, p):
    rev = (
        session.query(LineItem.suppkey_id.label("supplier_no"),
                      func.sum(LineItem.extendedprice * (1 - LineItem.discount)).label("total_revenue"))
        .filter(LineItem.shipdate >= p["date"],
                LineItem.shipdate < p["date_end"])
        .group_by(LineItem.suppkey_id)
        .subquery()
    )
    max_rev = select(func.max(rev.c.total_revenue)).scalar_subquery()
    rows = (
        session.query(Supplier.suppkey, Supplier.name, Supplier.address,
                      Supplier.phone, rev.c.total_revenue)
        .filter(Supplier.suppkey == rev.c.supplier_no,
                rev.c.total_revenue == max_rev)
        .order_by(Supplier.suppkey)
        .all()
    )
    return _dicts(rows, ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"])


# ---------------------------------------------------------------- Q16
def q16(session: Session, p):
    bad_supp = (
        select(Supplier.suppkey)
        .where(Supplier.comment.like("%Customer%Complaints%"))
        .scalar_subquery()
    )
    cnt = func.count(distinct(PartSupp.suppkey_id))
    rows = (
        session.query(Part.brand, Part.type, Part.size, cnt.label("supplier_cnt"))
        .filter(Part.partkey == PartSupp.partkey_id,
                Part.brand != p["brand"],
                Part.type.notlike("%s%%" % p["type"]),
                Part.size.in_(p["sizes"]),
                PartSupp.suppkey_id.notin_(bad_supp))
        .group_by(Part.brand, Part.type, Part.size)
        .order_by(cnt.desc(), Part.brand, Part.type, Part.size)
        .all()
    )
    return _dicts(rows, ["p_brand", "p_type", "p_size", "supplier_cnt"])


# ---------------------------------------------------------------- Q17
def q17(session: Session, p):
    l2 = aliased(LineItem)
    avg_qty = (
        select(Decimal("0.2") * func.avg(l2.quantity))
        .where(l2.partkey_id == Part.partkey)
        .scalar_subquery()
    )
    row = (
        session.query((func.sum(LineItem.extendedprice) / 7.0).label("avg_yearly"))
        .filter(Part.partkey == LineItem.partkey_id,
                Part.brand == p["brand"],
                Part.container == p["container"],
                LineItem.quantity < avg_qty)
        .one()
    )
    return [{"avg_yearly": row[0]}]


# ---------------------------------------------------------------- Q18
def q18(session: Session, p):
    l2 = aliased(LineItem)
    big_orders = (
        select(l2.orderkey_id)
        .group_by(l2.orderkey_id)
        .having(func.sum(l2.quantity) > p["quantity"])
        .scalar_subquery()
    )
    rows = (
        session.query(Customer.name, Customer.custkey, Orders.orderkey,
                      Orders.orderdate, Orders.totalprice,
                      func.sum(LineItem.quantity).label("total_qty"))
        .filter(Orders.orderkey.in_(big_orders),
                Customer.custkey == Orders.custkey_id,
                Orders.orderkey == LineItem.orderkey_id)
        .group_by(Customer.name, Customer.custkey, Orders.orderkey,
                  Orders.orderdate, Orders.totalprice)
        .order_by(Orders.totalprice.desc(), Orders.orderdate)
        .limit(100)
        .all()
    )
    return _dicts(rows, ["c_name", "c_custkey", "o_orderkey", "o_orderdate",
                         "o_totalprice", "total_qty"])


# ---------------------------------------------------------------- Q19
def q19(session: Session, p):
    def branch(brand, containers, qlo, size_hi):
        return and_(Part.partkey == LineItem.partkey_id,
                    Part.brand == brand,
                    Part.container.in_(containers),
                    LineItem.quantity >= qlo,
                    LineItem.quantity <= qlo + 10,
                    Part.size.between(1, size_hi),
                    LineItem.shipmode.in_(["AIR", "AIR REG"]),
                    LineItem.shipinstruct == "DELIVER IN PERSON")

    row = (
        session.query(func.sum(LineItem.extendedprice * (1 - LineItem.discount)).label("revenue"))
        .filter(or_(
            branch(p["brand1"], ["SM CASE", "SM BOX", "SM PACK", "SM PKG"], p["quantity1"], 5),
            branch(p["brand2"], ["MED BAG", "MED BOX", "MED PKG", "MED PACK"], p["quantity2"], 10),
            branch(p["brand3"], ["LG CASE", "LG BOX", "LG PACK", "LG PKG"], p["quantity3"], 15),
        ))
        .one()
    )
    return [{"revenue": row[0]}]


# ---------------------------------------------------------------- Q20
def q20(session: Session, p):
    forest_parts = (
        select(Part.partkey).where(Part.name.like("%s%%" % p["color"])).scalar_subquery()
    )
    half_qty = (
        select(Decimal("0.5") * func.sum(LineItem.quantity))
        .where(and_(LineItem.partkey_id == PartSupp.partkey_id,
                    LineItem.suppkey_id == PartSupp.suppkey_id,
                    LineItem.shipdate >= p["date"],
                    LineItem.shipdate < p["date_end"]))
        .scalar_subquery()
    )
    good_supp = (
        select(PartSupp.suppkey_id)
        .where(and_(PartSupp.partkey_id.in_(forest_parts),
                    PartSupp.availqty > half_qty))
        .scalar_subquery()
    )
    rows = (
        session.query(Supplier.name, Supplier.address)
        .filter(Supplier.suppkey.in_(good_supp),
                Supplier.nationkey_id == Nation.nationkey,
                Nation.name == p["nation"])
        .order_by(Supplier.name)
        .all()
    )
    return _dicts(rows, ["s_name", "s_address"])


# ---------------------------------------------------------------- Q21
def q21(session: Session, p):
    l1, l2, l3 = aliased(LineItem), aliased(LineItem), aliased(LineItem)
    exists_other = (
        select(literal_column("1"))
        .where(and_(l2.orderkey_id == l1.orderkey_id,
                    l2.suppkey_id != l1.suppkey_id))
        .exists()
    )
    not_exists_late = (
        select(literal_column("1"))
        .where(and_(l3.orderkey_id == l1.orderkey_id,
                    l3.suppkey_id != l1.suppkey_id,
                    l3.receiptdate > l3.commitdate))
        .exists()
    )
    cnt = func.count()
    rows = (
        session.query(Supplier.name, cnt.label("numwait"))
        .filter(Supplier.suppkey == l1.suppkey_id,
                Orders.orderkey == l1.orderkey_id,
                Orders.orderstatus == "F",
                l1.receiptdate > l1.commitdate,
                exists_other,
                ~not_exists_late,
                Supplier.nationkey_id == Nation.nationkey,
                Nation.name == p["nation"])
        .group_by(Supplier.name)
        .order_by(cnt.desc(), Supplier.name)
        .limit(100)
        .all()
    )
    return _dicts(rows, ["s_name", "numwait"])


# ---------------------------------------------------------------- Q22
class _substr(FunctionElement):
    """Substring, spelled the way each dialect spells it.

    `func.substr(...)` emits the name verbatim. PostgreSQL, MySQL and Oracle all
    have `substr`, so Q22 worked on three systems and raised on the fourth:
    SQL Server's function is `SUBSTRING`, and the ORM path failed with
    "'substr' is not a recognized built-in function name". This mirrors what
    `_sql.py`'s `sql_for()` already does for the hand-written baselines, where
    the SQL Server branch substitutes `SUBSTRING(c_phone, 1, 2)`.

    Written as a compiled construct rather than a branch on the session's
    dialect so that the query still reads as one expression and the dialect
    choice happens where SQLAlchemy makes every other dialect choice.
    """
    name = "substr"
    inherit_cache = True
    # Without an explicit type this compiles as NullType, and the IN comparison
    # and the GROUP BY label below both depend on it being a string.
    type = String()


@compiles(_substr)
def _substr_default(element, compiler, **kw):
    return "substr(%s)" % compiler.process(element.clauses, **kw)


@compiles(_substr, "mssql")
def _substr_mssql(element, compiler, **kw):
    return "SUBSTRING(%s)" % compiler.process(element.clauses, **kw)


def q22(session: Session, p):
    codes = list(p["country_codes"])
    cc = _substr(Customer.phone, 1, 2)
    c2 = aliased(Customer)
    avg_bal = (
        select(func.avg(c2.acctbal))
        .where(and_(c2.acctbal > Decimal("0.00"),
                    _substr(c2.phone, 1, 2).in_(codes)))
        .scalar_subquery()
    )
    no_orders = (
        select(literal_column("1"))
        .where(Orders.custkey_id == Customer.custkey)
        .exists()
    )
    inner = (
        session.query(cc.label("cntrycode"), Customer.acctbal.label("c_acctbal"))
        .filter(cc.in_(codes), Customer.acctbal > avg_bal, ~no_orders)
        .subquery()
    )
    rows = (
        session.query(inner.c.cntrycode, func.count().label("numcust"),
                      func.sum(inner.c.c_acctbal).label("totacctbal"))
        .group_by(inner.c.cntrycode)
        .order_by(inner.c.cntrycode)
        .all()
    )
    return _dicts(rows, ["cntrycode", "numcust", "totacctbal"])


REGISTRY = {i: globals()[f"q{i:02d}"] for i in range(1, 23)}
