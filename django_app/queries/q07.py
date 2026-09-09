"""
TPC-H Query 7: Volume Shipping
Complex - shipping volume between two nations
"""

from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
from django.db.models.functions import ExtractYear
from ..models import Supplier, LineItem, Orders, Customer, Nation
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q7 via Django ORM."""
    P = _paramset(7, params)

    results = (
        LineItem.objects.using(using)
        .select_related("suppkey__nationkey", "orderkey__custkey__nationkey")
        .filter(
            (
                Q(suppkey__nationkey__name=P["nation1"])
                & Q(orderkey__custkey__nationkey__name=P["nation2"])
            )
            | (
                Q(suppkey__nationkey__name=P["nation2"])
                & Q(orderkey__custkey__nationkey__name=P["nation1"])
            ),
            shipdate__gte="1995-01-01",
            shipdate__lte="1996-12-31",
        )
        .annotate(
            supp_nation=F("suppkey__nationkey__name"),
            cust_nation=F("orderkey__custkey__nationkey__name"),
            l_year=ExtractYear("shipdate"),
            volume=ExpressionWrapper(
                F("extendedprice") * (1 - F("discount")),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            ),
        )
        .values("supp_nation", "cust_nation", "l_year")
        .annotate(revenue=Sum("volume"))
        .order_by("supp_nation", "cust_nation", "l_year")
    )

    return list(results)


def run_query_sql(connection, params=None):
    P = _paramset(7, params)

    # Get database vendor
    vendor = connection.vendor

    # Database-specific date literals
    if vendor == "mysql":
        date_start = "'1995-01-01'"
    elif vendor == "microsoft":
        date_start = "'1995-01-01'"
    elif vendor == "postgresql":
        date_start = "DATE '1995-01-01'"
    else:  # Oracle
        date_start = "{date_start}"

    if vendor == "mysql":
        date_end = "'1996-12-31'"
    elif vendor == "microsoft":
        date_end = "'1996-12-31'"
    elif vendor == "postgresql":
        date_end = "DATE '1996-12-31'"
    else:  # Oracle
        date_end = "{date_end}"

    """Execute Q7 via direct SQL."""

    sql = f"""
    SELECT supp_nation, cust_nation, l_year, SUM(volume) as revenue
    FROM (
      SELECT n1.n_name as supp_nation, n2.n_name as cust_nation,
             EXTRACT(year FROM l_shipdate) as l_year,
             l_extendedprice * (1 - l_discount) as volume
      FROM supplier, lineitem, orders, customer, nation n1, nation n2
      WHERE s_suppkey = l_suppkey
        AND o_orderkey = l_orderkey
        AND c_custkey = o_custkey
        AND s_nationkey = n1.n_nationkey
        AND c_nationkey = n2.n_nationkey
        AND ((n1.n_name = '{P["nation1"]}' AND n2.n_name = '{P["nation2"]}')
          OR (n1.n_name = '{P["nation2"]}' AND n2.n_name = '{P["nation1"]}'))
        AND l_shipdate BETWEEN {date_start} AND {date_end}
    ) as shipping
    GROUP BY supp_nation, cust_nation, l_year
    ORDER BY supp_nation, cust_nation, l_year
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 7,
        "name": "Volume Shipping",
        "complexity": "Complex",
        "description": "Shipping volume between two nations",
        "tables": ["supplier", "lineitem", "orders", "customer", "nation"],
        "joins": 4,
        "aggregations": 1,
        "subqueries": 1,
    }
