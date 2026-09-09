"""
TPC-H Query 13: Customer Distribution
Complex - distribution of customers by number of qualifying orders.

Fixed: the previous ORM implementation chained .annotate(custdist=Count('*'))
onto a queryset that had already annotated an aggregate, so Django collapsed the
grouping and returned a single meaningless row (c_count 1162311, custdist
1550004) instead of the 42-row distribution. Its predicate was also wrong:
~Q(comment__icontains='special') & ~Q(comment__icontains='requests') excludes
comments containing either word, whereas TPC-H excludes comments matching
'%special%requests%' -- the two words in that order.

The per-customer count is now a correlated Subquery, which keeps it a scalar
expression and lets the outer query GROUP BY it. Validated against
run_query_sql on TPC-H SF1: 42 rows, identical distribution.

The predicate is a LIKE, not a regular expression
-------------------------------------------------
This file used to write the TPC-H predicate `o_comment NOT LIKE
'%special%requests%'` as `.exclude(comment__regex=r'special.*requests')`, and
`q13_sqlserver.py` already recorded why that is wrong: LIKE "is also what
TPC-H actually specifies", which made SQL Server's Q13 "both the faster and
the more faithful of the two". The note there asked that Q13's ORM time not be
put beside other systems' without saying that PostgreSQL, MySQL and Oracle
were evaluating a regular expression while SQL Server evaluated a LIKE.

That difference is now gone: every vendor uses the registered `like` lookup
from `_lookups.py`, the same construct `q13_sqlserver.py` and Q16 use, and the
ORM path evaluates the same operator as its own baseline. The caveat in
`q13_sqlserver.py` about comparing Q13 ORM times across systems no longer
applies to the operator, though it still applies to everything else that
differs between those servers.

Why the shape still does not match the baseline, and cannot
----------------------------------------------------------
The baseline is a LEFT JOIN with the predicate in the ON clause, grouped by
customer and then grouped again by the count. Django cannot express that. The
obvious rewrite, `FilteredRelation` for the ON-clause condition followed by
`.values().annotate().values().annotate()`, was tried and measured: it emits a
statement with **no GROUP BY at all** and returns a single meaningless row —
c_count 1484298, custdist 1534302 against the baseline's 42-row distribution.
That is the same collapse this file's first implementation suffered, and the
reason the correlated Subquery exists: it keeps the per-customer count a
scalar expression so the outer GROUP BY has something to group by.

So the join shape is not a defect in this file and not a lazy implementation.
Django has no way to GROUP BY over a grouped derived table, and the correlated
Subquery is the only formulation available. That is a finding about the ORM,
and Q13 is where the study can say so with evidence.

Why this implementation is slow, and why it is nonetheless the right one
-----------------------------------------------------------------------
On PostgreSQL SF10 *non-indexed* this path exceeds the 900 s ceiling while its
own hand-written baseline returns in 10.8 s and SQLAlchemy's ORM in 10.6 s. That
is not a defect in this file, and the difference was checked rather than assumed.

The correlated Subquery compiles to a plan whose inner scan runs once per
customer, and in the non-indexed configuration there is no index on o_custkey,
so each of those executions is a full scan of 15 million orders:

    Index Only Scan using customer_pkey on customer   rows=1,499,989
      SubPlan 1
        -> Seq Scan on orders u0                      cost=500,697.88

    total estimated cost  88,358,207,471

The hand-written baseline is a single pass:

    Hash Right Join  (orders.o_custkey = customer.c_custkey)
    total estimated cost   1,253,944

a ratio of about 70,464x. The query is not marginally over the ceiling; it is
nowhere near it.

Django cannot express the hash-join form. Q13 groups over a per-customer
aggregate, which in SQL is a derived table, and Django's ORM has no
derived-table construct - `Subquery` in an annotation is the only way to carry a
per-row aggregate into an outer grouping. The obvious alternative,

    Customer.objects
      .annotate(c_count=Count('orders', filter=~Q(orders__comment__regex=...)))
      .values('c_count').annotate(custdist=Count('*'))

compiles, and is wrong. Django emits it with **no GROUP BY at all**:

    SELECT COUNT(orders.o_orderkey) FILTER (...) AS c_count, COUNT(*) AS custdist
    FROM customer LEFT OUTER JOIN orders ON (...)
    ORDER BY 2 DESC, 1 DESC

which returns one global row rather than the distribution - precisely the defect
described above, the one that produced "c_count 1162311, custdist 1550004" in
the original study. Fast, and an answer to a different question.

So Django offers two options for Q13: a correct one that cannot finish, and a
fast one that is wrong. This file takes the correct one and lets it record a
timeout. The same limitation appears on SQL Server as an outright failure rather
than a slow query - see `q13_sqlserver.py` and defect C17 - because SQL Server
additionally forbids a subquery in a GROUP BY expression. SQLAlchemy has
`.subquery()` and expresses the derived table directly, which is why its ORM
path completes on both systems. That difference in expressive power is a result
of this study, not an artefact of it.
"""

from django.db.models import Count, OuterRef, Subquery, IntegerField
from django.db.models.functions import Coalesce
from ..models import Customer, Orders

# Registers field__like. The predicate below is a LIKE, not a regular
# expression, so that every vendor evaluates the operator TPC-H specifies.
from ._lookups import Like  # noqa: F401
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute Q13 via Django ORM."""
    P = _paramset(13, params)

    order_count = Subquery(
        Orders.objects.using(using)
        .filter(custkey=OuterRef("custkey"))
        .exclude(comment__like=P["like_pattern"])
        .values("custkey")
        .annotate(n=Count("orderkey"))
        .values("n")[:1],
        output_field=IntegerField(),
    )

    results = (
        Customer.objects.using(using)
        .annotate(c_count=Coalesce(order_count, 0))
        .values("c_count")
        .annotate(custdist=Count("*"))
        .order_by("-custdist", "-c_count")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute Q13 via direct SQL."""
    P = _paramset(13, params)

    sql = f"""
    SELECT c_count, COUNT(*) as custdist
    FROM (
        SELECT c_custkey, COUNT(o_orderkey) as c_count
        FROM customer LEFT OUTER JOIN orders
          ON c_custkey = o_custkey
         AND o_comment NOT LIKE '{P["like_pattern"]}'
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
