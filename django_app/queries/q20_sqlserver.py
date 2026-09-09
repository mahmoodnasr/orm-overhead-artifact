"""
TPC-H Query 20 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""

from decimal import Decimal
from django.db.models import (
    Sum,
    F,
    Q,
    Subquery,
    OuterRef,
    DecimalField,
    ExpressionWrapper,
)
from ..models import Supplier, Nation, PartSupp, Part, LineItem
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q20 via Django ORM."""
    P = _paramset(20, params)

    # Get parts starting with 'forest'
    forest_parts = (
        Part.objects.using(using)
        .filter(name__startswith=P["color"])
        .values_list("partkey", flat=True)
    )

    # Calculate 50% of sum of quantity for each part-supplier combination
    lineitem_threshold = (
        LineItem.objects.filter(
            partkey=OuterRef("partkey"),
            suppkey=OuterRef("suppkey"),
            shipdate__gte=P["date"],
            shipdate__lt=P["date_end"],
        )
        .values("partkey", "suppkey")
        .annotate(
            half_qty=ExpressionWrapper(
                Sum("quantity") * Decimal("0.5"), output_field=DecimalField()
            )
        )
        .values("half_qty")
    )

    # Get suppliers with excess inventory
    eligible_suppliers = (
        PartSupp.objects.using(using)
        .filter(partkey__in=forest_parts, availqty__gt=Subquery(lineitem_threshold))
        .values_list("suppkey", flat=True)
        .distinct()
    )

    results = (
        Supplier.objects.using(using)
        .select_related("nationkey")
        .filter(suppkey__in=eligible_suppliers, nationkey__name=P["nation"])
        .annotate(s_name=F("name"), s_address=F("address"))
        .values("s_name", "s_address")
        .order_by("s_name")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q20 via direct SQL."""
    P = _paramset(20, params)

    sql = f"""
    SELECT s_name, s_address
    FROM supplier, nation
    WHERE s_suppkey IN (
        SELECT ps_suppkey
        FROM partsupp
        WHERE ps_partkey IN (
            SELECT p_partkey
            FROM part
            WHERE p_name LIKE '{P["color"]}%'
          )
          AND ps_availqty > (
            SELECT 0.5 * SUM(l_quantity)
            FROM lineitem
            WHERE l_partkey = ps_partkey
              AND l_suppkey = ps_suppkey
              AND l_shipdate >= CAST('{P["date"]}' AS DATE)
              AND l_shipdate < CAST('{P["date_end"]}' AS DATE)
          )
      )
      AND s_nationkey = n_nationkey
      AND n_name = '{P["nation"]}'
    ORDER BY s_name
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 20,
        "name": "Potential Part Promotion",
        "complexity": "Complex",
        "description": "Suppliers with excess inventory for specific parts",
        "tables": ["supplier", "nation", "partsupp", "part", "lineitem"],
        "joins": 4,
        "aggregations": 1,
        "subqueries": 3,
    }
