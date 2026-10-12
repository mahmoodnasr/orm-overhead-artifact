"""Django application for TPC-H benchmark.

This module used to install PyMySQL under the MySQLdb name:

    import pymysql
    pymysql.install_as_MySQLdb()

That is gone, and deliberately (C31). Django's MySQL backend gates on the
DBAPI's reported version. Django 4.2 and 5.2 require mysqlclient >= 1.4.3 and
PyMySQL reports 1.4.6, so the shim cleared the floor by three patch versions
of a number belonging to another project. Django 6.0 raises the floor to
2.2.1 and the shim fails at import - and because this ran on *any* import of
django_app, it took PostgreSQL, Oracle and SQL Server down with it.

mysqlclient provides MySQLdb natively, so no shim is needed. SQLAlchemy moved
to mysql+mysqldb:// at the same time and for the same reason: a C extension
under one framework and a pure-Python driver under the other would be charged
to the framework, not to the driver.
"""
