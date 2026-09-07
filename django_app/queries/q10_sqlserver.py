"""
TPC-H Query 10 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""


from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from ..models import Customer, Orders, LineItem, Nation
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q10 via Django ORM."""
    P = _paramset(10, params)
    
    results = (
        LineItem.objects
        .using(using)
        .select_related('orderkey__custkey__nationkey')
        .filter(
            orderkey__orderdate__gte=P['date'],
            orderkey__orderdate__lt=P['date_end'],
            returnflag='R'
        )
        .annotate(
            revenue=ExpressionWrapper(
                F('extendedprice') * (1 - F('discount')),
                output_field=DecimalField(max_digits=15, decimal_places=2)
            ),
            c_custkey=F('orderkey__custkey__custkey'),
            c_name=F('orderkey__custkey__name'),
            c_acctbal=F('orderkey__custkey__acctbal'),
            c_phone=F('orderkey__custkey__phone'),
            n_name=F('orderkey__custkey__nationkey__name'),
            c_address=F('orderkey__custkey__address'),
            c_comment=F('orderkey__custkey__comment')
        )
        .values('c_custkey', 'c_name', 'c_acctbal', 'c_phone', 'n_name', 'c_address', 'c_comment')
        .annotate(total_revenue=Sum('revenue'))
        .order_by('-total_revenue')[:20]
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q10 via direct SQL."""
    P = _paramset(10, params)
    
    sql = f"""
    SELECT TOP 20 c_custkey, c_name, SUM(l_extendedprice * (1 - l_discount)) as revenue,
           c_acctbal, n_name, c_address, c_phone, c_comment
    FROM customer, orders, lineitem, nation
    WHERE c_custkey = o_custkey
      AND l_orderkey = o_orderkey
      AND o_orderdate >= CAST('{P['date']}' AS DATE)
      AND o_orderdate < CAST('{P['date_end']}' AS DATE)
      AND l_returnflag = 'R'
      AND c_nationkey = n_nationkey
    GROUP BY c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment
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
        'number': 10,
        'name': 'Returned Item Reporting',
        'complexity': 'Complex',
        'description': 'Top 20 customers with returned items',
        'tables': ['customer', 'orders', 'lineitem', 'nation'],
        'joins': 3,
        'aggregations': 1,
        'subqueries': 0
    }
