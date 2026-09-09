"""
Django settings for TPC-H ORM benchmark
Multi-database configuration for PostgreSQL, MySQL, Oracle, SQL Server
"""

import os

from odbc_driver import odbc_driver as _odbc_driver

# mssql-django 1.8.0 truncates Decimal parameters to integers in any query
# containing GROUP BY. See mssql_decimal_fix for the measurement.
import mssql_decimal_fix

mssql_decimal_fix.apply()
import sys
from pathlib import Path

# Oracle compatibility: Use oracledb as cx_Oracle replacement
try:
    import oracledb

    sys.modules["cx_Oracle"] = oracledb
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent


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


# Security settings (for benchmark only)
SECRET_KEY = "benchmark-secret-key-not-for-production"
# False. Django keeps every executed query in connection.queries when DEBUG is
# True, which grows without bound across a campaign, and it is not a setting
# anyone benchmarks under.
DEBUG = False
ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django_app",
]

MIDDLEWARE = []

ROOT_URLCONF = None

# Database configuration
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "tpch"),
        "USER": os.getenv("POSTGRES_USER", "benchmark"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "benchmark_pass"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "55432"),
        "OPTIONS": {
            "connect_timeout": 10,
        },
        "CONN_MAX_AGE": 300,  # Keep connections alive for 5 minutes  # Close connections after each request for clean measurements
    },
    "postgresql": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "tpch"),
        "USER": os.getenv("POSTGRES_USER", "benchmark"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "benchmark_pass"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "55432"),
        "OPTIONS": {
            "connect_timeout": 10,
        },
        "CONN_MAX_AGE": 300,  # Keep connections alive for 5 minutes  # Close connections after each request for clean measurements
    },
    "mysql": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DB", "tpch"),
        "USER": os.getenv("MYSQL_USER", "benchmark"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", "benchmark_pass"),
        "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.getenv("MYSQL_PORT", "33306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "use_unicode": True,
        },
        "CONN_MAX_AGE": 300,  # Keep connections alive for 5 minutes
    },
    "oracle": {
        "ENGINE": "django.db.backends.oracle",
        "NAME": os.getenv("ORACLE_HOST", "localhost")
        + ":"
        + os.getenv("ORACLE_PORT", "41521")
        + "/"
        + os.getenv("ORACLE_SERVICE", "FREEPDB1"),
        "USER": os.getenv("ORACLE_USER", "benchmark"),
        "PASSWORD": os.getenv("ORACLE_PASSWORD")
        or get_oracle_password_from_container()
        or "benchmark_pass",
        "OPTIONS": {
            "use_returning_into": False,
        },
        "CONN_MAX_AGE": 300,  # Keep connections alive for 5 minutes
    },
    "sqlserver": {
        "ENGINE": "mssql",
        "NAME": os.getenv("SQLSERVER_DB", "tpch"),
        "USER": os.getenv("SQLSERVER_USER", "sa"),
        "PASSWORD": os.getenv("SQLSERVER_PASSWORD", "YourStrong!Passw0rd"),
        "HOST": os.getenv("SQLSERVER_HOST", "localhost"),
        "PORT": os.getenv("SQLSERVER_PORT", "1433"),
        "OPTIONS": {
            "driver": _odbc_driver(),  # discovered, not hardcoded (C9)
            "extra_params": "TrustServerCertificate=yes",
        },
        "CONN_MAX_AGE": 300,  # Keep connections alive for 5 minutes
    },
}

# Default database for Django management commands
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = False

# Static files (not used in benchmark)
STATIC_URL = "/static/"

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs" / "benchmark.log",
            "formatter": "verbose",
        },
    },
    "loggers": {
        # WARNING, not DEBUG. At DEBUG this logger formats and writes one line to
        # disk for every statement Django executes, synchronously, inside the
        # timed region -- and SQLAlchemy has no equivalent, so it was a cost
        # charged to one framework and not the other.
        #
        # Measured on TPC-C New-Order, PostgreSQL, same transaction with the
        # handler attached and detached:
        #
        #     logging on   23.29 ms      logging off   8.42 ms
        #
        # 14.87 ms per transaction, 63.8% of the measured time. TPC-H is
        # unaffected at +0.55%, because a TPC-H query issues one or two
        # statements against seconds of work while a New-Order issues about
        # twenty against milliseconds. The defect is proportional to statement
        # count, which is why it hid in the benchmark that runs longest.
        #
        # It also wrote a 6.4 GB benchmark.log, which is how it was noticed.
        "django.db.backends": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": False,
        },
        "benchmark": {
            "handlers": ["console", "file"],
            "level": "INFO",
        },
    },
}

# Create logs directory if it doesn't exist
(BASE_DIR / "logs").mkdir(exist_ok=True)
