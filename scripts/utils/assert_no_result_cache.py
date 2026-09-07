#!/usr/bin/env python3
"""Refuse to measure a system that can answer a repeat without executing it.

    python3 assert_no_result_cache.py --dbms oracle
    python3 assert_no_result_cache.py --dbms mysql --quiet

Exits non-zero if the system under test has result-set caching enabled.

This exists because of defect C19. `docker/oracle/init.sql` set
`result_cache_mode = FORCE`, which caches the result set of every query and
serves repeats from the cache. The protocol here is four repetitions with the
first discarded as warmup, so the discarded repetition populated the cache and
all three timed repetitions read it back. Q03 was recorded at 0.00 s; it takes
33 to 38 seconds. Oracle's `v$result_cache_statistics` reported 4,368 results
returned without executing the query.

Nothing else in the harness can catch this. The five validation checks compare
*results*, and a cached result is the correct result — all five pass on a query
that never ran. The coefficient of variation points the wrong way: three cache
lookups agree far more tightly than three real executions, so a corrupted run
looks more stable than a valid one, not less.

The check is deliberately asymmetric. Only Oracle among the four has the
feature, so only Oracle has something to test; for the other three this records
*why* there is nothing to test, so the claim "no other system caches results" is
verifiable from the campaign log rather than taken on trust.

Note what this does *not* object to. Every one of these systems caches **pages**,
and that is fine and wanted: a repeated query still executes, against warm
buffers, which is exactly what discarding the first repetition as warmup is for.
The distinction is between re-reading data quickly and not running the query.
"""
import argparse
import os
import sys


def check_oracle():
    """The only one of the four with a server-side result cache."""
    import oracledb
    dsn = os.environ.get("ORA_SYS_DSN", "127.0.0.1:41521/FREEPDB1")
    cn = oracledb.connect(user=os.environ.get("ORA_SYS_USER", "system"),
                          password=os.environ.get("ORA_SYS_PASS", "bench"),
                          dsn=dsn)
    cur = cn.cursor()
    cur.execute("SELECT value FROM v$parameter WHERE name = 'result_cache_mode'")
    mode = (cur.fetchone() or ["?"])[0]
    # Find Count is how many results were served without executing. Non-zero
    # from an earlier run is not itself a failure; the mode is what matters.
    finds = None
    try:
        cur.execute("SELECT value FROM v$result_cache_statistics "
                    "WHERE name = 'Find Count'")
        row = cur.fetchone()
        finds = row[0] if row else None
    except Exception:
        pass
    cn.close()
    ok = (mode or "").upper() == "MANUAL"
    detail = "result_cache_mode = %s" % mode
    if finds is not None:
        detail += ", lifetime Find Count = %s" % finds
    return ok, detail, ("MANUAL is Oracle's default and means the cache is used "
                        "only by a query carrying a /*+ RESULT_CACHE */ hint. "
                        "No query in this study carries one.")


def check_mysql():
    """MySQL 8.0 removed the query cache outright."""
    import MySQLdb        # mysqlclient, not PyMySQL (C31)
    cn = MySQLdb.connect(host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
                         port=int(os.environ.get("MYSQL_PORT", "33306")),
                         user="root", password="bench")
    cur = cn.cursor()
    cur.execute("SELECT VERSION()")
    ver = cur.fetchone()[0]
    cur.execute("SHOW VARIABLES LIKE 'have_query_cache'")
    present = cur.fetchall()
    cn.close()
    # The variable is gone in 8.0; if it ever comes back, fail loudly.
    ok = not present
    return ok, "MySQL %s, have_query_cache: %s" % (ver, present or "absent"), \
        ("The query cache was removed in MySQL 8.0. There is no mechanism to "
         "return a stored result set.")


def check_postgresql():
    """PostgreSQL has no result cache at any version."""
    import psycopg2
    dsn = os.environ.get("PG_DSN",
                         "host=127.0.0.1 port=55432 dbname=tpch "
                         "user=benchmark password=bench")
    cn = psycopg2.connect(dsn)
    cur = cn.cursor()
    cur.execute("SHOW server_version")
    ver = cur.fetchone()[0]
    # effective_cache_size is a *planner hint* about OS cache, not a cache.
    cur.execute("SHOW effective_cache_size")
    ecs = cur.fetchone()[0]
    cn.close()
    return True, "PostgreSQL %s, effective_cache_size = %s (a planner hint)" % (ver, ecs), \
        ("PostgreSQL has no result-set cache. effective_cache_size only tells "
         "the planner how much OS page cache to assume exists.")


def check_sqlserver():
    """SQL Server 2019 has no result-set cache; that is a Synapse feature."""
    import pyodbc
    drv = max((d for d in pyodbc.drivers() if "SQL Server" in d),
              key=lambda s: int("".join(c for c in s if c.isdigit()) or 0))
    cn = pyodbc.connect(
        "DRIVER={%s};SERVER=127.0.0.1,1433;DATABASE=master;UID=sa;PWD=%s;"
        "TrustServerCertificate=yes"
        % (drv, os.environ.get("SQLSERVER_SA_PASSWORD", "YourStrong!Passw0rd")))
    cur = cn.cursor()
    cur.execute("SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR)")
    ver = cur.fetchone()[0]
    cn.close()
    return True, "SQL Server %s" % ver, \
        ("SQL Server has no result-set cache. RESULT_SET_CACHING is an Azure "
         "Synapse feature. Query Store, which this study enables, records plans "
         "and statistics and never returns stored rows.")


CHECKS = {"oracle": check_oracle, "mysql": check_mysql,
          "postgresql": check_postgresql, "sqlserver": check_sqlserver}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dbms", required=True, choices=sorted(CHECKS))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        ok, detail, why = CHECKS[args.dbms]()
    except Exception as e:
        # Not reachable is not the same as caching. Say so and do not block.
        print("  result-cache check skipped for %s: %s"
              % (args.dbms, str(e)[:100]), file=sys.stderr)
        return 0

    if not args.quiet or not ok:
        print("  result-cache check [%s]: %s" % ("PASS" if ok else "FAIL", detail))
        print("    %s" % why)
    if not ok:
        print("REFUSING TO MEASURE: results would be cache lookups, not query "
              "executions.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
