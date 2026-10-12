#!/usr/bin/env python3
"""Read-only probe of one engine: identity, privileges, databases, TPC-C presence.

Used before planning the SF2 load and the transaction phase. Writes nothing to
the database. Output omits every credential.
"""
import json
import os
import sys

import django
django.setup()
from django.db import connection

d = os.environ['DJ_VENDOR']


def q(sql):
    try:
        with connection.cursor() as c:
            c.execute(sql)
            cols = [x[0].lower() for x in c.description] if c.description else []
            return [dict(zip(cols, r)) for r in c.fetchall()]
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'[:300]}


out = {'dbms': d, 'database': connection.settings_dict['NAME'], 'user': connection.settings_dict['USER']}
if d == 'postgresql':
    out['role'] = q("SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user")
    out['databases'] = q("SELECT datname, pg_database_size(datname)/1048576 AS mb FROM pg_database ORDER BY 1")
    out['schema_create'] = q("SELECT has_database_privilege(current_user, current_database(), 'CREATE') AS can_create_schema")
    out['version'] = q('SELECT version()')
    out['data_directory_free'] = q("SELECT setting FROM pg_settings WHERE name = 'data_directory'")
elif d == 'mysql':
    out['grants'] = q('SHOW GRANTS')
    out['databases'] = q("SELECT table_schema, ROUND(SUM(data_length + index_length)/1048576) AS mb FROM information_schema.tables GROUP BY table_schema")
    out['version'] = q('SELECT VERSION() AS v')
    out['local_infile'] = q('SELECT @@local_infile AS v')
elif d == 'sqlserver':
    out['roles'] = q("SELECT IS_SRVROLEMEMBER('sysadmin') AS sysadmin, IS_SRVROLEMEMBER('dbcreator') AS dbcreator")
    out['databases'] = q("SELECT d.name, SUM(f.size) * 8 / 1024 AS mb FROM sys.databases d JOIN sys.master_files f ON f.database_id = d.database_id GROUP BY d.name ORDER BY 1")
elif d == 'oracle':
    out['session_privs'] = q('SELECT privilege FROM session_privs ORDER BY 1')
    out['roles'] = q('SELECT granted_role FROM user_role_privs')
    out['v_session'] = q("SELECT COUNT(*) AS n FROM v$session")
    out['segments_mb'] = q('SELECT ROUND(SUM(bytes)/1048576) AS mb FROM user_segments')
    out['tablespace_quota'] = q('SELECT tablespace_name, max_bytes FROM user_ts_quotas')
    out['users'] = q("SELECT username FROM all_users WHERE username LIKE 'TP%' ORDER BY 1")
print(json.dumps(out, default=str, indent=1))
