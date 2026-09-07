"""
Database utility functions for TPC-C transactions
Handles vendor-specific SQL differences for SQLAlchemy
"""

def get_table_name(session, table_name):
    """
    Get properly quoted table name for the database vendor.
    
    Args:
        session: SQLAlchemy session
        table_name: Table name (e.g., 'order')
    
    Returns:
        Properly quoted table name for the vendor
    """
    vendor = session.bind.dialect.name
    
    if vendor == 'mysql':
        return f'`{table_name}`'
    elif vendor == 'mssql':  # SQL Server
        return f'[{table_name}]'
    elif vendor == 'oracle':
        return f'"{table_name.upper()}"'  # Oracle is case-sensitive, typically uppercase
    else:  # PostgreSQL
        return f'"{table_name}"'


def get_any_operator(session):
    """
    Get the appropriate operator for array/IN operations.
    
    Args:
        session: SQLAlchemy session
    
    Returns:
        Tuple of (operator, format_function)
        operator: 'ANY' or 'IN'
        format_function: Function to format the value list
    """
    vendor = session.bind.dialect.name
    
    if vendor == 'mysql':
        def format_in(values):
            placeholders = ','.join([f':id{i}' for i in range(len(values))])
            params = {f'id{i}': val for i, val in enumerate(values)}
            return placeholders, params
        return 'IN', format_in
    elif vendor == 'mssql':  # SQL Server
        def format_in(values):
            placeholders = ','.join([f':id{i}' for i in range(len(values))])
            params = {f'id{i}': val for i, val in enumerate(values)}
            return placeholders, params
        return 'IN', format_in
    elif vendor == 'oracle':
        # Oracle doesn't support ANY(:values) in regular SQL, only in PL/SQL
        # Use IN with expanded placeholders instead
        def format_in(values):
            placeholders = ','.join([f':id{i}' for i in range(len(values))])
            params = {f'id{i}': val for i, val in enumerate(values)}
            return placeholders, params
        return 'IN', format_in
    else:  # PostgreSQL
        def format_any(values):
            return ':values', {'values': values}
        return 'ANY', format_any


def get_current_timestamp(session):
    """
    Get vendor-specific current timestamp function.
    
    Args:
        session: SQLAlchemy session
    
    Returns:
        SQL expression for current timestamp
    """
    vendor = session.bind.dialect.name
    
    if vendor == 'oracle':
        return 'SYSDATE'
    elif vendor == 'mssql':  # SQL Server
        return 'GETDATE()'
    else:  # PostgreSQL, MySQL
        return 'NOW()'


def get_limit_clause(session, limit):
    """
    Get vendor-specific LIMIT clause.
    
    Args:
        session: SQLAlchemy session
        limit: Number of rows to limit
    
    Returns:
        SQL LIMIT clause string
    """
    vendor = session.bind.dialect.name
    
    if vendor == 'oracle':
        return f'FETCH FIRST {limit} ROWS ONLY'
    elif vendor == 'mssql':  # SQL Server
        return f'OFFSET 0 ROWS FETCH NEXT {limit} ROWS ONLY'
    else:  # PostgreSQL, MySQL
        return f'LIMIT {limit}'

