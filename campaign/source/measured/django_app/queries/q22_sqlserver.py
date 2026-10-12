"""
TPC-H Query 22 - SQL Server Version
This version uses SQL Server-specific syntax (SUBSTRING instead of SUBSTR FROM FOR)
"""
from django.db.models import Count, Sum, Avg, Q, Subquery, OuterRef, Exists
from django.db.models.functions import Substr
from django_app.models import Customer, Orders
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """
    Execute Q22 via Django ORM.
    Global Sales Opportunity Query - identifies customers who might be persuaded to do business.
    """
    P = _paramset(22, params)
    # Country codes of interest
    country_codes = list(P['country_codes'])
    
    # Build Q objects for phone startswith filter
    from django.db.models import Q
    phone_filters = Q()
    for code in country_codes:
        phone_filters |= Q(phone__startswith=code)
    
    # Get average account balance for customers with positive balance in specific countries
    avg_acctbal_subquery = Customer.objects.using(using).filter(
        phone_filters,
        acctbal__gt=0
    ).aggregate(avg_bal=Avg('acctbal'))['avg_bal'] or 0
    
    # Subquery to check if customer has any orders
    from django.db.models import Exists, OuterRef
    has_orders = Orders.objects.filter(custkey=OuterRef('custkey'))
    
    # Find customers with no orders
    results = (
        Customer.objects.using(using)
        .annotate(
            cntrycode=Substr('phone', 1, 2),
            has_order=Exists(has_orders)
        )
        .filter(
            cntrycode__in=country_codes,
            acctbal__gt=avg_acctbal_subquery,
            has_order=False
        )
        .values('cntrycode')
        .annotate(
            numcust=Count('custkey'),
            totacctbal=Sum('acctbal')
        )
        .order_by('cntrycode')
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q22 via direct SQL."""
    P = _paramset(22, params)
    
    # SQL Server uses SUBSTRING(x, y, z) instead of SUBSTR(x FROM y FOR z)
    sql = f"""
    SELECT cntrycode, COUNT(*) as numcust, SUM(c_acctbal) as totacctbal
    FROM (
      SELECT SUBSTRING(c_phone, 1, 2) as cntrycode, c_acctbal
      FROM customer
      WHERE SUBSTRING(c_phone, 1, 2) IN ({P['codes_sql_spaced']})
        AND c_acctbal > (
          SELECT AVG(c_acctbal)
          FROM customer
          WHERE c_acctbal > 0.00
            AND SUBSTRING(c_phone, 1, 2) IN ({P['codes_sql_spaced']})
        )
        AND NOT EXISTS (
          SELECT * FROM orders
          WHERE o_custkey = c_custkey
        )
    ) as custsale
    GROUP BY cntrycode
    ORDER BY cntrycode
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 22,
        'name': 'Global Sales Opportunity',
        'description': 'Identifies customers who might be persuaded to do business',
        'complexity': 'Medium',
        'tables': ['customer', 'orders']
    }

