-- Load TPC-H Data into Oracle
-- Run this script inside the Oracle container

-- Truncate tables
TRUNCATE TABLE lineitem;
TRUNCATE TABLE orders;
TRUNCATE TABLE partsupp;
TRUNCATE TABLE customer;
TRUNCATE TABLE part;
TRUNCATE TABLE supplier;
TRUNCATE TABLE nation;
TRUNCATE TABLE region;

-- Load data using SQL*Loader control files or direct path
-- Note: Oracle requires control files for bulk loading
-- Alternative: Use external tables

-- For now, use INSERT statements (slower but works)
-- In production, use SQL*Loader or Oracle Data Pump

-- Example for region (small table)
-- You would need to create control files for larger tables

-- Verify counts
SELECT 'region' as table_name, COUNT(*) as row_count FROM region
UNION ALL
SELECT 'nation', COUNT(*) FROM nation
UNION ALL
SELECT 'supplier', COUNT(*) FROM supplier
UNION ALL
SELECT 'customer', COUNT(*) FROM customer
UNION ALL
SELECT 'part', COUNT(*) FROM part
UNION ALL
SELECT 'partsupp', COUNT(*) FROM partsupp
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'lineitem', COUNT(*) FROM lineitem;

