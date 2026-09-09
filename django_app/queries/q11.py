"""
TPC-H Query 11: Important Stock Identification
Medium complexity - parts with significant inventory value
"""

from decimal import Decimal
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Subquery, OuterRef
from ..models import PartSupp, Supplier, Nation
from tpch_paramsets import resolve as _paramset
from tpch_params import Q11_FRACTION


def run_query_orm(using="default", params=None):
    """Execute Q11 via Django ORM."""
    P = _paramset(11, params)

    # FRACTION is 0.0001/SF, not 0.0001. Held at 0.0001 the HAVING clause
    # excludes every group above SF1 and the query returns nothing while still
    # doing all the aggregation work, so it looks like a valid measurement.
    total_value = PartSupp.objects.using(using).filter(
        suppkey__nationkey__name=P["nation"]
    ).aggregate(
        total=Sum(F("supplycost") * F("availqty"), output_field=DecimalField())
    )["total"] or Decimal("0")

    threshold = total_value * Decimal(repr(Q11_FRACTION))

    results = (
        PartSupp.objects.using(using)
        .filter(suppkey__nationkey__name=P["nation"])
        .values("partkey")
        .annotate(
            value=Sum(
                ExpressionWrapper(
                    F("supplycost") * F("availqty"),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                )
            )
        )
        .filter(value__gt=threshold)
        .annotate(ps_partkey=F("partkey"))
        .order_by("-value")
        .values("ps_partkey", "value")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q11 via direct SQL."""
    P = _paramset(11, params)

    # The threshold is scale-dependent, so it is interpolated rather than
    # inlined. See tpch_params.Q11_FRACTION. It is rendered at twelve decimal
    # places: at SF10 the value is 0.00001, and %s would print it as 1e-05,
    # which is not valid SQL in every dialect. The width used to be applied by
    # a .replace() on a plain string; the statement is an f-string now and the
    # format spec does it directly, which removes the way that could silently
    # become a no-op.
    sql = f"""
    SELECT ps_partkey, SUM(ps_supplycost * ps_availqty) as value
    FROM partsupp, supplier, nation
    WHERE ps_suppkey = s_suppkey
      AND s_nationkey = n_nationkey
      AND n_name = '{P["nation"]}'
    GROUP BY ps_partkey
    HAVING SUM(ps_supplycost * ps_availqty) > (
      SELECT SUM(ps_supplycost * ps_availqty) * {P["fraction"]:.12f}
      FROM partsupp, supplier, nation
      WHERE ps_suppkey = s_suppkey
        AND s_nationkey = n_nationkey
        AND n_name = '{P["nation"]}'
    )
    ORDER BY value DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 11,
        "name": "Important Stock Identification",
        "complexity": "Medium",
        "description": "Parts with significant inventory value",
        "tables": ["partsupp", "supplier", "nation"],
        "joins": 2,
        "aggregations": 2,
        "subqueries": 1,
    }
