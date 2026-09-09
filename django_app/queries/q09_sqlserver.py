"""TPC-H Query 9 — SQL Server version.

This module exists for the `YEAR(o_orderdate)` spelling in the hand-written
baseline, and for one restriction in the ORM path that is SQL Server's own -
see `run_query_orm` below, which reaches PARTSUPP by a join because SQL Server
will not aggregate over an expression containing a subquery.

The ORM implementation here previously computed the wrong quantity. TPC-H Q9 sums *profit*,
`l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity`; this module
summed only the first term, never joining PARTSUPP for `ps_supplycost` at all.
Its own comments said so — "Note: This is simplified. Full implementation needs
PartSupp join for supplycost" — and it had been sitting in the repository in
that state, unexecuted, ever since.

It returned the right *shape*: 175 rows, the right nations, the right years,
sorted correctly, in a time indistinguishable from a correct run. Only the
values were wrong, by about 1.5x — ALGERIA/1998 came out at 414,006,807.63
against the 271,504,046.55 that the two hand-written baselines and the
SQLAlchemy ORM all agreed on. The `MATCH` and `ORM=SQL` checks caught it; no
amount of looking at the timings would have. Defect C16.

Importing the shared ORM rather than copying it is deliberate: a correction to
Q9's ORM must not be able to apply to three vendors and miss this one, which is
how defect C9 happened.
"""

from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.db.models.functions import ExtractYear
from ..models import Part, Supplier, LineItem, PartSupp, Orders, Nation
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q9 via Django ORM.

    The same query as the shared `q09.py`, reaching PARTSUPP by a join rather
    than by a correlated `Subquery`. It cannot simply import the shared version:
    that one puts the subquery inside the summed expression, and SQL Server
    rejects it outright with "Cannot perform an aggregate function on an
    expression containing an aggregate or a subquery" (error 130). The
    restriction is the server's, not the driver's, and there is no setting that
    relaxes it.

    Joining PARTSUPP on both key columns - `partkey__partsupp` gives the join on
    `ps_partkey`, and `partkey__partsupp__suppkey=F('suppkey')` completes it on
    `ps_suppkey` - produces the same rows with no subquery anywhere, which is
    also the shape the hand-written baseline below uses. Verified against all
    three other paths: 175 rows, ALGERIA/1998 = 271504046.5508.

    Note for the write-up: Django's Q9 therefore executes a different plan shape
    here than on the other three systems. Both arms of the SQL Server comparison
    still run against the same server in the same process, so the ORM-versus-SQL
    ratio in this row is sound; the absolute Q9 ORM time is not directly
    comparable across systems.
    """
    P = _paramset(9, params)
    results = (
        LineItem.objects.using(using)
        .filter(
            partkey__name__contains=P["color"],
            partkey__partsupp__suppkey=F("suppkey"),
        )
        .annotate(
            nation=F("suppkey__nationkey__name"),
            o_year=ExtractYear("orderkey__orderdate"),
            amount=ExpressionWrapper(
                F("extendedprice") * (1 - F("discount"))
                - F("partkey__partsupp__supplycost") * F("quantity"),
                output_field=DecimalField(max_digits=25, decimal_places=4),
            ),
        )
        .values("nation", "o_year")
        .annotate(sum_profit=Sum("amount"))
        .order_by("nation", "-o_year")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q9 via direct SQL."""
    P = _paramset(9, params)

    sql = rf"""
    SELECT nation, o_year, SUM(amount) as sum_profit
    FROM (
        SELECT n_name as nation,
               YEAR(o_orderdate) as o_year,
               l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity as amount
        FROM part, supplier, lineitem, partsupp, orders, nation
        WHERE s_suppkey = l_suppkey
          AND ps_suppkey = l_suppkey
          AND ps_partkey = l_partkey
          AND p_partkey = l_partkey
          AND o_orderkey = l_orderkey
          AND s_nationkey = n_nationkey
          -- The pattern is '%green%', written as concatenation on purpose.
          -- mssql-django's cursor applies re.sub(r'%\w+', '{{}}', sql) to any
          -- statement containing the string "GROUP BY" (mssql/base.py,
          -- CursorWrapper.execute -> format_group_by_params), which turns
          -- LIKE '%green%' into LIKE '{{}}%'. That matches nothing, so this
          -- baseline returned 0 rows in 0.74 s and would have been recorded as
          -- a fast, successful measurement of Q09. Writing every '%' followed
          -- by a quote leaves nothing for that regex to match; SQL Server folds
          -- the constants at compile time, so the plan is the literal's plan.
          -- See defect C14.
          AND p_name LIKE '%' + '{P["color"]}' + '%'
    ) as profit
    GROUP BY nation, o_year
    ORDER BY nation, o_year DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 9,
        "name": "Product Type Profit Measure",
        "complexity": "Very Complex",
        "description": "Profit for a specific product type by nation and year",
        "tables": ["part", "supplier", "lineitem", "partsupp", "orders", "nation"],
        "joins": 6,
        "aggregations": 1,
        "subqueries": 1,
        "features": [
            "Multi-table joins (6 tables)",
            "Profit calculation with multiple fields",
            "Date extraction",
            "Pattern matching (LIKE)",
            "Grouping by multiple dimensions",
        ],
        "parameters": {"part_name_pattern": "%green%"},
    }
