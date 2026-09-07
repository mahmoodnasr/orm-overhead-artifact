"""
TPC-H Query 2: Minimum Cost Supplier
Complex query - finds suppliers with minimum cost for given part type and region
"""

from django.db.models import Min, Q, F
from django.db.models import Subquery, OuterRef
from ..models import Part, Supplier, PartSupp, Nation, Region
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q2 via Django ORM."""
    P = _paramset(2, params)
    
    # Subquery to find minimum supplycost for each part in EUROPE
    min_cost_subquery = (
        PartSupp.objects
        .using(using)
        .filter(
            partkey=OuterRef('partkey'),
            suppkey__nationkey__regionkey__name=P['region']
        )
        .values('partkey')
        .annotate(min_cost=Min('supplycost'))
        .values('min_cost')[:1]
    )
    # The [:1] is required from Django 6.0 on, which rejects an unbounded
    # QuerySet in an `exact` lookup:
    #
    #   ValueError: The QuerySet value for an exact lookup must be limited to
    #   one result using slicing.
    #
    # Django 4.2 accepted it and returned 100 rows on the same data; 6.0
    # raises before any SQL is sent. The slice is safe here rather than merely
    # permitted: the subquery is correlated on partkey and grouped by partkey,
    # so for one outer row it already yields exactly one value - the minimum
    # supply cost for that part among EUROPE suppliers. LIMIT 1 is applied to
    # a result that was already one row, so the emitted SQL changes and the
    # answer does not. Re-validated after the change: MATCH and ORM=SQL pass.

    results = (
        PartSupp.objects
        .using(using)
        .select_related('suppkey__nationkey__regionkey', 'partkey')
        .filter(
            partkey__size=P['size'],
            partkey__type__endswith=P['type_suffix'],
            suppkey__nationkey__regionkey__name=P['region'],
            supplycost=Subquery(min_cost_subquery)
        )
        .annotate(
            s_acctbal=F('suppkey__acctbal'),
            s_name=F('suppkey__name'),
            n_name=F('suppkey__nationkey__name'),
            p_partkey=F('partkey__partkey'),
            p_mfgr=F('partkey__mfgr'),
            s_address=F('suppkey__address'),
            s_phone=F('suppkey__phone'),
            s_comment=F('suppkey__comment')
        )
        .values('s_acctbal', 's_name', 'n_name', 'p_partkey', 'p_mfgr', 's_address', 's_phone', 's_comment')
        .order_by('-s_acctbal', 'n_name', 's_name', 'p_partkey')[:100]
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q02 via direct SQL."""
    P = _paramset(2, params)
    
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
    SELECT s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment
    FROM part, supplier, partsupp, nation, region
    WHERE p_partkey = ps_partkey
      AND s_suppkey = ps_suppkey
      AND p_size = {P['size']}
      AND p_type LIKE '%{P['type_suffix']}'
      AND s_nationkey = n_nationkey
      AND n_regionkey = r_regionkey
      AND r_name = '{P['region']}'
      AND ps_supplycost = (
        SELECT MIN(ps_supplycost)
        FROM partsupp, supplier, nation, region
        WHERE p_partkey = ps_partkey
          AND s_suppkey = ps_suppkey
          AND s_nationkey = n_nationkey
          AND n_regionkey = r_regionkey
          AND r_name = '{P['region']}'
      )
    ORDER BY s_acctbal DESC, n_name, s_name, p_partkey
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
        'number': 2,
        'name': 'Minimum Cost Supplier',
        'complexity': 'Complex',
        'description': 'Find suppliers with minimum cost for given part type and region',
        'tables': ['part', 'supplier', 'partsupp', 'nation', 'region'],
        'joins': 4,
        'aggregations': 1,
        'subqueries': 1
    }
