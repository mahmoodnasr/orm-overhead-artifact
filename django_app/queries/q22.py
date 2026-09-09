"""
TPC-H Query 22: Global Sales Opportunity
Very Complex - potential customers who haven't placed orders
"""

from django.db.models import Count, Sum, F, Avg, Exists, OuterRef, Q, Value
from django.db.models.functions import Substr
from ..models import Customer, Orders
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q22 via Django ORM."""
    P = _paramset(22, params)

    # Country codes of interest
    country_codes = list(P["country_codes"])

    # Calculate average account balance for customers with positive balance in these countries
    # Build Q objects for phone startswith filter
    phone_filters = Q()
    for code in country_codes:
        phone_filters |= Q(phone__startswith=code)

    avg_acctbal = (
        Customer.objects.using(using)
        .filter(phone_filters, acctbal__gt=0)
        .aggregate(avg_bal=Avg("acctbal"))["avg_bal"]
        or 0
    )

    # Subquery to check if customer has any orders
    has_orders = Orders.objects.filter(custkey=OuterRef("custkey"))

    results = (
        Customer.objects.using(using)
        .annotate(cntrycode=Substr("phone", 1, 2), has_order=Exists(has_orders))
        .filter(cntrycode__in=country_codes, acctbal__gt=avg_acctbal, has_order=False)
        .values("cntrycode")
        .annotate(numcust=Count("custkey"), totacctbal=Sum("acctbal"))
        .order_by("cntrycode")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q22 via direct SQL."""
    P = _paramset(22, params)

    # Get database vendor
    vendor = connection.vendor

    # Database-specific SUBSTR/SUBSTRING function
    # Use only forms that are valid in PostgreSQL to avoid accidental syntax
    # errors if the wrong branch is hit.
    if vendor in ["mysql", "microsoft"]:
        # MySQL and SQL Server: SUBSTRING(str, pos, len)
        substr_func = "SUBSTRING(c_phone, 1, 2)"
    elif vendor == "postgresql":
        # PostgreSQL supports SUBSTRING(str, pos, len)
        substr_func = "SUBSTRING(c_phone, 1, 2)"
    else:  # Oracle
        # Oracle supports SUBSTR(str, pos, len) — avoid the \"FROM ... FOR ...\" form
        # so that this SQL stays acceptable to PostgreSQL if misrouted.
        substr_func = "SUBSTR(c_phone, 1, 2)"

    sql = f"""
    SELECT cntrycode, COUNT(*) as numcust, SUM(c_acctbal) as totacctbal
    FROM (
      SELECT {substr_func} as cntrycode, c_acctbal
      FROM customer
      WHERE {substr_func} IN ({P["codes_sql_spaced"]})
        AND c_acctbal > (
          SELECT AVG(c_acctbal)
          FROM customer
          WHERE c_acctbal > 0.00
            AND {substr_func} IN ({P["codes_sql_spaced"]})
        )
        AND NOT EXISTS (
          SELECT * FROM orders
          WHERE o_custkey = c_custkey
        )
    ) as custsale
    GROUP BY cntrycode
    ORDER BY cntrycode
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 22,
        "name": "Global Sales Opportunity",
        "complexity": "Very Complex",
        "description": "Potential customers who haven't placed orders",
        "tables": ["customer", "orders"],
        "joins": 1,
        "aggregations": 3,
        "subqueries": 2,
        "features": [
            "String manipulation (SUBSTR)",
            "NOT EXISTS subquery",
            "Aggregate in WHERE clause",
            "Nested subquery structure",
        ],
    }
