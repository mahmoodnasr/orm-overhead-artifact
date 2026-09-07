"""
TPC-H Query 9: Product Type Profit Measure Query - Oracle Version
"""
from django.db.models import Sum, F
from django.db.models.functions import ExtractYear


# The ORM implementation is NOT duplicated here. It used to be, and it was the
# copy made before q09.py was corrected, so it kept two defects the shared file
# had already fixed and documented: it reached supplycost through
# `partkey__partsupp__supplycost`, joining PARTSUPP on partkey alone instead of
# on the (partkey, suppkey) pair TPC-H requires, and it filtered with
# `icontains` where the specification's LIKE '%green%' is case sensitive. The
# validator caught it on the campaign host as MATCH DIFF and ORM=SQL DIFF - the
# Django ORM returning different sums from all three other paths, and returning
# them in 4.4 s against 28 s, because the wrong join was the cheaper one.
#
# Only run_query_sql needs to be Oracle-specific: the shared baseline uses AS
# for a table alias and Oracle rejects it with ORA-03048. So this module
# overrides the SQL and re-exports the shared ORM (C9 - one definition).
from .q09 import run_query_orm  # noqa: F401
from tpch_paramsets import resolve as _paramset


def run_query_sql(connection, params=None):
    """Execute TPC-H Q9 via direct SQL - Oracle compatible"""
    P = _paramset(9, params)
    sql = f"""
    SELECT
        nation,
        o_year,
        SUM(amount) as sum_profit
    FROM (
        SELECT
            n_name as nation,
            EXTRACT(YEAR FROM o_orderdate) as o_year,
            l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity as amount
        FROM part, supplier, lineitem, partsupp, orders, nation
        WHERE s_suppkey = l_suppkey
        AND ps_suppkey = l_suppkey
        AND ps_partkey = l_partkey
        AND p_partkey = l_partkey
        AND o_orderkey = l_orderkey
        AND s_nationkey = n_nationkey
        AND p_name LIKE '%{P['color']}%'
    ) profit
    GROUP BY nation, o_year
    ORDER BY nation, o_year DESC
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results

