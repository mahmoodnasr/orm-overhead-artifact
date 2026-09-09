"""
TPC-H Query 15: Top Supplier
Complex - supplier with maximum total revenue in a period
"""

from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Max
from ..models import Supplier, LineItem
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q15 via Django ORM."""
    P = _paramset(15, params)

    # Calculate revenue for each supplier
    supplier_revenue = (
        LineItem.objects.using(using)
        .filter(shipdate__gte=P["date"], shipdate__lt=P["date_end"])
        .values("suppkey")
        .annotate(
            total_revenue=Sum(
                ExpressionWrapper(
                    F("extendedprice") * (1 - F("discount")),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                )
            )
        )
    )

    # Find max revenue
    max_revenue = supplier_revenue.aggregate(max_rev=Max("total_revenue"))["max_rev"]

    # Get suppliers with max revenue
    top_suppliers = supplier_revenue.filter(total_revenue=max_revenue)

    results = (
        Supplier.objects.using(using)
        .filter(suppkey__in=[s["suppkey"] for s in top_suppliers])
        .annotate(
            s_suppkey=F("suppkey"),
            s_name=F("name"),
            s_address=F("address"),
            s_phone=F("phone"),
        )
        .values("s_suppkey", "s_name", "s_address", "s_phone")
        .order_by("s_suppkey")
    )

    # Add revenue to results
    revenue_map = {s["suppkey"]: s["total_revenue"] for s in top_suppliers}
    results_list = list(results)
    for r in results_list:
        r["total_revenue"] = revenue_map.get(r["s_suppkey"])

    return results_list


def run_query_sql(connection, params=None):
    P = _paramset(15, params)

    # Get database vendor
    vendor = connection.vendor

    # Database-specific date literals
    if vendor == "mysql":
        date_start = f"'{P['date']}'"
    elif vendor == "microsoft":
        date_start = f"'{P['date']}'"
    elif vendor == "postgresql":
        date_start = f"DATE '{P['date']}'"
    else:  # Oracle
        date_start = f"TO_DATE('{P['date']}', 'YYYY-MM-DD')"

    if vendor == "mysql":
        date_end = f"'{P['date_end']}'"
    elif vendor == "microsoft":
        date_end = f"'{P['date_end']}'"
    elif vendor == "postgresql":
        date_end = f"DATE '{P['date_end']}'"
    else:  # Oracle
        date_end = f"TO_DATE('{P['date_end']}', 'YYYY-MM-DD')"

    """Execute Q15 via direct SQL."""

    sql = f"""
    WITH revenue0 (supplier_no, total_revenue) AS (
      SELECT l_suppkey, SUM(l_extendedprice * (1 - l_discount))
      FROM lineitem
      WHERE l_shipdate >= {date_start}
        AND l_shipdate < {date_end}
      GROUP BY l_suppkey
    )
    SELECT s_suppkey, s_name, s_address, s_phone, total_revenue
    FROM supplier, revenue0
    WHERE s_suppkey = supplier_no
      AND total_revenue = (SELECT MAX(total_revenue) FROM revenue0)
    ORDER BY s_suppkey
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 15,
        "name": "Top Supplier",
        "complexity": "Complex",
        "description": "Supplier with maximum total revenue in a period",
        "tables": ["supplier", "lineitem"],
        "joins": 1,
        "aggregations": 2,
        "subqueries": 1,
    }
