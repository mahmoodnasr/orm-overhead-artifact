"""TPC-H Query 13 — SQL Server version.

Two things in the shared `q13.py` cannot run on SQL Server, and each fails in a
different direction: one raises, the other quietly answers a different question.

*The ORM path raised.* `q13.py` writes the TPC-H predicate
`o_comment NOT LIKE '{P['like_pattern']}'` as `.exclude(comment__regex=...)`.
Django maps `__regex` to whatever the backend declares, and mssql-django
declares `dbo.REGEXP_LIKE` — a user-defined function it expects the database to
supply and this database does not have, so the query dies with
"Cannot find either column 'dbo' or the user-defined function or aggregate
'dbo.REGEXP_LIKE'".

Creating that UDF is the wrong fix here even though it is the documented one.
A T-SQL scalar function is evaluated row by row and inhibits parallelism, so
Django's Q13 would carry the cost of a UDF over 15 million orders and the
resulting "ORM overhead" would be a measurement of scalar UDF dispatch. The
predicate is expressed as a LIKE instead, through a registered lookup: the ORM
still builds the entire statement and the pattern travels as a bound parameter.

This note used to warn that Q13's ORM path evaluated a regular expression on
PostgreSQL, MySQL and Oracle while evaluating a LIKE here, making SQL Server's
Q13 both the faster and the more faithful arm, and that its ORM time therefore
should not be placed beside the other systems' without saying so.

**That is no longer true.** `q13.py` now uses the same registered `like` lookup
this file does, so all four vendors evaluate the operator TPC-H specifies. The
two predicates were shown equivalent on the loaded data before the change:
`NOT LIKE '%special%requests%'` and `NOT (o_comment ~ 'special.*requests')`
each select 1,484,298 of 1,500,000 orders at SF1, with zero rows on which they
disagree. The caveat is retired for the operator; everything else that differs
between these servers still stands.

*The SQL path silently returned the wrong distribution.* See the comment on the
statement below and defect C14.
"""

from django.db.models import Count, OuterRef, Subquery, IntegerField
from django.db.models.functions import Coalesce

from ..models import Customer, Orders


# The `Like` lookup this query needs now lives in `_lookups.py`, because Q16
# needs the identical construct on every vendor (C24) and two copies of one
# lookup is the shape of C9 - they drift the moment either is corrected.
from ._lookups import Like  # noqa: F401  registers field__like
from tpch_paramsets import resolve as _paramset


class Q13NotExpressible(NotImplementedError):
    """Raised instead of measuring something that is not Q13."""


def run_query_orm(using="default", params=None):
    """Not expressible through the Django ORM on SQL Server. Raises.

    Q13 aggregates twice: count the qualifying orders per customer, then count
    the customers per distinct count. The second grouping is over the result of
    the first, which in SQL is a derived table.

    Django's ORM has no derived-table construct. Its only way to carry a
    per-row aggregate into an outer grouping is `Subquery` in an annotation,
    which is what the shared `q13.py` uses and what works on PostgreSQL, MySQL
    and Oracle. SQL Server does not allow a subquery in a GROUP BY expression -
    mssql-django states the restriction directly, `supports_subqueries_in_group_by
    = False` in mssql/features.py, and its compiler drops such expressions from
    the GROUP BY clause in `collapse_group_by`.

    The consequence is worth being precise about, because it is *not* an error.
    The compiler silently emitted

        SELECT COALESCE((correlated subquery), 0) AS c_count, COUNT_BIG(*) AS custdist
        FROM customer ORDER BY 2 DESC, 1 DESC

    with no GROUP BY at all. Here that happens to raise (error 8120, a column
    not in an aggregate or the GROUP BY clause), but nothing guarantees it will:
    a query that loses its grouping and still parses would have been timed and
    recorded as Q13.

    Two ways to produce a number were rejected:

    *Emit the SQL by hand.* That is defect C1 - `run_query_orm` running
    hand-written SQL and the difference reported as ORM overhead - and it is the
    defect that invalidated the whole earlier study.

    *Do the outer grouping in Python.* That moves work out of the database into
    the framework, and would report a Django Q13 time that is mostly a Python
    loop over 1.5 million rows. It would not be wrong so much as meaningless.

    So this cell is not measured, and the run records why. The other three paths
    for Q13 on SQL Server - Django's hand-written SQL, and both SQLAlchemy paths
    - all run and agree. SQLAlchemy's ORM manages it because it can build a real
    FROM-subquery (`.subquery()`), which is a genuine difference in expressive
    power between the two ORMs and belongs in the write-up rather than in a
    footnote.
    """
    P = _paramset(13, params)
    raise Q13NotExpressible(
        "Django ORM cannot express Q13 on SQL Server: no derived-table "
        "construct, and SQL Server forbids GROUP BY on a subquery. See "
        "django_app/queries/q13_sqlserver.py and defect C17."
    )


def run_query_sql(connection, params=None):
    """Execute Q13 via direct SQL."""
    P = _paramset(13, params)

    # The predicate is o_comment NOT LIKE '{P['like_pattern']}'. It is written as
    # concatenation because mssql-django rewrites the statement before sending
    # it: CursorWrapper.execute applies format_group_by_params to any SQL
    # containing the string "GROUP BY", and that method runs
    # re.sub(r'%\w+', '{}', query) over the whole text. Q13 groups, so the
    # pattern arrived at the server as '{}{}%' — confirmed by reading the text
    # back out of Query Store — and the join condition excluded almost nothing.
    # The query still succeeded and still returned a plausible 46-row
    # distribution; it was simply a different query. Every '%' here is followed
    # by a quote, which that regex cannot match, and SQL Server folds the
    # constants at compile time so the plan is unchanged. Defect C14.
    sql = f"""
    SELECT c_count, COUNT(*) as custdist
    FROM (
        SELECT c_custkey, COUNT(o_orderkey) as c_count
        FROM customer LEFT OUTER JOIN orders
          ON c_custkey = o_custkey
         AND o_comment NOT LIKE '%' + '{P["word1"]}' + '%' + '{P["word2"]}' + '%'
        GROUP BY c_custkey
    ) AS c_orders
    GROUP BY c_count
    ORDER BY custdist DESC, c_count DESC
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 13,
        "name": "Customer Distribution",
        "complexity": "Complex",
        "description": "Distribution of customers by number of qualifying orders",
        "tables": ["customer", "orders"],
        "joins": 1,
        "aggregations": 2,
        "subqueries": 1,
    }
