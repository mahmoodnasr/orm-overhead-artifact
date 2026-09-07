#!/bin/bash
# Load TPC-H data into PostgreSQL

set -e

DATA_DIR=${1:-"data/tpch-raw"}
POSTGRES_HOST=${POSTGRES_HOST:-"localhost"}
POSTGRES_PORT=${POSTGRES_PORT:-"5432"}
POSTGRES_DB=${POSTGRES_DB:-"tpch"}
POSTGRES_USER=${POSTGRES_USER:-"postgres"}

echo "==============================================="
echo "Loading TPC-H Data into PostgreSQL"
echo "==============================================="

# Check if data exists
if [ ! -d "$DATA_DIR" ] || [ ! -f "$DATA_DIR/customer.tbl" ]; then
    echo "Error: Data directory $DATA_DIR not found or empty"
    echo "Run ./scripts/generate_tpch_data.sh first"
    exit 1
fi

# Create schema
echo "Creating TPC-H schema..."
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB <<EOF
-- Create tables
CREATE TABLE IF NOT EXISTS region (
    r_regionkey INTEGER PRIMARY KEY,
    r_name CHAR(25),
    r_comment VARCHAR(152)
);

CREATE TABLE IF NOT EXISTS nation (
    n_nationkey INTEGER PRIMARY KEY,
    n_name CHAR(25),
    n_regionkey INTEGER REFERENCES region(r_regionkey),
    n_comment VARCHAR(152)
);

CREATE TABLE IF NOT EXISTS supplier (
    s_suppkey INTEGER PRIMARY KEY,
    s_name CHAR(25),
    s_address VARCHAR(40),
    s_nationkey INTEGER REFERENCES nation(n_nationkey),
    s_phone CHAR(15),
    s_acctbal DECIMAL(15,2),
    s_comment VARCHAR(101)
);

CREATE TABLE IF NOT EXISTS part (
    p_partkey INTEGER PRIMARY KEY,
    p_name VARCHAR(55),
    p_mfgr CHAR(25),
    p_brand CHAR(10),
    p_type VARCHAR(25),
    p_size INTEGER,
    p_container CHAR(10),
    p_retailprice DECIMAL(15,2),
    p_comment VARCHAR(23)
);

CREATE TABLE IF NOT EXISTS partsupp (
    ps_partkey INTEGER REFERENCES part(p_partkey),
    ps_suppkey INTEGER REFERENCES supplier(s_suppkey),
    ps_availqty INTEGER,
    ps_supplycost DECIMAL(15,2),
    ps_comment VARCHAR(199),
    PRIMARY KEY (ps_partkey, ps_suppkey)
);

CREATE TABLE IF NOT EXISTS customer (
    c_custkey INTEGER PRIMARY KEY,
    c_name VARCHAR(25),
    c_address VARCHAR(40),
    c_nationkey INTEGER REFERENCES nation(n_nationkey),
    c_phone CHAR(15),
    c_acctbal DECIMAL(15,2),
    c_mktsegment CHAR(10),
    c_comment VARCHAR(117)
);

CREATE TABLE IF NOT EXISTS orders (
    o_orderkey INTEGER PRIMARY KEY,
    o_custkey INTEGER REFERENCES customer(c_custkey),
    o_orderstatus CHAR(1),
    o_totalprice DECIMAL(15,2),
    o_orderdate DATE,
    o_orderpriority CHAR(15),
    o_clerk CHAR(15),
    o_shippriority INTEGER,
    o_comment VARCHAR(79)
);

CREATE TABLE IF NOT EXISTS lineitem (
    l_orderkey INTEGER REFERENCES orders(o_orderkey),
    l_partkey INTEGER REFERENCES part(p_partkey),
    l_suppkey INTEGER REFERENCES supplier(s_suppkey),
    l_linenumber INTEGER,
    l_quantity DECIMAL(15,2),
    l_extendedprice DECIMAL(15,2),
    l_discount DECIMAL(15,2),
    l_tax DECIMAL(15,2),
    l_returnflag CHAR(1),
    l_linestatus CHAR(1),
    l_shipdate DATE,
    l_commitdate DATE,
    l_receiptdate DATE,
    l_shipinstruct CHAR(25),
    l_shipmode CHAR(10),
    l_comment VARCHAR(44),
    PRIMARY KEY (l_orderkey, l_linenumber)
);
EOF

echo "✓ Schema created"

# Load data using COPY
echo ""
echo "Loading data (this may take a while)..."

for table in region nation supplier part partsupp customer orders lineitem; do
    echo "  Loading $table..."
    psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB -c \
        "COPY $table FROM STDIN WITH DELIMITER '|';" < "$DATA_DIR/${table}.tbl"
done

echo "✓ Data loaded"

# Verify row counts
echo ""
echo "Verifying row counts..."
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB <<EOF
SELECT 'region' as table_name, COUNT(*) as row_count FROM region
UNION ALL SELECT 'nation', COUNT(*) FROM nation
UNION ALL SELECT 'supplier', COUNT(*) FROM supplier
UNION ALL SELECT 'part', COUNT(*) FROM part
UNION ALL SELECT 'partsupp', COUNT(*) FROM partsupp
UNION ALL SELECT 'customer', COUNT(*) FROM customer
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'lineitem', COUNT(*) FROM lineitem;
EOF

echo ""
echo "==============================================="
echo "✓ PostgreSQL data load complete!"
echo "==============================================="
