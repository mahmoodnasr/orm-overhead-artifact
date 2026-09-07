#!/bin/bash
# Wait for all databases to be ready

set -e

echo "Waiting for databases to be ready..."

# PostgreSQL
echo -n "  PostgreSQL... "
until pg_isready -h localhost -p 5432 -U postgres > /dev/null 2>&1; do
    sleep 1
done
echo "✓"

# MySQL
echo -n "  MySQL... "
until mysqladmin ping -h localhost -P 3306 --silent > /dev/null 2>&1; do
    sleep 1
done
echo "✓"

# Oracle (check if port is open)
echo -n "  Oracle... "
until nc -z localhost 1521 > /dev/null 2>&1; do
    sleep 1
done
echo "✓"

# SQL Server
echo -n "  SQL Server... "
until nc -z localhost 1433 > /dev/null 2>&1; do
    sleep 1
done
echo "✓"

echo ""
echo "✓ All databases are ready!"

