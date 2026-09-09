"""
TPC-H Query 1: Pricing Summary Report Query
Simple aggregation with filtering
"""

from django.db.models import Sum, Avg, Count, F, Q
from decimal import Decimal
from datetime import date
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """
    Execute TPC-H Q1 via Django ORM

    SELECT
        l_returnflag,
        l_linestatus,
        SUM(l_quantity) as sum_qty,
        SUM(l_extendedprice) as sum_base_price,
        SUM(l_extendedprice * (1 - l_discount)) as sum_disc_price,
        SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) as sum_charge,
        AVG(l_quantity) as avg_qty,
        AVG(l_extendedprice) as avg_price,
        AVG(l_discount) as avg_disc,
        COUNT(*) as count_order
    FROM lineitem
    WHERE l_shipdate <= '{P['date']}'
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
    """
    P = _paramset(1, params)
    from django_app.models import LineItem

    cutoff_date = P["date"]

    results = (
        LineItem.objects.using(using)
        .filter(shipdate__lte=cutoff_date)
        .values("returnflag", "linestatus")
        .annotate(
            sum_qty=Sum("quantity"),
            sum_base_price=Sum("extendedprice"),
            sum_disc_price=Sum(F("extendedprice") * (1 - F("discount"))),
            sum_charge=Sum(F("extendedprice") * (1 - F("discount")) * (1 + F("tax"))),
            avg_qty=Avg("quantity"),
            avg_price=Avg("extendedprice"),
            avg_disc=Avg("discount"),
            count_order=Count("*"),
        )
        .order_by("returnflag", "linestatus")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """
    Execute TPC-H Q1 via direct SQL

    Args:
        connection: Database connection object

    Returns:
        List of result tuples
    """
    P = _paramset(1, params)
    sql = f"""
    SELECT
        l_returnflag,
        l_linestatus,
        SUM(l_quantity) as sum_qty,
        SUM(l_extendedprice) as sum_base_price,
        SUM(l_extendedprice * (1 - l_discount)) as sum_disc_price,
        SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) as sum_charge,
        AVG(l_quantity) as avg_qty,
        AVG(l_extendedprice) as avg_price,
        AVG(l_discount) as avg_disc,
        COUNT(*) as count_order
    FROM lineitem
    WHERE l_shipdate <= '{P["date"]}'
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query"""
    return {
        "number": 1,
        "name": "Pricing Summary Report",
        "complexity": "Medium",
        "description": "Reports summary pricing information for shipped line items",
        "tables": ["lineitem"],
        "joins": 0,
        "aggregations": 8,
        "subqueries": 0,
    }
