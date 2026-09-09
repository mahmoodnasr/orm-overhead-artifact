"""
TPC-H Query 13: Customer Distribution Query - Oracle Version
"""

from django.db.models import Count, Q
from tpch_paramsets import resolve as _paramset


# Q13's ORM path is not expressible on Oracle. See run_query_orm below.
#
# This module previously carried its own copy of the ORM, and that copy was the
# *original* Q13 implementation - both defects the shared q13.py records as
# fixed, still present, because the per-vendor override was never updated when
# the shared module was corrected. It chained
# .annotate(custdist=Count('custkey')) onto an already-annotated queryset, so
# Django collapsed the grouping and returned a single row. Measured on Oracle at
# SF10:
#
#     dj_orm   1 row    c_count 11,622,531   custdist 15,500,018
#     dj_sql   45 rows  totalling 1,500,000 customers
#     sa_orm   45 rows  totalling 1,500,000 customers
#     sa_sql   45 rows  totalling 1,500,000 customers
#
# 11,622,531 and 15,500,018 are exactly ten times the SF1 figures quoted in
# q13.py's docstring, which makes the provenance unambiguous. Its predicate was
# wrong too: ~Q(comment__icontains='special') & ~Q(comment__icontains='requests')
# excludes comments containing *either* word, where TPC-H excludes
# '%special%requests%', the two in that order. It was fast, and it was an answer
# to a different question.
#
# Replacing it with the shared implementation does not work either, which is the
# substantive finding here - see below.


class Q13NotExpressible(NotImplementedError):
    """Raised instead of measuring something that is not Q13."""


def run_query_orm(using="default", params=None):
    """Not expressible through the Django ORM on Oracle. Raises.

    Q13 groups over a per-customer aggregate, which in SQL is a derived table.
    Django has no derived-table construct; its only route is `Subquery` in an
    annotation, which is what the shared `q13.py` uses. Oracle rejects that
    outright:

        ORA-22818: subquery expressions not allowed here

    This is the same limitation recorded as C17 for SQL Server, where
    mssql-django states it as `supports_subqueries_in_group_by = False` and
    drops the clause instead of raising. Two of the four systems in this study
    forbid a subquery in a GROUP BY expression, so C17 is a general limitation
    of expressing Q13 through the Django ORM rather than a SQL Server quirk.

    Django therefore offers Oracle the same two options it offers SQL Server: a
    correct query that will not run, or a fast one that answers a different
    question. The implementation this file used to carry took the second. This
    one takes neither and records the reason.

    The other three paths run and agree: 45 rows, 1,500,000 customers.
    SQLAlchemy's ORM manages it because `.subquery()` builds the derived table
    directly, which is a difference in expressive power between the two ORMs and
    a result of this study rather than an artefact of it.
    """
    P = _paramset(13, params)
    raise Q13NotExpressible(
        "Django ORM cannot express Q13 on Oracle: no derived-table construct, "
        "and Oracle raises ORA-22818 for a subquery in a GROUP BY expression. "
        "See django_app/queries/q13_oracle.py and defect C17."
    )


def run_query_sql(connection, params=None):
    """Execute TPC-H Q13 via direct SQL - Oracle compatible"""
    P = _paramset(13, params)
    sql = f"""
    SELECT
        c_count,
        COUNT(*) as custdist
    FROM (
        SELECT
            c_custkey,
            COUNT(o_orderkey) as c_count
        FROM customer
        LEFT OUTER JOIN orders ON c_custkey = o_custkey
            AND o_comment NOT LIKE '{P["like_pattern"]}'
        GROUP BY c_custkey
    ) c_orders
    GROUP BY c_count
    ORDER BY custdist DESC, c_count DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results
