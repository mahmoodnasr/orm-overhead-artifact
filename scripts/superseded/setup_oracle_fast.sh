#!/bin/bash
# Fast Oracle setup using SQL*Loader for large tables
set -e

ORACLE_HOST=${ORACLE_HOST:-localhost}
ORACLE_PORT=${ORACLE_PORT:-1521}
ORACLE_SERVICE=${ORACLE_SERVICE:-XEPDB1}
ORACLE_USER=${ORACLE_USER:-benchmark}
ORACLE_PASSWORD=${ORACLE_PASSWORD:-benchmark_pass}
DATA_DIR="data/tpch-raw"

echo "============================================================"
echo "Fast Oracle TPC-H Data Loading"
echo "============================================================"

# Create control file for ORDERS
cat > /tmp/orders.ctl <<EOF
LOAD DATA
CHARACTERSET UTF8
INFILE '/tpch-data/orders.tbl.clean'
APPEND INTO TABLE ORDERS
FIELDS TERMINATED BY '|'
TRAILING NULLCOLS
(
  O_ORDERKEY,
  O_CUSTKEY,
  O_ORDERSTATUS,
  O_TOTALPRICE,
  O_ORDERDATE DATE "YYYY-MM-DD",
  O_ORDERPRIORITY,
  O_CLERK,
  O_SHIPPRIORITY,
  O_COMMENT
)
EOF

# Create control file for LINEITEM
cat > /tmp/lineitem.ctl <<EOF
LOAD DATA
CHARACTERSET UTF8
INFILE '/tpch-data/lineitem.tbl.clean'
APPEND INTO TABLE LINEITEM
FIELDS TERMINATED BY '|'
TRAILING NULLCOLS
(
  L_ORDERKEY,
  L_PARTKEY,
  L_SUPPKEY,
  L_LINENUMBER,
  L_QUANTITY,
  L_EXTENDEDPRICE,
  L_DISCOUNT,
  L_TAX,
  L_RETURNFLAG,
  L_LINESTATUS,
  L_SHIPDATE DATE "YYYY-MM-DD",
  L_COMMITDATE DATE "YYYY-MM-DD",
  L_RECEIPTDATE DATE "YYYY-MM-DD",
  L_SHIPINSTRUCT,
  L_SHIPMODE,
  L_COMMENT
)
EOF

echo "Loading ORDERS table..."
docker cp /tmp/orders.ctl orm-bench-oracle:/tmp/
docker exec orm-bench-oracle sqlldr $ORACLE_USER/$ORACLE_PASSWORD@$ORACLE_SERVICE control=/tmp/orders.ctl log=/tmp/orders.log bad=/tmp/orders.bad errors=1000000 direct=true

echo "Loading LINEITEM table..."
docker cp /tmp/lineitem.ctl orm-bench-oracle:/tmp/
docker exec orm-bench-oracle sqlldr $ORACLE_USER/$ORACLE_PASSWORD@$ORACLE_SERVICE control=/tmp/lineitem.ctl log=/tmp/lineitem.log bad=/tmp/lineitem.bad errors=1000000 direct=true

echo "✓ Data loading complete!"
echo ""
echo "Verifying row counts..."
docker exec orm-bench-oracle sqlplus -s $ORACLE_USER/$ORACLE_PASSWORD@$ORACLE_SERVICE <<EOSQL
SET PAGESIZE 0
SET FEEDBACK OFF
SELECT 'ORDERS: ' || COUNT(*) FROM ORDERS;
SELECT 'LINEITEM: ' || COUNT(*) FROM LINEITEM;
EXIT;
EOSQL

echo "✓ Fast Oracle setup complete!"

