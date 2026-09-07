"""Django settings for the SQL Server configuration.

`run_query.py` and `validate_queries.py` measure through `connections["default"]`,
so the vendor under test has to be the *default* alias. The second alias below is
needed because `get_query_module_for_db(n, vendor)` takes a database alias and
the campaign drivers pass `DJ_VENDOR`, which is the string "sqlserver";
`settings_mysql.py` and `settings_oracle.py` carry the same pairing.

**This configuration has not been exercised against a running server.** No SQL
Server campaign has been run, so treat the first validation pass as part of the
port rather than a formality. Two things are known to need attention:

*The statement timeout does not come from the harness.* `set_timeouts()` in
`run_query.py` maps postgresql to `SET statement_timeout` and mysql to
`SET SESSION max_execution_time`, and returns without doing anything for
"mssql"/"sqlserver" — the comment there says SQL Server uses a client-side query
timeout. Nothing then sets one, so a pathological query on SQL Server runs
unbounded and takes the campaign with it, which is the exact failure the
per-query harness design exists to prevent. `query_timeout` below supplies it at
the connection level instead. Keep it equal to the campaign's `--timeout` or the
two will disagree about what a timeout is.

*The ODBC driver name is environment-specific.* It is discovered from the ones
actually registered rather than written down: this file first named "ODBC Driver
18 for SQL Server" while the machine had 17 installed, and the resulting error
names a driver rather than a database, which is easy to misread as the server
being down. Driver 18 additionally defaults to encrypting connections and
rejects the self-signed certificate the container presents, which is what
`TrustServerCertificate=yes` is for; 17 does not encrypt by default and is
unaffected by it.
"""
import os

# mssql-django 1.8.0 truncates Decimal parameters to integers in any query
# containing GROUP BY. See mssql_decimal_fix for the measurement.
import mssql_decimal_fix
mssql_decimal_fix.apply()


# Moved to odbc_driver.py so this decision exists once. It was duplicated in
# django_app/settings.py, which hardcoded "ODBC Driver 17" and broke when the
# campaign host installed 18 and dropped 17 (C9).
from odbc_driver import odbc_driver as _odbc_driver

SECRET_KEY = "benchmark-only"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "django_app"]

DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": os.getenv("SQLSERVER_DB", "tpch"),
        "USER": os.getenv("SQLSERVER_USER", "sa"),
        "PASSWORD": os.getenv("SQLSERVER_PASSWORD", "YourStrong!Passw0rd"),
        "HOST": os.getenv("SQLSERVER_HOST", "127.0.0.1"),
        "PORT": os.getenv("SQLSERVER_PORT", "1433"),
        "CONN_MAX_AGE": 300,
        "OPTIONS": {
            "driver": _odbc_driver(),
            "extra_params": "TrustServerCertificate=yes",
            # Seconds. See the module docstring: the harness does not set a
            # server-side statement timeout for this vendor, so this is the only
            # thing bounding a runaway query.
            "query_timeout": int(os.getenv("QUERY_TIMEOUT", "900")),
        },
    }
}

# See the module docstring: DJ_VENDOR is used as an alias name.
DATABASES["sqlserver"] = dict(DATABASES["default"])

USE_TZ = False
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
