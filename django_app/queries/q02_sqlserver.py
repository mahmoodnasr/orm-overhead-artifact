"""
TPC-H Query 2 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""

from django.db.models import Min, Q, F
from django.db.models import Subquery, OuterRef
from ..models import Part, Supplier, PartSupp, Nation, Region


# The ORM implementation is NOT duplicated here. It was, character for
# character, and the copy went stale the moment q02.py was fixed for Django
# 6.0: the grouped Subquery passed to an `exact` lookup needs a [:1] slice from
# 6.0 on, and only the shared file got it. The smoke test on this system then
# failed with the ValueError while PostgreSQL, MySQL and Oracle passed.
#
# Only run_query_sql needs to be SQL Server specific - CAST rather than
# TO_DATE, YEAR() rather than EXTRACT. So this module overrides the SQL and
# re-exports the shared ORM (C9 - one definition).
from .q02 import run_query_orm  # noqa: F401
from tpch_paramsets import resolve as _paramset


def run_query_sql(connection, params=None):
    """Execute Q2 via direct SQL."""
    P = _paramset(2, params)

    sql = f"""
    SELECT TOP 100 s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment
    FROM part, supplier, partsupp, nation, region
    WHERE p_partkey = ps_partkey
      AND s_suppkey = ps_suppkey
      AND p_size = {P["size"]}
      AND p_type LIKE '%{P["type_suffix"]}'
      AND s_nationkey = n_nationkey
      AND n_regionkey = r_regionkey
      AND r_name = '{P["region"]}'
      AND ps_supplycost = (
        SELECT MIN(ps_supplycost)
        FROM partsupp, supplier, nation, region
        WHERE p_partkey = ps_partkey
          AND s_suppkey = ps_suppkey
          AND s_nationkey = n_nationkey
          AND n_regionkey = r_regionkey
          AND r_name = '{P["region"]}'
      )
    ORDER BY s_acctbal DESC, n_name, s_name, p_partkey
    
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        "number": 2,
        "name": "Minimum Cost Supplier",
        "complexity": "Complex",
        "description": "Find suppliers with minimum cost for given part type and region",
        "tables": ["part", "supplier", "partsupp", "nation", "region"],
        "joins": 4,
        "aggregations": 1,
        "subqueries": 1,
    }
