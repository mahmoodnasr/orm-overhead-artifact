"""TPC-H Query 16 — SQL Server version.

Identical to `q16.py` except for one predicate in the hand-written baseline.
The ORM path is unchanged and is not repeated here for a reason: it is imported
from the shared module, so the two cannot drift apart.

`q16.py`'s baseline contains `s_comment LIKE '%Customer%Complaints%'`, and Q16
groups. mssql-django's `CursorWrapper.execute` runs `format_group_by_params` on
any statement containing the string "GROUP BY", which applies
`re.sub(r'%\w+', '{}', query)` to the whole text — so the pattern reached the
server as `'{}{}%'`, the NOT IN subquery selected no suppliers at all, and Q16
was measured with its exclusion clause disabled. It returned rows and it
returned quickly. Only the `SQL=` check, comparing the two frameworks'
baselines against each other, showed anything was wrong.

Writing the pattern as concatenation leaves no `%` followed by a word character
for that regex to match. SQL Server folds the constants at compile time, so the
plan is the one the literal would have produced. Defect C14.
"""

from ..models import PartSupp, Part, Supplier

# The ORM path is the shared one. Importing it rather than copying it means a
# later correction to Q16's ORM implementation cannot silently apply to three
# vendors and miss this one - which is how defect C9 happened.
from .q16 import run_query_orm, get_query_info  # noqa: F401
from tpch_paramsets import resolve as _paramset


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
        WHERE s_comment LIKE '%' + 'Customer' + '%' + 'Complaints' + '%'
      )
    GROUP BY p_brand, p_type, p_size
    ORDER BY supplier_cnt DESC, p_brand, p_type, p_size
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
