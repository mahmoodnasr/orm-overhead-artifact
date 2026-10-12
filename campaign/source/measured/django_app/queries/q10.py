"""
TPC-H Query 10: Returned Item Reporting
Complex - top 20 customers with returned items
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
    
    # Get database vendor
    vendor = connection.vendor
    
    # Database-specific LIMIT clause
    if vendor == 'mysql':
        limit_clause = "LIMIT 20"
    elif vendor == 'microsoft':
        limit_clause = "OFFSET 0 ROWS FETCH NEXT 20 ROWS ONLY"
    else:  # PostgreSQL, Oracle
        limit_clause = "FETCH FIRST 20 ROWS ONLY"
    
    # Database-specific date literals
    if vendor == 'mysql':
        date_start = f"'{P['date']}'"
        date_end = f"'{P['date_end']}'"
    elif vendor == 'microsoft':
        date_start = f"'{P['date']}'"
        date_end = f"'{P['date_end']}'"
    elif vendor == 'postgresql':
        date_start = f"DATE '{P['date']}'"
        date_end = f"DATE '{P['date_end']}'"
    else:  # Oracle
        date_start = f"TO_DATE('{P['date']}', 'YYYY-MM-DD')"
        date_end = f"TO_DATE('{P['date_end']}', 'YYYY-MM-DD')"
    
    sql = f"""
    SELECT c_custkey, c_name, SUM(l_extendedprice * (1 - l_discount)) as revenue,
           c_acctbal, n_name, c_address, c_phone, c_comment
    FROM customer, orders, lineitem, nation
    WHERE c_custkey = o_custkey
      AND l_orderkey = o_orderkey
      AND o_orderdate >= {date_start}
      AND o_orderdate < {date_end}
      AND l_returnflag = 'R'
      AND c_nationkey = n_nationkey
    GROUP BY c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment
    ORDER BY revenue DESC
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
        'number': 10,
        'name': 'Returned Item Reporting',
        'complexity': 'Complex',
        'description': 'Top 20 customers with returned items',
        'tables': ['customer', 'orders', 'lineitem', 'nation'],
        'joins': 3,
        'aggregations': 1,
        'subqueries': 0
    }
