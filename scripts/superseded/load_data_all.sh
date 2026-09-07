#!/bin/bash
# Load data into all databases

set -e

echo "==============================================="
echo "Loading TPC-H Data into All Databases"
echo "==============================================="

DATA_DIR=${1:-"data/tpch-raw"}

# Check if data exists
if [ ! -d "$DATA_DIR" ]; then
    echo "Error: Data directory $DATA_DIR not found"
    echo "Run ./scripts/generate_tpch_data.sh first"
    exit 1
fi

echo ""
echo "Loading PostgreSQL..."
./scripts/load_data_postgres.sh "$DATA_DIR"

echo ""
echo "Loading MySQL..."
./scripts/load_data_mysql.sh "$DATA_DIR"

echo ""
echo "Loading Oracle..."
./scripts/load_data_oracle.sh "$DATA_DIR"

echo ""
echo "Loading SQL Server..."
./scripts/load_data_sqlserver.sh "$DATA_DIR"

echo ""
echo "==============================================="
echo "✓ All databases loaded successfully!"
echo "==============================================="


