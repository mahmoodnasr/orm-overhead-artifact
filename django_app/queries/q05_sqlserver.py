"""
TPC-H Query 5 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""


from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from ..models import Customer, Orders, LineItem, Supplier, Nation, Region
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q5 via Django ORM."""
    P = _paramset(5, params)
    
    results = (
        LineItem.objects
        .using(using)
        .select_related('orderkey__custkey__nationkey__regionkey', 'suppkey__nationkey')
        .filter(
            orderkey__custkey__nationkey__regionkey__name=P['region'],
            orderkey__orderdate__gte=P['date'],
            orderkey__orderdate__lt=P['date_end'],
            # Local supplier: supplier nation = customer nation
            suppkey__nationkey=F('orderkey__custkey__nationkey')
        )
        .annotate(
            n_name=F('suppkey__nationkey__name'),
            revenue=ExpressionWrapper(
                F('extendedprice') * (1 - F('discount')),
                output_field=DecimalField(max_digits=15, decimal_places=2)
            )
        )
        .values('n_name')
        .annotate(total_revenue=Sum('revenue'))
        .order_by('-total_revenue')
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q5 via direct SQL."""
    P = _paramset(5, params)
    
    sql = f"""
    SELECT n_name, SUM(l_extendedprice * (1 - l_discount)) as revenue
    FROM customer, orders, lineitem, supplier, nation, region
    WHERE c_custkey = o_custkey
      AND l_orderkey = o_orderkey
      AND l_suppkey = s_suppkey
      AND c_nationkey = s_nationkey
      AND s_nationkey = n_nationkey
      AND n_regionkey = r_regionkey
      AND r_name = '{P['region']}'
      AND o_orderdate >= CAST('{P['date']}' AS DATE)
      AND o_orderdate < CAST('{P['date_end']}' AS DATE)
    GROUP BY n_name
    ORDER BY revenue DESC
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 5,
        'name': 'Local Supplier Volume',
        'complexity': 'Complex',
        'description': 'Revenue from local suppliers by nation',
        'tables': ['customer', 'orders', 'lineitem', 'supplier', 'nation', 'region'],
        'joins': 5,
        'aggregations': 1,
        'subqueries': 0
    }
