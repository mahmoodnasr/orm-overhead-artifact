"""
TPC-H Query 19: Discounted Revenue
Simple - revenue from specific part/shipment combinations
"""

from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
from ..models import LineItem, Part
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q19 via Django ORM."""
    P = _paramset(19, params)
    
    # Three different combinations with OR logic
    condition1 = Q(
        partkey__brand=P['brand1'],
        partkey__container__in=['SM CASE', 'SM BOX', 'SM PACK', 'SM PKG'],
        quantity__gte=P['quantity1'],
        quantity__lte=P['quantity1'] + 10,
        partkey__size__gte=1,
        partkey__size__lte=5,
        shipmode__in=['AIR', 'AIR REG'],
        shipinstruct='DELIVER IN PERSON'
    )
    
    condition2 = Q(
        partkey__brand=P['brand2'],
        partkey__container__in=['MED BAG', 'MED BOX', 'MED PKG', 'MED PACK'],
        quantity__gte=P['quantity2'],
        quantity__lte=P['quantity2'] + 10,
        partkey__size__gte=1,
        partkey__size__lte=10,
        shipmode__in=['AIR', 'AIR REG'],
        shipinstruct='DELIVER IN PERSON'
    )
    
    condition3 = Q(
        partkey__brand=P['brand3'],
        partkey__container__in=['LG CASE', 'LG BOX', 'LG PACK', 'LG PKG'],
        quantity__gte=P['quantity3'],
        quantity__lte=P['quantity3'] + 10,
        partkey__size__gte=1,
        partkey__size__lte=15,
        shipmode__in=['AIR', 'AIR REG'],
        shipinstruct='DELIVER IN PERSON'
    )
    
    results = (
        LineItem.objects
        .using(using)
        .select_related('partkey')
        .filter(condition1 | condition2 | condition3)
        .aggregate(
            revenue=Sum(
                ExpressionWrapper(
                    F('extendedprice') * (1 - F('discount')),
                    output_field=DecimalField(max_digits=15, decimal_places=2)
                )
            )
        )
    )
    
    return [results]


def run_query_sql(connection, params=None):
    """Execute Q19 via direct SQL."""
    P = _paramset(19, params)
    
    sql = f"""
    SELECT SUM(l_extendedprice * (1 - l_discount)) as revenue
    FROM lineitem, part
    WHERE (
      p_partkey = l_partkey
      AND p_brand = '{P['brand1']}'
      AND p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
      AND l_quantity >= {P['quantity1']} AND l_quantity <= {P['quantity1'] + 10}
      AND p_size BETWEEN 1 AND 5
      AND l_shipmode IN ('AIR', 'AIR REG')
      AND l_shipinstruct = 'DELIVER IN PERSON'
    ) OR (
      p_partkey = l_partkey
      AND p_brand = '{P['brand2']}'
      AND p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
      AND l_quantity >= {P['quantity2']} AND l_quantity <= {P['quantity2'] + 10}
      AND p_size BETWEEN 1 AND 10
      AND l_shipmode IN ('AIR', 'AIR REG')
      AND l_shipinstruct = 'DELIVER IN PERSON'
    ) OR (
      p_partkey = l_partkey
      AND p_brand = '{P['brand3']}'
      AND p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
      AND l_quantity >= {P['quantity3']} AND l_quantity <= {P['quantity3'] + 10}
      AND p_size BETWEEN 1 AND 15
      AND l_shipmode IN ('AIR', 'AIR REG')
      AND l_shipinstruct = 'DELIVER IN PERSON'
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
        'number': 19,
        'name': 'Discounted Revenue',
        'complexity': 'Simple',
        'description': 'Revenue from specific part/shipment combinations',
        'tables': ['lineitem', 'part'],
        'joins': 1,
        'aggregations': 1,
        'subqueries': 0
    }
