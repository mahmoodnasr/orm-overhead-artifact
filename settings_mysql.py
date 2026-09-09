"""Django settings for the MySQL configuration.

`run_query.py` and `validate_queries.py` both measure through
`connections["default"]`, so the vendor under test has to be the *default*
alias, not an alias named after itself. That is why this module exists at all
rather than the campaign selecting one of the entries in
`django_app/settings.py`.

The second alias below is not redundant. `get_query_module_for_db(n, vendor)` in
`django_app/queries/__init__.py` takes a *database alias* as its second
argument, and the campaign drivers pass `DJ_VENDOR`, which is the string
"mysql". Without an alias of that name the per-vendor module lookup raises
ConnectionDoesNotExist before it can fall back. `settings_oracle.py` carries the
same pairing for the same reason.

Host and port match what `scripts/1-setup/load_mysql.py` hardcodes
(127.0.0.1:33306, root/bench), which the repository `.env` maps the container
onto, so the loader and the harness cannot address different databases.
"""

import os

SECRET_KEY = "benchmark-only"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "django_app"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        # Read from the environment so the same settings module serves both
        # benchmarks: TPC-H lives in "tpch" and TPC-C in "tpcc" on the same
        # server. It was hardcoded to "tpch", which meant the TPC-C campaign
        # would have connected to the TPC-H database and failed on missing
        # tables. settings_sqlserver.py already reads SQLSERVER_DB this way.
        "NAME": os.getenv("MYSQL_DB", "tpch"),
        # Read from the environment, with the same names and defaults that
        # django_app/settings.py and sqlalchemy_app/database.py already use.
        # These were hardcoded to root/bench on 127.0.0.1:33306, which was the
        # container rig's port mapping. When MySQL moved to a native install on
        # 3306 every Django path failed to connect while SQLAlchemy, which
        # reads the environment, kept working - so the smoke test reported
        # 0/22 with two paths dead rather than a configuration error. Same
        # shape as load_mysql.py's hardcoded DSN and the ODBC driver name.
        "USER": os.getenv("MYSQL_USER", "benchmark"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", "benchmark_pass"),
        "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.getenv("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": 300,
        "OPTIONS": {
            "charset": "utf8mb4",
            # Django otherwise issues SET sql_mode on every connection. The
            # server already runs the STRICT_TRANS_TABLES mode my.cnf sets, and
            # leaving the statement out keeps the connection setup identical
            # between the ORM path and the hand-written path.
            "init_command": "SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        },
    }
}

# See the module docstring: DJ_VENDOR is used as an alias name.
DATABASES["mysql"] = dict(DATABASES["default"])

USE_TZ = False
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
