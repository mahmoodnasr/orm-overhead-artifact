"""
TPC-H Query 9: Product Type Profit Measure
Very Complex - 6 table joins, profit by nation and year.

Fixed: the previous ORM implementation omitted the PARTSUPP join and therefore
summed revenue rather than profit. Its own comment recorded the omission
("This is simplified. Full implementation needs PartSupp join for supplycost").
Validated against run_query_sql on TPC-H SF1: 175 rows, identical sums.

The supplycost lookup is expressed as a correlated Subquery because LineItem has
no direct relation to PartSupp; the join is on the (partkey, suppkey) pair.
The name predicate uses `contains`, not `icontains`: TPC-H specifies a
case-sensitive LIKE '%green%'.
"""

from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper, OuterRef, Subquery
from django.db.models.functions import ExtractYear
from ..models import Part, Supplier, LineItem, PartSupp, Orders, Nation
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q9 via Django ORM."""
    P = _paramset(9, params)

    supplycost = Subquery(
        PartSupp.objects
        .using(using)
        .filter(partkey=OuterRef('partkey'), suppkey=OuterRef('suppkey'))
        .values('supplycost')[:1],
        output_field=DecimalField(max_digits=15, decimal_places=2),
    )

    results = (
        LineItem.objects
        .using(using)
        .filter(partkey__name__contains=P['color'])
        .annotate(
            nation=F('suppkey__nationkey__name'),
            o_year=ExtractYear('orderkey__orderdate'),
            amount=ExpressionWrapper(
                F('extendedprice') * (1 - F('discount')) - supplycost * F('quantity'),
                output_field=DecimalField(max_digits=25, decimal_places=4),
            ),
        )
        .values('nation', 'o_year')
        .annotate(sum_profit=Sum('amount'))
        .order_by('nation', '-o_year')
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q9 via direct SQL."""
    P = _paramset(9, params)

    sql = f"""
    SELECT nation, o_year, SUM(amount) as sum_profit
    FROM (
        SELECT n_name as nation,
               EXTRACT(year FROM o_orderdate) as o_year,
               l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity as amount
        FROM part, supplier, lineitem, partsupp, orders, nation
        WHERE s_suppkey = l_suppkey
          AND ps_suppkey = l_suppkey
          AND ps_partkey = l_partkey
          AND p_partkey = l_partkey
          AND o_orderkey = l_orderkey
          AND s_nationkey = n_nationkey
          AND p_name LIKE '%{P['color']}%'
    ) AS profit
    GROUP BY nation, o_year
    ORDER BY nation, o_year DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 9,
        'name': 'Product Type Profit Measure',
        'complexity': 'Very Complex',
        'description': 'Profit by nation and year for parts matching a name pattern',
        'tables': ['part', 'supplier', 'lineitem', 'partsupp', 'orders', 'nation'],
        'joins': 5,
        'aggregations': 1,
        'subqueries': 1,
    }
