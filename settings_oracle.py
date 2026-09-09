"""Django settings for the Oracle configuration.

Django 4.2's Oracle backend imports `cx_Oracle` at module load. cx_Oracle is
superseded by python-oracledb, which ships a compatibility surface for exactly
this case, so the module is aliased before Django touches the backend. This is
Oracle's own documented migration path, not a hack around a broken driver.

The alias has to happen at settings-import time: Django imports the settings
module before it resolves DATABASES['default']['ENGINE'], so this is the last
point at which sys.modules can still be arranged.
"""

import datetime
import os
import sys

import oracledb

oracledb.version = "8.3.0"  # the version Django 4.2 checks for

# Django does `isinstance(param, (Database.Binary, datetime.timedelta))`, which
# needs Binary to be a type. cx_Oracle bound it to `bytes`; python-oracledb
# exposes it as a constructor function, so isinstance() raises TypeError on
# every parameterised query. Rebind it to the type it used to be.
if not isinstance(getattr(oracledb, "Binary", None), type):
    oracledb.Binary = bytes

# The same problem, one layer deeper, and it took a campaign to surface.
# `django/db/backends/oracle/operations.py` does
# `isinstance(value, Database.Timestamp)` when converting a DateField or a
# DateTimeField *result*. cx_Oracle bound Timestamp to datetime.datetime, a
# type; python-oracledb exposes it as the DB-API constructor function, so the
# isinstance() raises
#
#     TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
#
# Binary breaks at connection time and so was found immediately. Timestamp only
# breaks when a query *returns* a date column, so every query that filters on a
# date but does not select one - Q04, Q12 - passed, and Q03 and Q18, which
# select o_orderdate, failed after their SQL had already run. On a campaign that
# measures twenty-two queries per configuration, that is four cells lost to a
# type check rather than to anything about Oracle or about the ORM.
if not isinstance(getattr(oracledb, "Timestamp", None), type):
    oracledb.Timestamp = datetime.datetime

sys.modules["cx_Oracle"] = oracledb

SECRET_KEY = "validation-only"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.auth", "django_app"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.oracle",
        # Read from the environment so one settings module serves both
        # benchmarks. TPC-H lives in the TPCH schema and TPC-C in TPCC, because
        # both define a CUSTOMER table and Oracle has no separate "database" to
        # put them in - a schema is a user. These were hardcoded to tpch, so the
        # TPC-C campaign connected to the TPC-H schema and failed on
        # ORA-00942 for a table that exists, one user over.
        # settings_mysql.py had the same defect for the same reason.
        # ORACLE_DSN wins if set; otherwise build it from the same
        # ORACLE_HOST / ORACLE_PORT / ORACLE_SERVICE names that
        # django_app/settings.py uses, so one set of variables works for every
        # entry point. The old default was 127.0.0.1:41521, the container's
        # published port; against a native listener on 1521 every Django path
        # failed with DPY-6005 while SQLAlchemy connected, and the smoke test
        # reported n/a rather than a configuration error.
        "NAME": os.getenv("ORACLE_DSN")
        or "%s:%s/%s"
        % (
            os.getenv("ORACLE_HOST", "127.0.0.1"),
            os.getenv("ORACLE_PORT", "1521"),
            os.getenv("ORACLE_SERVICE", "FREEPDB1"),
        ),
        "USER": os.getenv("ORACLE_USER", "tpch"),
        "PASSWORD": os.getenv("ORACLE_PASSWORD", "bench"),
        "CONN_MAX_AGE": 300,
        # No OPTIONS: python-oracledb dropped cx_Oracle's `threaded` keyword,
        # and Django passes OPTIONS straight through to connect().
    }
}
DATABASES["oracle"] = dict(DATABASES["default"])
USE_TZ = False
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
