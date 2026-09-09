-- Oracle Index Creation for TPC-H Benchmark
-- OPTIMIZED INDEX DESIGN based on actual query patterns
-- This design focuses on:
-- 1. Composite indexes for common filter combinations
-- 2. Essential foreign key indexes for joins
-- 3. Removing low-selectivity and rarely-used indexes
-- Run this AFTER loading data for the "Indexed" (I) schema configuration

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
-- Gather Statistics
-- ============================================================================
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'LINEITEM');
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'ORDERS');
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'PARTSUPP');
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'PART');
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'CUSTOMER');
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'SUPPLIER');
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'NATION');
EXEC DBMS_STATS.GATHER_TABLE_STATS(USER, 'REGION');

-- Report on index creation
SELECT
    TABLE_NAME,
    INDEX_NAME,
    UNIQUENESS,
    STATUS
FROM USER_INDEXES
WHERE TABLE_NAME IN ('LINEITEM', 'ORDERS', 'PARTSUPP', 'PART', 'CUSTOMER', 'SUPPLIER', 'NATION', 'REGION')
ORDER BY TABLE_NAME, INDEX_NAME;
