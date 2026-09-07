#!/bin/bash
# Setup TPC-C schema and load data into PostgreSQL

set -e

DATA_DIR=${1:-"data/tpcc-raw"}
CONTAINER_NAME=${CONTAINER_NAME:-"orm-bench-postgresql"}
DB_NAME=${DB_NAME:-"tpch"}
DB_USER=${DB_USER:-"benchmark"}

echo "==============================================="
echo "Setting up TPC-C in PostgreSQL"
echo "==============================================="

# Check if data exists
if [ ! -d "$DATA_DIR" ] || [ ! -f "$DATA_DIR/warehouse.tbl.clean" ]; then
    echo "Error: TPC-C data not found in $DATA_DIR"
    echo "Run: python scripts/setup/generate_tpcc_data.py"
    exit 1
fi

# Create schema
echo "Creating TPC-C schema..."
docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" < scripts/setup/create_tpcc_schema_postgres.sql

if [ $? -ne 0 ]; then
    echo "Error: Failed to create schema"
    exit 1
fi

echo "✓ Schema created"

# Load data
echo "Loading TPC-C data..."
docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" <<EOF
\COPY warehouse FROM '/tpcc-data/warehouse.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY district FROM '/tpcc-data/district.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY item FROM '/tpcc-data/item.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY stock FROM '/tpcc-data/stock.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY customer FROM '/tpcc-data/customer.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY "order" FROM '/tpcc-data/order.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY new_order FROM '/tpcc-data/new_order.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY order_line FROM '/tpcc-data/order_line.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
\COPY history FROM '/tpcc-data/history.tbl.clean' WITH (FORMAT csv, DELIMITER '|');
EOF

if [ $? -eq 0 ]; then
    echo "✓ Data loaded successfully"
    
    # Verify data
    echo "Verifying data..."
    docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" <<EOF
SELECT 
    'warehouse' as table_name, COUNT(*) as row_count FROM warehouse
UNION ALL
SELECT 'district', COUNT(*) FROM district
UNION ALL
SELECT 'customer', COUNT(*) FROM customer
UNION ALL
SELECT 'item', COUNT(*) FROM item
UNION ALL
SELECT 'stock', COUNT(*) FROM stock
UNION ALL
SELECT 'order', COUNT(*) FROM "order"
UNION ALL
SELECT 'new_order', COUNT(*) FROM new_order
UNION ALL
SELECT 'order_line', COUNT(*) FROM order_line
UNION ALL
SELECT 'history', COUNT(*) FROM history;
EOF
else
    echo "Error: Failed to load data"
    exit 1
fi

echo ""
echo "==============================================="
echo "TPC-C setup complete!"
echo "==============================================="

