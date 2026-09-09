"""
TPC-H Queries Package

All 22 TPC-H benchmark queries implemented with both ORM and SQL versions.
"""

from . import q01, q02, q03, q04, q05, q06, q07, q08, q09, q10
from . import q11, q12, q13, q14, q15, q16, q17, q18, q19, q20
from . import q21, q22

# Map query numbers to modules
QUERY_MODULES = {
    1: q01,
    2: q02,
    3: q03,
    4: q04,
    5: q05,
    6: q06,
    7: q07,
    8: q08,
    9: q09,
    10: q10,
    11: q11,
    12: q12,
    13: q13,
    14: q14,
    15: q15,
    16: q16,
    17: q17,
    18: q18,
    19: q19,
    20: q20,
    21: q21,
    22: q22,
}


def get_query_module(query_number):
    """Get the module for a specific query number."""
    return QUERY_MODULES.get(query_number)


def get_all_queries():
    """Return list of all query numbers."""
    return list(QUERY_MODULES.keys())


def get_query_name(query_number):
    """Get the name of a query."""
    module = get_query_module(query_number)
    if module and hasattr(module, "get_query_info"):
        return module.get_query_info().get("name", f"Query {query_number}")
    return f"Query {query_number}"


def get_query_complexity(query_number):
    """Get the complexity level of a query."""
    module = get_query_module(query_number)
    if module and hasattr(module, "get_query_info"):
        return module.get_query_info().get("complexity", "Unknown")
    return "Unknown"


def get_query_info(query_number):
    """Get full info about a query."""
    module = get_query_module(query_number)
    if module and hasattr(module, "get_query_info"):
        return module.get_query_info()
    return {
        "number": query_number,
        "name": f"Query {query_number}",
        "complexity": "Unknown",
    }


__all__ = [
    "q01",
    "q02",
    "q03",
    "q04",
    "q05",
    "q06",
    "q07",
    "q08",
    "q09",
    "q10",
    "q11",
    "q12",
    "q13",
    "q14",
    "q15",
    "q16",
    "q17",
    "q18",
    "q19",
    "q20",
    "q21",
    "q22",
    "QUERY_MODULES",
    "get_query_module",
    "get_all_queries",
    "get_query_name",
    "get_query_complexity",
    "get_query_info",
]


# Check if we're using SQL Server and load appropriate query version
def get_query_module_for_db(query_num, database="default"):
    """Get the appropriate query module for the database"""
    from django.db import connections

    # Determine database engine
    engine = connections[database].settings_dict.get("ENGINE", "")

    # Check if SQL Server-specific version exists
    if "mssql" in engine.lower() or "sqlserver" in engine.lower():
        sqlserver_module = f"q{query_num:02d}_sqlserver"
        try:
            return __import__(
                f"django_app.queries.{sqlserver_module}", fromlist=[sqlserver_module]
            )
        except ImportError:
            pass  # Fall back to default

    # Check if Oracle-specific version exists
    if "oracle" in engine.lower():
        oracle_module = f"q{query_num:02d}_oracle"
        try:
            return __import__(
                f"django_app.queries.{oracle_module}", fromlist=[oracle_module]
            )
        except ImportError:
            pass  # Fall back to default

    # Default version
    default_module = f"q{query_num:02d}"
    return __import__(f"django_app.queries.{default_module}", fromlist=[default_module])
