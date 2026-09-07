#!/usr/bin/env bash
# Apply the server-level initialisation the SQL Server image will not apply itself.
#
# docker/sqlserver/setup.sql is mounted at /docker-entrypoint-initdb.d/setup.sql
# by docker-compose.yml, but that path is a PostgreSQL and MySQL convention.
# mcr.microsoft.com/mssql/server has no init-directory support and ignores it,
# so the container reports "healthy" with no tpch database and the first error
# anyone sees is a connection failure naming a database rather than a server.
# This script closes that gap.
#
#     ./scripts/1-setup/init_sqlserver.sh
#
# Idempotent: setup.sql guards every CREATE with an IF NOT EXISTS.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTAINER="${SQLSERVER_CONTAINER:-orm-bench-sqlserver}"
SA_PASSWORD="${SQLSERVER_SA_PASSWORD:-YourStrong!Passw0rd}"

# The 2019 image ships both tool generations depending on the CU; prefer 18,
# which needs -C because the server presents a self-signed certificate.
if docker exec "$CONTAINER" test -x /opt/mssql-tools18/bin/sqlcmd 2>/dev/null; then
    SQLCMD=(/opt/mssql-tools18/bin/sqlcmd -C)
elif docker exec "$CONTAINER" test -x /opt/mssql-tools/bin/sqlcmd 2>/dev/null; then
    SQLCMD=(/opt/mssql-tools/bin/sqlcmd)
else
    echo "no sqlcmd in $CONTAINER" >&2
    exit 1
fi

echo "waiting for $CONTAINER to accept connections..."
for _ in $(seq 1 60); do
    if docker exec "$CONTAINER" "${SQLCMD[@]}" -S localhost -U sa -P "$SA_PASSWORD" \
            -Q "SELECT 1" >/dev/null 2>&1; then
        break
    fi
    sleep 5
done

echo "applying docker/sqlserver/setup.sql"
docker exec -i "$CONTAINER" "${SQLCMD[@]}" -S localhost -U sa -P "$SA_PASSWORD" -b \
    < "$REPO/docker/sqlserver/setup.sql"

# Prove the database is actually there. Without this the script would report
# success on a server where every batch failed, which is the failure mode that
# made the silent mount worth a defect entry in the first place.
echo "verifying:"
docker exec "$CONTAINER" "${SQLCMD[@]}" -S localhost -U sa -P "$SA_PASSWORD" -b -h -1 -W \
    -Q "SET NOCOUNT ON;
        IF DB_ID('tpch') IS NULL
            RAISERROR('tpch was not created', 16, 1);
        SELECT 'database    : ' + name FROM sys.databases WHERE name = 'tpch';
        SELECT 'max memory  : ' + CAST(value_in_use AS VARCHAR) + ' MB'
          FROM sys.configurations WHERE name = 'max server memory (MB)';
        SELECT 'maxdop      : ' + CAST(value_in_use AS VARCHAR)
          FROM sys.configurations WHERE name = 'max degree of parallelism';"
