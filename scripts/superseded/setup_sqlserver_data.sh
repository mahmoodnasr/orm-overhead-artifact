#!/bin/bash
#
# SQL Server TPC-H Data Loader
# This script loads TPC-H data into SQL Server using bcp (bulk copy program)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$PROJECT_ROOT/data/tpch-raw"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "SQL Server TPC-H Data Loader"
echo "======================================================================"

# Check if data directory exists
if [ ! -d "$DATA_DIR" ]; then
    echo -e "${RED}Error: Data directory not found: $DATA_DIR${NC}"
    echo "Please run scripts/setup/generate_tpch_data.sh first"
    exit 1
fi

# SQL Server connection parameters
SQLSERVER_HOST="${SQLSERVER_HOST:-localhost}"
SQLSERVER_PORT="${SQLSERVER_PORT:-1433}"
SQLSERVER_USER="${SQLSERVER_USER:-sa}"
SQLSERVER_PASSWORD="${SQLSERVER_PASSWORD:-YourStrong!Passw0rd}"
SQLSERVER_DB="${SQLSERVER_DB:-tpch}"

echo ""
echo "Connecting to SQL Server..."

# Check if LINEITEM has data
LINEITEM_COUNT=$(docker exec orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U "$SQLSERVER_USER" -P "$SQLSERVER_PASSWORD" -C -d "$SQLSERVER_DB" \
    -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM LINEITEM;" -h -1 -W 2>/dev/null | tr -d ' \r\n' | tail -1)

# Handle empty or non-numeric result
if [ -z "$LINEITEM_COUNT" ] || ! [[ "$LINEITEM_COUNT" =~ ^[0-9]+$ ]]; then
    LINEITEM_COUNT=0
fi

if [ "$LINEITEM_COUNT" -gt 0 ]; then
    echo -e "${YELLOW}⚠ SQL Server already has $LINEITEM_COUNT rows in LINEITEM${NC}"
    read -p "Clear all tables and reload? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy]es$ ]]; then
        echo "Aborted."
        exit 0
    fi
    
    echo ""
    echo "Clearing existing data..."
    docker exec orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
        -S localhost -U "$SQLSERVER_USER" -P "$SQLSERVER_PASSWORD" -C -d "$SQLSERVER_DB" \
        -Q "DELETE FROM LINEITEM; DELETE FROM ORDERS; DELETE FROM PARTSUPP; DELETE FROM CUSTOMER; DELETE FROM SUPPLIER; DELETE FROM PART; DELETE FROM NATION; DELETE FROM REGION;" \
        > /dev/null 2>&1
    echo -e "${GREEN}✓ Cleared all tables${NC}"
fi

echo ""
echo "Loading data into SQL Server..."
echo ""

# Function to load a table
load_table() {
    local table_name=$1
    local data_file=$2
    local num_cols=$3
    
    echo "Loading $table_name..."
    
    if [ ! -f "$data_file" ]; then
        echo -e "  ${YELLOW}⚠ Data file not found: $data_file${NC}"
        return 1
    fi
    
    # Copy data file into container
    docker cp "$data_file" orm-bench-sqlserver:/tmp/data.txt
    
    # Use sqlcmd to bulk insert (simpler than bcp for our use case)
    docker exec orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
        -S localhost -U "$SQLSERVER_USER" -P "$SQLSERVER_PASSWORD" -C -d "$SQLSERVER_DB" \
        -Q "BULK INSERT $table_name FROM '/tmp/data.txt' WITH (FIELDTERMINATOR='|', ROWTERMINATOR='\n');" \
        2>&1 | grep -v "rows affected" | grep -v "Changed database" || true
    
    # Get row count
    local count=$(docker exec orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
        -S localhost -U "$SQLSERVER_USER" -P "$SQLSERVER_PASSWORD" -C -d "$SQLSERVER_DB" \
        -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM $table_name;" -h -1 -W 2>/dev/null | tr -d ' \r\n' | tail -1)
    
    echo -e "  ${GREEN}✓ Loaded ${count} rows into $table_name${NC}"
    
    # Cleanup
    docker exec orm-bench-sqlserver bash -c "rm -f /tmp/data.txt" 2>/dev/null || true
    
    return 0
}

# Load tables in dependency order
load_table "REGION" "$DATA_DIR/region.tbl.clean" 3
load_table "NATION" "$DATA_DIR/nation.tbl.clean" 4
load_table "SUPPLIER" "$DATA_DIR/supplier.tbl.clean" 7
load_table "CUSTOMER" "$DATA_DIR/customer.tbl.clean" 8
load_table "PART" "$DATA_DIR/part.tbl.clean" 9
load_table "PARTSUPP" "$DATA_DIR/partsupp.tbl.clean" 5
load_table "ORDERS" "$DATA_DIR/orders.tbl.clean" 9
load_table "LINEITEM" "$DATA_DIR/lineitem.tbl.clean" 16

echo ""
echo "Verifying data..."
docker exec orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U "$SQLSERVER_USER" -P "$SQLSERVER_PASSWORD" -C -d "$SQLSERVER_DB" \
    -Q "SELECT 'REGION' as [Table], COUNT(*) as [Rows] FROM REGION UNION ALL SELECT 'NATION', COUNT(*) FROM NATION UNION ALL SELECT 'LINEITEM', COUNT(*) FROM LINEITEM;" \
    2>/dev/null

echo ""
echo -e "${GREEN}✓ SQL Server data loading complete!${NC}"
echo "======================================================================"

