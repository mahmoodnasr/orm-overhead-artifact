"""
TPC-H Query 3 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""

from django.db.models import Sum, F, Q
from datetime import date
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """
    Execute TPC-H Q3 via Django ORM

    SELECT
        l_orderkey,
        SUM(l_extendedprice * (1 - l_discount)) as revenue,
        o_orderdate,
        o_shippriority
    FROM customer, orders, lineitem
    WHERE c_mktsegment = '{P['segment']}'
        AND c_custkey = o_custkey
        AND l_orderkey = o_orderkey
        AND o_orderdate < '{P['date']}'
        AND l_shipdate > '{P['date']}'
    GROUP BY l_orderkey, o_orderdate, o_shippriority
    ORDER BY revenue DESC, o_orderdate
    FETCH FIRST 10 ROWS ONLY
    """
    P = _paramset(3, params)
    from django_app.models import LineItem, Orders, Customer

    order_date = P["date"]
    ship_date = P["date"]

    results = (
        LineItem.objects.using(using)
        .select_related("orderkey__custkey")
        .filter(
            orderkey__custkey__mktsegment=P["segment"],
            orderkey__orderdate__lt=order_date,
            shipdate__gt=ship_date,
        )
        .values("orderkey", "orderkey__orderdate", "orderkey__shippriority")
        .annotate(revenue=Sum(F("extendedprice") * (1 - F("discount"))))
        .order_by("-revenue", "orderkey__orderdate")[:10]
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute TPC-H Q3 via direct SQL"""
    P = _paramset(3, params)
    sql = f"""
    SELECT TOP 10
        l_orderkey,
        SUM(l_extendedprice * (1 - l_discount)) as revenue,
        o_orderdate,
        o_shippriority
    FROM customer, orders, lineitem
    WHERE c_mktsegment = '{P["segment"]}'
        AND c_custkey = o_custkey
        AND l_orderkey = o_orderkey
        AND o_orderdate < '{P["date"]}'
        AND l_shipdate > '{P["date"]}'
    GROUP BY l_orderkey, o_orderdate, o_shippriority
    ORDER BY revenue DESC, o_orderdate
    
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query"""
    return {
        "number": 3,
        "name": "Shipping Priority",
        "complexity": "Medium",
        "description": "Retrieves top 10 unshipped orders with highest value",
        "tables": ["customer", "orders", "lineitem"],
        "joins": 2,
        "aggregations": 1,
        "subqueries": 0,
    }
