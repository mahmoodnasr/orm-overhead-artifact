"""Which SQL Server ODBC driver to use, in one place.

This existed twice: `settings_sqlserver.py` discovered the newest installed
driver, while `django_app/settings.py` hardcoded "ODBC Driver 17 for SQL
Server". They agreed until the campaign host installed msodbcsql18 and dropped
17, at which point index creation on the commercial system failed with

    [unixODBC][Driver Manager]Can't open lib 'ODBC Driver 17 for SQL Server'
    : file not found

while every path that went through settings_sqlserver.py kept working. That is
the shape of C9 - two definitions of one thing, drifting the moment either side
of the environment changes. Both modules now import this.
"""

import os


def odbc_driver():
    """The newest installed SQL Server ODBC driver, or an explicit override.

    Returns a name even when nothing is installed, so the failure is a clear
    "driver not found" at connect time rather than a confusing empty DSN.
    """
    override = os.getenv("SQLSERVER_ODBC_DRIVER")
    if override:
        return override
    try:
        import pyodbc

        found = [d for d in pyodbc.drivers() if "SQL Server" in d]
        if found:

            def version(name):
                digits = "".join(c for c in name if c.isdigit())
                return int(digits) if digits else 0

            return max(found, key=version)
    except ImportError:
        pass
    return "ODBC Driver 18 for SQL Server"
