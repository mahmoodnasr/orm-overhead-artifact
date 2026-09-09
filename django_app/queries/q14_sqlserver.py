"""
TPC-H Query 14 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""

from django.db.models import (
    Sum,
    F,
    Q,
    Case,
    When,
    DecimalField,
    ExpressionWrapper,
    Value,
)
from ..models import LineItem, Part
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q14 via Django ORM."""
    P = _paramset(14, params)

    results = (
        LineItem.objects.using(using)
        .select_related("partkey")
        .filter(shipdate__gte=P["date"], shipdate__lt=P["date_end"])
        .aggregate(
            promo_revenue=ExpressionWrapper(
                Value(100.00)
                * Sum(
                    Case(
                        When(
                            partkey__type__startswith="PROMO",
                            then=F("extendedprice") * (1 - F("discount")),
                        ),
                        default=Value(0),
                        output_field=DecimalField(),
                    )
                )
                / Sum(F("extendedprice") * (1 - F("discount"))),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            )
        )
    )

    return [results]


def run_query_sql(connection, params=None):
    """Execute Q14 via direct SQL."""
    P = _paramset(14, params)

    sql = f"""
    SELECT 100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%'
                             THEN l_extendedprice * (1 - l_discount)
                             ELSE 0 END) / SUM(l_extendedprice * (1 - l_discount))
           as promo_revenue
    FROM lineitem, part
    WHERE l_partkey = p_partkey
      AND l_shipdate >= CAST('{P["date"]}' AS DATE)
      AND l_shipdate < CAST('{P["date_end"]}' AS DATE)
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 14,
        "name": "Promotion Effect",
        "complexity": "Simple",
        "description": "Percentage of revenue from promotional parts",
        "tables": ["lineitem", "part"],
        "joins": 1,
        "aggregations": 2,
        "subqueries": 0,
    }
