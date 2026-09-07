"""
TPC-H Query 6: Forecasting Revenue Change Query
Simple single-table query with filtering and aggregation
"""
from django.db.models import Sum, F, Q
from decimal import Decimal
from datetime import date
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """
    Execute TPC-H Q6 via Django ORM
    
    SELECT SUM(l_extendedprice * l_discount) as revenue
    FROM lineitem
    WHERE l_shipdate >= '{P['date']}'
        AND l_shipdate < '{P['date_end']}'
        AND l_discount BETWEEN {P['disc_lo']} AND {P['disc_hi']}
        AND l_quantity < {P['quantity']}
    """
    P = _paramset(6, params)
    from django_app.models import LineItem
    
    start_date = P['date']
    end_date = P['date_end']
    
    result = (
        LineItem.objects
        .using(using)
        .filter(
            shipdate__gte=start_date,
            shipdate__lt=end_date,
            discount__gte=P['disc_lo'],
            discount__lte=P['disc_hi'],
            quantity__lt=P['quantity']
        )
        .aggregate(
            revenue=Sum(F('extendedprice') * F('discount'))
        )
    )
    
    return [result]


def run_query_sql(connection, params=None):
    """Execute TPC-H Q6 via direct SQL"""
    P = _paramset(6, params)
    sql = f"""
    SELECT SUM(l_extendedprice * l_discount) as revenue
    FROM lineitem
    WHERE l_shipdate >= '{P['date']}'
        AND l_shipdate < '{P['date_end']}'
        AND l_discount BETWEEN {P['disc_lo']} AND {P['disc_hi']}
        AND l_quantity < {P['quantity']}
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query"""
    return {
        'number': 6,
        'name': 'Forecasting Revenue Change',
        'complexity': 'Simple',
        'description': 'Quantifies revenue increase from discount elimination',
        'tables': ['lineitem'],
        'joins': 0,
        'aggregations': 1,
        'subqueries': 0,
    }
