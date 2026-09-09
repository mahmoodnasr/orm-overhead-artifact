"""
SQLAlchemy Database Connection Utilities

Provides connection management for multiple database backends:
- PostgreSQL
- MySQL
- Oracle
- SQL Server
"""

import os
from typing import Dict, Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool


def get_oracle_password_from_container():
    """
    Get Oracle password from container environment.
    This ensures we use the same password that the container was initialized with.
    Returns the password if found, None otherwise.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "exec", "orm-bench-oracle", "env"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if line.startswith("APP_USER_PASSWORD="):
                    return line.split("=", 1)[1]
                elif line.startswith("ORACLE_PASSWORD="):
                    return line.split("=", 1)[1]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        # Docker command failed or container not running - use environment variable or default
        pass
    return None


# Database configuration mapping - matches Django settings exactly
DB_CONFIGS = {
    "postgresql": {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": os.getenv("POSTGRES_PORT", "5433"),
        "database": os.getenv("POSTGRES_DB", "tpch"),
        "user": os.getenv("POSTGRES_USER", "benchmark"),
        "password": os.getenv("POSTGRES_PASSWORD", "benchmark_pass"),
    },
    "mysql": {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": os.getenv("MYSQL_PORT", "3306"),
        "database": os.getenv("MYSQL_DB", "tpch"),
        "user": os.getenv("MYSQL_USER", "benchmark"),
        "password": os.getenv("MYSQL_PASSWORD", "benchmark_pass"),
    },
    "oracle": {
        "host": os.getenv("ORACLE_HOST", "localhost"),
        "port": os.getenv("ORACLE_PORT", "1521"),
        "service": os.getenv("ORACLE_SERVICE", "XEPDB1"),
        "user": os.getenv("ORACLE_USER", "benchmark"),
        "password": os.getenv("ORACLE_PASSWORD")
        or get_oracle_password_from_container()
        or "benchmark_pass",
    },
    "sqlserver": {
        "host": os.getenv("SQLSERVER_HOST", "localhost"),
        "port": os.getenv("SQLSERVER_PORT", "1433"),
        "database": os.getenv("SQLSERVER_DB", "tpch"),
        "user": os.getenv("SQLSERVER_USER", "sa"),
        "password": os.getenv("SQLSERVER_PASSWORD", "YourStrong!Passw0rd"),
    },
}


def get_connection_string(database: str) -> str:
    """
    Generate SQLAlchemy connection string for specified database.

    Args:
        database: Database name ('postgresql', 'mysql', 'oracle', 'sqlserver')

    Returns:
        SQLAlchemy connection string
    """
    if database not in DB_CONFIGS:
        raise ValueError(
            f"Unknown database: {database}. Available: {list(DB_CONFIGS.keys())}"
        )

    config = DB_CONFIGS[database]

    if database == "postgresql":
        return (
            f"postgresql+psycopg2://{config['user']}:{config['password']}@"
            f"{config['host']}:{config['port']}/{config['database']}"
        )

    elif database == "mysql":
        # mysqlclient (mysqldb), not PyMySQL and not mysqlconnector.
        # Django's MySQL backend requires mysqlclient >= 2.2.1 from 6.0 on, so
        # both frameworks use it and the MySQL row compares two ORMs rather
        # than a C driver against a pure-Python one (C31). mysqlconnector
        # stays rejected for the original reason: segfaults under concurrency.
        return (
            f"mysql+mysqldb://{config['user']}:{config['password']}@"
            f"{config['host']}:{config['port']}/{config['database']}"
        )

    elif database == "oracle":
        return (
            f"oracle+oracledb://{config['user']}:{config['password']}@"
            f"{config['host']}:{config['port']}/?service_name={config['service']}"
        )

    elif database == "sqlserver":
        return (
            f"mssql+pyodbc://{config['user']}:{config['password']}@"
            f"{config['host']}:{config['port']}/{config['database']}?"
            f"driver=ODBC+Driver+17+for+SQL+Server"
        )

    raise ValueError(f"Database '{database}' not configured")


class DatabaseManager:
    """
    Manages SQLAlchemy database connections and sessions.
    """

    def __init__(self):
        self._engines: Dict[str, Engine] = {}
        self._session_makers: Dict[str, sessionmaker] = {}

    def get_engine(self, database: str, echo: bool = False) -> Engine:
        """
        Get or create engine for specified database.

        Args:
            database: Database name
            echo: Whether to echo SQL queries (for debugging)

        Returns:
            SQLAlchemy Engine instance
        """
        if database not in self._engines:
            connection_string = get_connection_string(database)

            # Create engine with connection pooling for concurrency tests
            # Use smaller pool sizes for Oracle to prevent session exhaustion
            if database == "oracle":
                pool_size = 2  # Very small base pool for Oracle
                max_overflow = 5  # Limited overflow for Oracle
                pool_timeout = 60  # Longer timeout for Oracle
            else:
                pool_size = 5  # Normal pool size for other databases
                max_overflow = 10  # Normal overflow for other databases
                pool_timeout = 30  # Normal timeout for other databases

            engine = create_engine(
                connection_string,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=3600,  # Recycle connections after 1 hour
                echo=echo,
                future=True,
            )

            # For Oracle, configure identifier preparer to uppercase table names
            # Oracle stores table names in uppercase, so we need to match that
            if database == "oracle":
                # Create a wrapper that uppercases identifiers before quoting
                original_preparer = engine.dialect.identifier_preparer
                original_quote = original_preparer.quote_identifier

                def uppercase_quote(self, value):
                    # Uppercase the identifier before quoting
                    return original_quote(value.upper())

                # Replace the quote_identifier method with bound method
                import types

                original_preparer.quote_identifier = types.MethodType(
                    uppercase_quote, original_preparer
                )

            # Apply database-specific optimizations
            if database == "postgresql":
                # PostgreSQL specific settings
                @event.listens_for(engine, "connect")
                def set_postgresql_pragmas(dbapi_conn, connection_record):
                    cursor = dbapi_conn.cursor()
                    cursor.execute("SET work_mem = '256MB'")
                    cursor.execute("SET random_page_cost = 1.1")
                    cursor.close()

            elif database == "mysql":
                # MySQL specific settings
                @event.listens_for(engine, "connect")
                def set_mysql_pragmas(dbapi_conn, connection_record):
                    cursor = dbapi_conn.cursor()
                    # query_cache_type was removed in MySQL 8.0
                    # Just ensure we're using fresh data for benchmarks
                    try:
                        cursor.execute("SET SESSION query_cache_type = OFF")
                    except:
                        pass  # Ignore if variable doesn't exist (MySQL 8.0+)
                    cursor.close()

            self._engines[database] = engine

        return self._engines[database]

    def get_session(self, database: str) -> Session:
        """
        Get a new session for specified database.

        Args:
            database: Database name

        Returns:
            SQLAlchemy Session instance
        """
        if database not in self._session_makers:
            engine = self.get_engine(database)
            # Configure session for read-only benchmark queries
            self._session_makers[database] = sessionmaker(
                bind=engine, autoflush=False, expire_on_commit=False
            )

        return self._session_makers[database]()

    def test_connection(self, database: str) -> bool:
        """
        Test database connection.

        Args:
            database: Database name

        Returns:
            True if connection successful, False otherwise
        """
        try:
            engine = self.get_engine(database)
            with engine.connect() as conn:
                # Simple query to test connection
                # Oracle requires FROM DUAL
                if database == "oracle":
                    conn.execute(text("SELECT 1 FROM DUAL"))
                else:
                    conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            print(f"Connection test failed for {database}: {e}")
            return False

    def close_all(self):
        """Close all database connections."""
        for engine in self._engines.values():
            engine.dispose()
        self._engines.clear()
        self._session_makers.clear()


# Global database manager instance
db_manager = DatabaseManager()


def get_session(database: str = "postgresql") -> Session:
    """
    Convenience function to get a database session.

    Args:
        database: Database name (default: 'postgresql')

    Returns:
        SQLAlchemy Session instance
    """
    return db_manager.get_session(database)


def execute_raw_sql(database: str, sql: str, params: Optional[Dict] = None):
    """
    Execute raw SQL query and return results.

    Args:
        database: Database name
        sql: SQL query string
        params: Optional query parameters

    Returns:
        List of dictionaries containing query results
    """
    engine = db_manager.get_engine(database)

    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        columns = result.keys()
        rows = result.fetchall()

        return [dict(zip(columns, row)) for row in rows]
