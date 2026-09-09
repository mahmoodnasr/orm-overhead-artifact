"""
TPC-H Query 8 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""

from django.db.models import Sum, F, Case, When, DecimalField, Value
from django.db.models.functions import ExtractYear
from decimal import Decimal
from ..models import Part, Supplier, LineItem, Orders, Customer, Nation, Region
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """
    Execute Q8 via Django ORM.

    Market share of BRAZIL for ECONOMY ANODIZED STEEL parts
    in AMERICA region during 1995-1996.
    """
    P = _paramset(8, params)
    # This is a very complex query with subqueries and conditional aggregation
    # We'll use a CTE-like approach with Django ORM

    # First, get all orders matching criteria
    results = (
        LineItem.objects.using(using)
        .select_related(
            "partkey", "suppkey__nationkey", "orderkey__custkey__nationkey__regionkey"
        )
        .filter(
            partkey__type=P["type"],
            orderkey__custkey__nationkey__regionkey__name=P["region"],
            orderkey__orderdate__gte="1995-01-01",
            orderkey__orderdate__lt="1997-01-01",
        )
        .annotate(
            o_year=ExtractYear("orderkey__orderdate"),
            volume=F("extendedprice") * (1 - F("discount")),
            nation=F("suppkey__nationkey__name"),
        )
        .values("o_year")
        .annotate(
            total_volume=Sum("volume"),
            brazil_volume=Sum(
                Case(
                    When(suppkey__nationkey__name=P["nation"], then=F("volume")),
                    default=Value(0),
                    output_field=DecimalField(),
                )
            ),
        )
        .annotate(mkt_share=F("brazil_volume") / F("total_volume"))
        .order_by("o_year")
        .values("o_year", "mkt_share")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q8 via direct SQL."""
    P = _paramset(8, params)

    sql = f"""
    SELECT o_year,
           SUM(CASE WHEN nation = '{P["nation"]}' THEN volume ELSE 0 END) / SUM(volume) as mkt_share
    FROM (
        SELECT YEAR(o_orderdate) as o_year,
               l_extendedprice * (1 - l_discount) as volume,
               n2.n_name as nation
        FROM part, supplier, lineitem, orders, customer, nation n1, nation n2, region
        WHERE p_partkey = l_partkey
          AND s_suppkey = l_suppkey
          AND l_orderkey = o_orderkey
          AND o_custkey = c_custkey
          AND c_nationkey = n1.n_nationkey
          AND n1.n_regionkey = r_regionkey
          AND r_name = '{P["region"]}'
          AND s_nationkey = n2.n_nationkey
          AND o_orderdate >= CAST('1995-01-01' AS DATE)
          AND o_orderdate < CAST('1997-01-01' AS DATE)
          AND p_type = '{P["type"]}'
    ) as all_nations
    GROUP BY o_year
    ORDER BY o_year
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 8,
        "name": "National Market Share",
        "complexity": "Very Complex",
        "description": "Market share of a specific nation for a part type over time in a region",
        "tables": [
            "part",
            "supplier",
            "lineitem",
            "orders",
            "customer",
            "nation",
            "region",
        ],
        "joins": 7,
        "aggregations": 2,
        "subqueries": 1,
        "features": [
            "Multi-table joins (7 tables)",
            "Conditional aggregation (CASE)",
            "Date extraction",
            "Self-join (nation table used twice)",
            "Subquery with aggregation",
        ],
        "parameters": {
            "nation": "BRAZIL",
            "region": "AMERICA",
            "part_type": "ECONOMY ANODIZED STEEL",
            "start_date": "1995-01-01",
            "end_date": "1997-01-01",
        },
    }
