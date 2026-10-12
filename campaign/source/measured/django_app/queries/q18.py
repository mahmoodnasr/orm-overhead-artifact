"""
TPC-H Query 18: Large Volume Customer
Complex - customers with orders exceeding quantity threshold
"""

from django.db.models import Sum, F, Subquery, OuterRef
from ..models import Customer, Orders, LineItem
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q18 via Django ORM."""
    P = _paramset(18, params)
    
    # Subquery to find orders with total quantity > 300
    large_orders = (
        LineItem.objects
        .values('orderkey')
        .annotate(total_qty=Sum('quantity'))
        .filter(total_qty__gt=P['quantity'])
        .values_list('orderkey', flat=True)
    )
    
    results = (
        LineItem.objects
        .using(using)
        .select_related('orderkey__custkey')
        .filter(orderkey__in=large_orders)
        .annotate(
            c_name=F('orderkey__custkey__name'),
            c_custkey=F('orderkey__custkey__custkey'),
            o_orderkey=F('orderkey__orderkey'),
            o_orderdate=F('orderkey__orderdate'),
            o_totalprice=F('orderkey__totalprice')
        )
        .values('c_name', 'c_custkey', 'o_orderkey', 'o_orderdate', 'o_totalprice')
        .annotate(total_qty=Sum('quantity'))
        .order_by('-o_totalprice', 'o_orderdate')[:100]
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q18 via direct SQL."""
    P = _paramset(18, params)
    
    # Get database vendor
    vendor = connection.vendor
    
    # Database-specific LIMIT clause
    if vendor == 'mysql':
        limit_clause = "LIMIT 100"
    elif vendor == 'microsoft':
        limit_clause = "OFFSET 0 ROWS FETCH NEXT 100 ROWS ONLY"
    else:  # PostgreSQL, Oracle
        limit_clause = "FETCH FIRST 100 ROWS ONLY"
    
    sql = f"""
    SELECT c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice,
           SUM(l_quantity) as total_qty
    FROM customer, orders, lineitem
    WHERE o_orderkey IN (
        SELECT l_orderkey
        FROM lineitem
        GROUP BY l_orderkey
        HAVING SUM(l_quantity) > {P['quantity']}
      )
      AND c_custkey = o_custkey
      AND o_orderkey = l_orderkey
    GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
    ORDER BY o_totalprice DESC, o_orderdate
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
        'number': 18,
        'name': 'Large Volume Customer',
        'complexity': 'Complex',
        'description': 'Customers with orders exceeding quantity threshold',
        'tables': ['customer', 'orders', 'lineitem'],
        'joins': 2,
        'aggregations': 2,
        'subqueries': 1
    }
