"""
TPC-H Query 16: Parts/Supplier Relationship
Medium - count distinct suppliers per part brand/type/size
"""

from django.db.models import Count, Q, F
from ..models import PartSupp, Part, Supplier
from ._lookups import Like  # noqa: F401  registers field__like
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q16 via Django ORM."""
    P = _paramset(16, params)
    
    # TPC-H excludes suppliers whose comment matches '%Customer%Complaints%':
    # one pattern, case-sensitive, the two words in that order.
    #
    # Was: `.filter(comment__icontains='Customer').filter(comment__icontains=
    # 'Complaints')`, which is three departures from that in the same direction
    # - two patterns instead of one, case-insensitive where the specification is
    # case-sensitive, and either order instead of a fixed one - so the subquery
    # could select more suppliers and the outer NOT IN exclude more rows.
    #
    # All eight measured Django cells nonetheless returned 27,840 rows, the same
    # as their baselines, and every surviving validation check passed: the two
    # predicates coincide on this data because dbgen inserts the phrase verbatim.
    # They are not equivalent queries, and no check in validate_queries.py could
    # have caught it - the counts match, the values match, nothing is slow and
    # nothing errors. Defect C24.
    #
    # `__like` is a registered lookup rather than a built-in: `__contains`
    # escapes interior wildcards and `__regex` is not portable to SQL Server.
    # See django_app/queries/_lookups.py.
    bad_suppliers = Supplier.objects.using(using).filter(
        comment__like='%Customer%Complaints%'
    ).values_list('suppkey', flat=True)
    
    results = (
        PartSupp.objects
        .using(using)
        .select_related('partkey')
        .filter(
            ~Q(partkey__brand=P['brand']) &
            ~Q(partkey__type__startswith=P['type']) &
            Q(partkey__size__in=P['sizes']) &
            ~Q(suppkey__in=bad_suppliers)
        )
        .annotate(
            p_brand=F('partkey__brand'),
            p_type=F('partkey__type'),
            p_size=F('partkey__size')
        )
        .values('p_brand', 'p_type', 'p_size')
        .annotate(supplier_cnt=Count('suppkey', distinct=True))
        .order_by('-supplier_cnt', 'p_brand', 'p_type', 'p_size')
    )
    
    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q16 via direct SQL."""
    P = _paramset(16, params)
    
    sql = f"""
    SELECT p_brand, p_type, p_size, COUNT(DISTINCT ps_suppkey) as supplier_cnt
    FROM partsupp, part
    WHERE p_partkey = ps_partkey
      AND p_brand <> '{P['brand']}'
      AND p_type NOT LIKE '{P['type']}%'
      AND p_size IN ({P['sizes_sql']})
      AND ps_suppkey NOT IN (
        SELECT s_suppkey FROM supplier
        WHERE s_comment LIKE '%Customer%Complaints%'
      )
    GROUP BY p_brand, p_type, p_size
    ORDER BY supplier_cnt DESC, p_brand, p_type, p_size
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 16,
        'name': 'Parts/Supplier Relationship',
        'complexity': 'Medium',
        'description': 'Count distinct suppliers per part brand/type/size',
        'tables': ['partsupp', 'part', 'supplier'],
        'joins': 2,
        'aggregations': 1,
        'subqueries': 1
    }
