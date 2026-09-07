"""
TPC-H Query 12 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""


from django.db.models import Sum, F, Q, Case, When, IntegerField
from ..models import Orders, LineItem
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q12 via Django ORM."""
    P = _paramset(12, params)
    
    results = (
        LineItem.objects
        .using(using)
        .select_related('orderkey')
        .filter(
            shipmode__in=[P['shipmode1'], P['shipmode2']],
            commitdate__lt=F('receiptdate'),
            shipdate__lt=F('commitdate'),
            receiptdate__gte=P['date'],
            receiptdate__lt=P['date_end']
        )
        .values('shipmode')
        .annotate(
            high_line_count=Sum(
                Case(
                    When(
                        Q(orderkey__orderpriority='1-URGENT') | Q(orderkey__orderpriority='2-HIGH'),
                        then=1
                    ),
                    default=0,
                    output_field=IntegerField()
                )
            ),
            low_line_count=Sum(
                Case(
                    When(
                        ~Q(orderkey__orderpriority='1-URGENT') & ~Q(orderkey__orderpriority='2-HIGH'),
                        then=1
                    ),
                    default=0,
                    output_field=IntegerField()
                )
            )
        )
        .order_by('shipmode')
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q12 via direct SQL."""
    P = _paramset(12, params)
    
    sql = f"""
    SELECT l_shipmode,
      SUM(CASE WHEN o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH'
               THEN 1 ELSE 0 END) as high_line_count,
      SUM(CASE WHEN o_orderpriority <> '1-URGENT' AND o_orderpriority <> '2-HIGH'
               THEN 1 ELSE 0 END) as low_line_count
    FROM orders, lineitem
    WHERE o_orderkey = l_orderkey
      AND l_shipmode IN ('{P['shipmode1']}', '{P['shipmode2']}')
      AND l_commitdate < l_receiptdate
      AND l_shipdate < l_commitdate
      AND l_receiptdate >= CAST('{P['date']}' AS DATE)
      AND l_receiptdate < CAST('{P['date_end']}' AS DATE)
    GROUP BY l_shipmode
    ORDER BY l_shipmode
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 12,
        'name': 'Shipping Modes and Order Priority',
        'complexity': 'Medium',
        'description': 'Count high and low priority orders by ship mode',
        'tables': ['orders', 'lineitem'],
        'joins': 1,
        'aggregations': 2,
        'subqueries': 0
    }
