"""
TPC-H Query 17: Small-Quantity-Order Revenue
Complex - average yearly revenue for parts with small quantity orders
"""

from decimal import Decimal
from django.db.models import Sum, Avg, F, Subquery, OuterRef, DecimalField, ExpressionWrapper, FloatField
from ..models import LineItem, Part
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q17 via Django ORM."""
    P = _paramset(17, params)
    
    # Subquery to calculate 20% of average quantity per part
    avg_qty_subquery = (
        LineItem.objects
        .filter(partkey=OuterRef('partkey'))
        .values('partkey')
        .annotate(avg_q=Avg('quantity'))
        .values('avg_q')
    )
    
    results = (
        LineItem.objects
        .using(using)
        .select_related('partkey')
        .filter(
            partkey__brand=P['brand'],
            partkey__container=P['container']
        )
        .annotate(
            avg_quantity=Subquery(avg_qty_subquery)
        )
        .filter(quantity__lt=ExpressionWrapper(
            F('avg_quantity') * Decimal('0.2'),
            output_field=DecimalField()
        ))
        .aggregate(
            avg_yearly=ExpressionWrapper(
                Sum('extendedprice', output_field=DecimalField()) / Decimal('7.0'),
                output_field=DecimalField()
            )
        )
    )
    
    return [results]


def run_query_sql(connection, params=None):
    """Execute Q17 via direct SQL."""
    P = _paramset(17, params)
    
    sql = f"""
    SELECT SUM(l_extendedprice) / 7.0 as avg_yearly
    FROM lineitem, part
    WHERE p_partkey = l_partkey
      AND p_brand = '{P['brand']}'
      AND p_container = '{P['container']}'
      AND l_quantity < (
        SELECT 0.2 * AVG(l_quantity)
        FROM lineitem
        WHERE l_partkey = p_partkey
      )
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 17,
        'name': 'Small-Quantity-Order Revenue',
        'complexity': 'Complex',
        'description': 'Average yearly revenue for parts with small quantity orders',
        'tables': ['lineitem', 'part'],
        'joins': 1,
        'aggregations': 2,
        'subqueries': 1
    }
