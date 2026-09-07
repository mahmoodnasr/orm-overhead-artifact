"""
TPC-H Query 4: Order Priority Checking
Medium complexity - counts orders by priority where items were committed late
"""

from django.db.models import Count, Exists, OuterRef, Q, F
from ..models import Orders, LineItem
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q4 via Django ORM."""
    P = _paramset(4, params)
    
    # Subquery to check if order has late line items
    late_lineitem_subquery = LineItem.objects.filter(
        orderkey=OuterRef('orderkey'),
        commitdate__lt=F('receiptdate')
    )
    
    results = (
        Orders.objects
        .using(using)
        .filter(
            orderdate__gte=P['date'],
            orderdate__lt=P['date_end']
        )
        .annotate(has_late_items=Exists(late_lineitem_subquery))
        .filter(has_late_items=True)
        .values('orderpriority')
        .annotate(order_count=Count('orderkey'))
        .order_by('orderpriority')
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    P = _paramset(4, params)

    # Get database vendor
    vendor = connection.vendor
    
    # Database-specific date literals
    if vendor == 'mysql':
        date_start = f"'{P['date']}'"
    elif vendor == 'microsoft':
        date_start = f"'{P['date']}'"
    elif vendor == 'postgresql':
        date_start = f"DATE '{P['date']}'"
    else:  # Oracle
        date_start = f"TO_DATE('{P['date']}', 'YYYY-MM-DD')"
    
    if vendor == 'mysql':
        date_end = f"'{P['date_end']}'"
    elif vendor == 'microsoft':
        date_end = f"'{P['date_end']}'"
    elif vendor == 'postgresql':
        date_end = f"DATE '{P['date_end']}'"
    else:  # Oracle
        date_end = f"TO_DATE('{P['date_end']}', 'YYYY-MM-DD')"
    
    """Execute Q4 via direct SQL."""
    
    sql = f"""
    SELECT o_orderpriority, COUNT(*) as order_count
    FROM orders
    WHERE o_orderdate >= {date_start}
      AND o_orderdate < {date_end}
      AND EXISTS (
        SELECT * FROM lineitem
        WHERE l_orderkey = o_orderkey
          AND l_commitdate < l_receiptdate
      )
    GROUP BY o_orderpriority
    ORDER BY o_orderpriority
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 4,
        'name': 'Order Priority Checking',
        'complexity': 'Medium',
        'description': 'Count orders by priority where items were committed late',
        'tables': ['orders', 'lineitem'],
        'joins': 1,
        'aggregations': 1,
        'subqueries': 1
    }
