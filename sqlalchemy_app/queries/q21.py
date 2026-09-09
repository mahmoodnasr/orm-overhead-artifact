"""TPC-H Query 21: rebuilt SQLAlchemy implementation.

run_query_orm  -- genuine SQLAlchemy ORM, built from the mapped classes.
run_query_sql  -- hand-written TPC-H SQL baseline with the specification's
                  substitution parameters for this query.

The original version of this file delegated run_query_orm to run_query_sql,
so the benchmark timed raw SQL twice and reported the difference as ORM
overhead. That delegation is removed.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from ._orm import REGISTRY
from ._sql import sql_for
from tpch_paramsets import resolve as _paramset

QUERY_NUM = 21


def run_query_orm(session: Session, params=None):
    """Execute TPC-H Q21 through the SQLAlchemy ORM."""
    return REGISTRY[QUERY_NUM](session, _paramset(QUERY_NUM, params))


def run_query_sql(session: Session, params=None):
    """Execute TPC-H Q21 as hand-written SQL."""
    sql = sql_for(QUERY_NUM, session.bind.dialect.name, params)
    result = session.execute(text(sql))
    cols = list(result.keys())
    return [dict(zip(cols, row)) for row in result.fetchall()]


def get_query_info():
    return {"number": QUERY_NUM, "orm_implemented": True}
