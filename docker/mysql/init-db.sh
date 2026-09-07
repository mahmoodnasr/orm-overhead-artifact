#!/bin/bash
set -e

echo "Initializing MySQL database 'tpch' with sample data..."

# Wait for MySQL to be ready
until mysql -u root -p"${MYSQL_ROOT_PASSWORD}" -e "SELECT 1" &>/dev/null; do
    echo "Waiting for MySQL to be ready..."
    sleep 2
done

# Run the SQL initialization script if it exists
if [ -f /docker-entrypoint-initdb.d/init-db.sql ]; then
    echo "Running SQL initialization script..."
    mysql -u root -p"${MYSQL_ROOT_PASSWORD}" tpch < /docker-entrypoint-initdb.d/init-db.sql
fi

echo "MySQL database 'tpch' initialization complete"
