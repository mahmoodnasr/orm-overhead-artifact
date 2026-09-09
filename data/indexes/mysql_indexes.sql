-- MySQL Index Creation for TPC-H Benchmark
-- OPTIMIZED INDEX DESIGN based on actual query patterns
-- This design focuses on:
-- 1. Composite indexes for common filter combinations
-- 2. Essential foreign key indexes for joins
-- 3. Removing low-selectivity and rarely-used indexes
-- Run this AFTER loading data for the "Indexed" (I) schema configuration

USE tpch;

-- ============================================================================
-- LINEITEM TABLE (largest table, most queries)
-- ============================================================================
-- Primary filter: l_shipdate (used in Q1, Q3, Q6, Q12, Q14, Q19)
CREATE INDEX idx_lineitem_shipdate ON lineitem(L_SHIPDATE);

-- Foreign key indexes for joins (essential for join performance)
CREATE INDEX idx_lineitem_orderkey ON lineitem(L_ORDERKEY);
CREATE INDEX idx_lineitem_partkey ON lineitem(L_PARTKEY);
CREATE INDEX idx_lineitem_suppkey ON lineitem(L_SUPPKEY);

-- Composite index for Q6: filters on shipdate + discount + quantity
-- This is more efficient than separate indexes
CREATE INDEX idx_lineitem_shipdate_discount_qty ON lineitem(L_SHIPDATE, L_DISCOUNT, L_QUANTITY);

-- Composite index for Q12: filters on shipmode + receiptdate + commitdate + shipdate
CREATE INDEX idx_lineitem_shipmode_receiptdate ON lineitem(L_SHIPMODE, L_RECEIPTDATE, L_COMMITDATE, L_SHIPDATE);

-- ============================================================================
-- ORDERS TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_orders_custkey ON orders(O_CUSTKEY);

-- Date filter (used in Q3)
CREATE INDEX idx_orders_orderdate ON orders(O_ORDERDATE);

-- Composite for Q3: orderdate + custkey (common pattern)
CREATE INDEX idx_orders_orderdate_custkey ON orders(O_ORDERDATE, O_CUSTKEY);

-- ============================================================================
-- PARTSUPP TABLE
-- ============================================================================
-- Foreign keys for joins (composite primary key, but indexes help)
CREATE INDEX idx_partsupp_partkey ON partsupp(PS_PARTKEY);
CREATE INDEX idx_partsupp_suppkey ON partsupp(PS_SUPPKEY);

-- ============================================================================
-- CUSTOMER TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_customer_nationkey ON customer(C_NATIONKEY);

-- Market segment filter (used in Q3, Q18)
CREATE INDEX idx_customer_mktsegment ON customer(C_MKTSEGMENT);

-- ============================================================================
-- SUPPLIER TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_supplier_nationkey ON supplier(S_NATIONKEY);

-- ============================================================================
-- PART TABLE
-- ============================================================================
-- Note: Removed low-selectivity indexes on p_type, p_size, p_container
-- These columns have many distinct values and indexes don't help much
-- Queries that filter on these typically also filter on other columns
-- The primary key index on p_partkey is sufficient for joins

-- ============================================================================
-- NATION TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_nation_regionkey ON nation(N_REGIONKEY);

-- ============================================================================
-- Update Statistics
-- ============================================================================
ANALYZE TABLE lineitem;
ANALYZE TABLE orders;
ANALYZE TABLE partsupp;
ANALYZE TABLE part;
ANALYZE TABLE customer;
ANALYZE TABLE supplier;
ANALYZE TABLE nation;
ANALYZE TABLE region;

-- Report on index creation.
--
-- Was: a single SELECT that took TABLE_NAME, INDEX_NAME and the DATA_LENGTH /
-- INDEX_LENGTH columns all from information_schema.TABLES. TABLES has no
-- INDEX_NAME column, so the statement failed with ERROR 1054 and the script
-- exited non-zero *after* every index had been built correctly — which reads as
-- "indexing failed" to any driver that checks the exit status. Index names come
-- from STATISTICS; sizes come from TABLES. They are two queries because they are
-- two different granularities.

SELECT TABLE_NAME, INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS COLUMNS
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'tpch' AND INDEX_NAME <> 'PRIMARY'
GROUP BY TABLE_NAME, INDEX_NAME
ORDER BY TABLE_NAME, INDEX_NAME;

SELECT
    TABLE_NAME,
    CONCAT(ROUND(DATA_LENGTH  / 1024 / 1024, 2), ' MB') AS DATA_SIZE,
    CONCAT(ROUND(INDEX_LENGTH / 1024 / 1024, 2), ' MB') AS INDEX_SIZE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'tpch'
ORDER BY DATA_LENGTH DESC;
