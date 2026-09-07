"""
TPC-H Query 22: Global Sales Opportunity Query - Oracle Version
"""
from django.db.models import Count, Sum, Avg, Q, F
from django.db.models.functions import Substr
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute TPC-H Q22 via Django ORM"""
    P = _paramset(22, params)
    from django_app.models import Customer
    
    country_codes = list(P['country_codes'])
    
    # The average is taken over the SAME seven country codes the outer query
    # filters on, so it has to be built from the parameter set rather than
    # written out. It used to name 13, 31, 23, 29, 30, 18 and 17 as literals -
    # which are exactly set 0's codes, so set 0 agreed with the SQL baseline and
    # every other set computed its threshold over the wrong population and
    # returned different rows. Validating set 0 alone cannot see this: the
    # hardcoded value *is* set 0. Seven of the eight sets disagreed with both
    # the SQL baseline and the SQLAlchemy ORM (C40).
    code_filter = Q()
    for code in country_codes:
        code_filter |= Q(phone__startswith=code)
    avg_acctbal = Customer.objects.using(using).filter(
        acctbal__gt=0
    ).filter(code_filter).aggregate(avg=Avg('acctbal'))['avg']
    
    results = (
        Customer.objects
        .using(using)
        .annotate(cntrycode=Substr('phone', 1, 2))
        .filter(
            cntrycode__in=country_codes,
            acctbal__gt=avg_acctbal if avg_acctbal else 0,
            orders__isnull=True
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
    """Execute TPC-H Q22 via direct SQL - Oracle compatible"""
    P = _paramset(22, params)
    sql = f"""
    SELECT
        cntrycode,
        COUNT(*) as numcust,
        SUM(c_acctbal) as totacctbal
    FROM (
        SELECT
            SUBSTR(c_phone, 1, 2) as cntrycode,
            c_acctbal
        FROM customer
        WHERE SUBSTR(c_phone, 1, 2) IN ({P['codes_sql_spaced']})
        AND c_acctbal > (
            SELECT AVG(c_acctbal)
            FROM customer
            WHERE c_acctbal > 0.00
            AND SUBSTR(c_phone, 1, 2) IN ({P['codes_sql_spaced']})
        )
        AND NOT EXISTS (
            SELECT *
            FROM orders
            WHERE o_custkey = c_custkey
        )
    ) custsale
    GROUP BY cntrycode
    ORDER BY cntrycode
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results

