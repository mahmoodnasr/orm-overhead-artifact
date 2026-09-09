-- PostgreSQL Index Creation for TPC-H Benchmark
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
CREATE INDEX idx_lineitem_shipdate ON lineitem(l_shipdate);

-- Foreign key indexes for joins (essential for join performance)
CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey);
CREATE INDEX idx_lineitem_partkey ON lineitem(l_partkey);
CREATE INDEX idx_lineitem_suppkey ON lineitem(l_suppkey);

-- Composite index for Q6: filters on shipdate + discount + quantity
-- This is more efficient than separate indexes
CREATE INDEX idx_lineitem_shipdate_discount_qty ON lineitem(l_shipdate, l_discount, l_quantity);

-- Composite index for Q12: filters on shipmode + receiptdate + commitdate + shipdate
CREATE INDEX idx_lineitem_shipmode_receiptdate ON lineitem(l_shipmode, l_receiptdate, l_commitdate, l_shipdate);

-- ============================================================================
-- ORDERS TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_orders_custkey ON orders(o_custkey);

-- Date filter (used in Q3)
CREATE INDEX idx_orders_orderdate ON orders(o_orderdate);

-- Composite for Q3: orderdate + custkey (common pattern)
CREATE INDEX idx_orders_orderdate_custkey ON orders(o_orderdate, o_custkey);

-- ============================================================================
-- PARTSUPP TABLE
-- ============================================================================
-- Foreign keys for joins (composite primary key, but indexes help)
CREATE INDEX idx_partsupp_partkey ON partsupp(ps_partkey);
CREATE INDEX idx_partsupp_suppkey ON partsupp(ps_suppkey);

-- ============================================================================
-- CUSTOMER TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_customer_nationkey ON customer(c_nationkey);

-- Market segment filter (used in Q3, Q18)
CREATE INDEX idx_customer_mktsegment ON customer(c_mktsegment);

-- ============================================================================
-- SUPPLIER TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_supplier_nationkey ON supplier(s_nationkey);

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
CREATE INDEX idx_nation_regionkey ON nation(n_regionkey);

-- ============================================================================
-- Update Statistics
-- ============================================================================
ANALYZE lineitem;
ANALYZE orders;
ANALYZE partsupp;
ANALYZE part;
ANALYZE customer;
ANALYZE supplier;
ANALYZE nation;
ANALYZE region;

-- Report on index creation.
--
-- This selected pg_relation_size(indexrelid). `indexrelid` is a column of
-- pg_index, the catalogue table; this query reads pg_indexes, the view, joined
-- to pg_class, and neither has that column. So the statement raised
-- "column indexrelid does not exist" every time - after all fifteen CREATE
-- INDEX statements and all eight ANALYZEs had already succeeded.
--
-- Under `psql -v ON_ERROR_STOP=1` that non-zero exit makes a completed index
-- build look like a failed one, which is exactly what happened: an automated
-- run aborted the campaign here with "index build failed" while all fifteen
-- indexes sat correctly in the database. data/indexes/mysql_indexes.sql had the
-- same defect in its own dialect (ERROR 1054, selecting INDEX_NAME from
-- information_schema.TABLES) and was fixed earlier for the same reason.
--
-- The size comes from pg_class.oid, which is what pg_relation_size wants.
SELECT
    i.schemaname,
    i.tablename,
    i.indexname,
    pg_size_pretty(pg_relation_size(c.oid)) AS index_size
FROM pg_indexes i
JOIN pg_class c ON c.relname = i.indexname
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = i.schemaname
WHERE i.schemaname = 'public'
ORDER BY i.tablename, i.indexname;
