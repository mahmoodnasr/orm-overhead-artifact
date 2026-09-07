"""
Database utility functions for TPC-C transactions
Handles vendor-specific SQL differences
"""

def get_table_name(connection, table_name):
    """
    Get properly quoted table name for the database vendor.
    
    Args:
        connection: Django database connection
        table_name: Table name (e.g., 'order')
    
    Returns:
        Properly quoted table name for the vendor
    """
    vendor = connection.vendor
    
    if vendor == 'mysql':
        return f'`{table_name}`'
    elif vendor == 'microsoft':  # SQL Server
        return f'[{table_name}]'
    elif vendor == 'oracle':
        return f'"{table_name.upper()}"'  # Oracle is case-sensitive, typically uppercase
    else:  # PostgreSQL
        return f'"{table_name}"'


def get_any_operator(connection):
    """
    Get the appropriate operator for array/IN operations.
    
    Args:
        connection: Django database connection
    
    Returns:
        Tuple of (operator, format_function)
        operator: 'ANY' or 'IN'
        format_function: Function to format the value list
    """
    vendor = connection.vendor
    
    if vendor == 'mysql':
        def format_in(values):
            placeholders = ','.join(['%s'] * len(values))
            return placeholders, values
        return 'IN', format_in
    elif vendor == 'microsoft':  # SQL Server
        def format_in(values):
            placeholders = ','.join(['%s'] * len(values))
            return placeholders, values
        return 'IN', format_in
    else:  # PostgreSQL, Oracle
        def format_any(values):
            return '%s', [values]
        return 'ANY', format_any


def get_current_timestamp(connection):
    """
    Get vendor-specific current timestamp function.
    
    Args:
        connection: Django database connection
    
    Returns:
        SQL expression for current timestamp
    """
    vendor = connection.vendor
    
    if vendor == 'oracle':
        return 'SYSDATE'
    elif vendor == 'microsoft':  # SQL Server
        return 'GETDATE()'
    else:  # PostgreSQL, MySQL
        return 'NOW()'


def get_limit_clause(connection, limit_value):
    """
    Get vendor-specific LIMIT clause.
    
    Args:
        connection: Django database connection
        limit_value: Number of rows to limit
    
    Returns:
        SQL LIMIT clause string
    """
    vendor = connection.vendor
    
    if vendor == 'oracle':
        # Oracle uses ROWNUM in WHERE clause or FETCH FIRST
        # For simplicity, we'll use FETCH FIRST (Oracle 12c+)
        return f'FETCH FIRST {limit_value} ROWS ONLY'
    elif vendor == 'microsoft':  # SQL Server
        # SQL Server uses OFFSET ... FETCH NEXT ... ROWS ONLY
        # Note: This requires ORDER BY clause before it
        return f'OFFSET 0 ROWS FETCH NEXT {limit_value} ROWS ONLY'
    else:  # PostgreSQL, MySQL
        return f'LIMIT {limit_value}'


def get_parameter_placeholder(connection):
    """
    Get vendor-specific parameter placeholder.
    
    Args:
        connection: Django database connection
    
    Returns:
        Parameter placeholder string ('%s', ':1', '?', etc.)
    """
    vendor = connection.vendor
    
    if vendor == 'oracle':
        # Oracle uses :1, :2, etc. but Django's Oracle backend uses %s
        # Actually, Django's Oracle backend converts %s to :1, :2 automatically
        return '%s'
    else:
        return '%s'

