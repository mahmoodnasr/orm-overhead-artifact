"""
TPC-H Query 21: Suppliers Who Kept Orders Waiting
Very Complex - suppliers with items that were committed late
"""

from django.db.models import Count, F, Exists, OuterRef, Q
from ..models import Supplier, LineItem, Orders, Nation
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q21 via Django ORM."""
    P = _paramset(21, params)

    # This query is very complex with EXISTS and NOT EXISTS subqueries
    # Checking for multi-supplier orders and late items

    # Subquery: Check if there are other suppliers for same order
    other_suppliers_exist = LineItem.objects.filter(
        Q(orderkey=OuterRef("orderkey")) & ~Q(suppkey=OuterRef("suppkey"))
    )

    # Subquery: Check if NO other supplier was also late
    other_late_suppliers_exist = LineItem.objects.filter(
        Q(orderkey=OuterRef("orderkey"))
        & ~Q(suppkey=OuterRef("suppkey"))
        & Q(receiptdate__gt=F("commitdate"))
    )

    results = (
        LineItem.objects.using(using)
        .select_related("suppkey__nationkey", "orderkey")
        .filter(
            orderkey__orderstatus="F",
            receiptdate__gt=F("commitdate"),
            suppkey__nationkey__name=P["nation"],
        )
        .annotate(
            has_other_suppliers=Exists(other_suppliers_exist),
            has_other_late_suppliers=Exists(other_late_suppliers_exist),
        )
        .filter(has_other_suppliers=True, has_other_late_suppliers=False)
        .annotate(s_name=F("suppkey__name"))
        .values("s_name")
        .annotate(numwait=Count("orderkey", distinct=True))
        .order_by("-numwait", "s_name")[:100]
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q21 via direct SQL."""
    P = _paramset(21, params)

    # Get database vendor
    vendor = connection.vendor

    # Database-specific LIMIT clause
    if vendor == "mysql":
        limit_clause = "LIMIT 100"
    elif vendor == "microsoft":
        limit_clause = "OFFSET 0 ROWS FETCH NEXT 100 ROWS ONLY"
    else:  # PostgreSQL, Oracle
        limit_clause = "FETCH FIRST 100 ROWS ONLY"

    sql = f"""
    SELECT s_name, COUNT(*) as numwait
    FROM supplier, lineitem l1, orders, nation
    WHERE s_suppkey = l1.l_suppkey
      AND o_orderkey = l1.l_orderkey
      AND o_orderstatus = 'F'
      AND l1.l_receiptdate > l1.l_commitdate
      AND EXISTS (
        SELECT * FROM lineitem l2
        WHERE l2.l_orderkey = l1.l_orderkey
          AND l2.l_suppkey <> l1.l_suppkey
      )
      AND NOT EXISTS (
        SELECT * FROM lineitem l3
        WHERE l3.l_orderkey = l1.l_orderkey
          AND l3.l_suppkey <> l1.l_suppkey
          AND l3.l_receiptdate > l3.l_commitdate
      )
      AND s_nationkey = n_nationkey
      AND n_name = '{P["nation"]}'
    GROUP BY s_name
    ORDER BY numwait DESC, s_name
    {limit_clause}
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 21,
        "name": "Suppliers Who Kept Orders Waiting",
        "complexity": "Very Complex",
        "description": "Suppliers with items that were committed late",
        "tables": ["supplier", "lineitem", "orders", "nation"],
        "joins": 3,
        "aggregations": 1,
        "subqueries": 2,
        "features": [
            "EXISTS subqueries",
            "NOT EXISTS subqueries",
            "Self-join (lineitem referenced 3 times)",
            "Complex filtering logic",
        ],
    }
