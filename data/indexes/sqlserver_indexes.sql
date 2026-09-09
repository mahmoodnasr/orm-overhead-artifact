-- SQL Server Index Creation for TPC-H Benchmark
-- OPTIMIZED INDEX DESIGN based on actual query patterns
-- This design focuses on:
-- 1. Composite indexes for common filter combinations
-- 2. Essential foreign key indexes for joins
-- 3. Removing low-selectivity and rarely-used indexes
-- Run this AFTER loading data for the "Indexed" (I) schema configuration

USE tpch;
GO

-- ============================================================================
-- LINEITEM TABLE (largest table, most queries)
-- ============================================================================
-- Primary filter: l_shipdate (used in Q1, Q3, Q6, Q12, Q14, Q19)
CREATE INDEX idx_lineitem_shipdate ON dbo.lineitem(L_SHIPDATE);
GO

-- Foreign key indexes for joins (essential for join performance)
CREATE INDEX idx_lineitem_orderkey ON dbo.lineitem(L_ORDERKEY);
GO
CREATE INDEX idx_lineitem_partkey ON dbo.lineitem(L_PARTKEY);
GO
CREATE INDEX idx_lineitem_suppkey ON dbo.lineitem(L_SUPPKEY);
GO

-- Composite index for Q6: filters on shipdate + discount + quantity
-- This is more efficient than separate indexes
CREATE INDEX idx_lineitem_shipdate_discount_qty ON dbo.lineitem(L_SHIPDATE, L_DISCOUNT, L_QUANTITY);
GO

-- Composite index for Q12: filters on shipmode + receiptdate + commitdate + shipdate
CREATE INDEX idx_lineitem_shipmode_receiptdate ON dbo.lineitem(L_SHIPMODE, L_RECEIPTDATE, L_COMMITDATE, L_SHIPDATE);
GO

-- ============================================================================
-- ORDERS TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_orders_custkey ON dbo.orders(O_CUSTKEY);
GO

-- Date filter (used in Q3)
CREATE INDEX idx_orders_orderdate ON dbo.orders(O_ORDERDATE);
GO

-- Composite for Q3: orderdate + custkey (common pattern)
CREATE INDEX idx_orders_orderdate_custkey ON dbo.orders(O_ORDERDATE, O_CUSTKEY);
GO

-- ============================================================================
-- PARTSUPP TABLE
-- ============================================================================
-- Foreign keys for joins (composite primary key, but indexes help)
CREATE INDEX idx_partsupp_partkey ON dbo.partsupp(PS_PARTKEY);
GO
CREATE INDEX idx_partsupp_suppkey ON dbo.partsupp(PS_SUPPKEY);
GO

-- ============================================================================
-- CUSTOMER TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_customer_nationkey ON dbo.customer(C_NATIONKEY);
GO

-- Market segment filter (used in Q3, Q18)
CREATE INDEX idx_customer_mktsegment ON dbo.customer(C_MKTSEGMENT);
GO

-- ============================================================================
-- SUPPLIER TABLE
-- ============================================================================
-- Foreign key for joins
CREATE INDEX idx_supplier_nationkey ON dbo.supplier(S_NATIONKEY);
GO

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
CREATE INDEX idx_nation_regionkey ON dbo.nation(N_REGIONKEY);
GO

-- ============================================================================
-- Update Statistics
-- ============================================================================
UPDATE STATISTICS dbo.lineitem WITH FULLSCAN;
GO
UPDATE STATISTICS dbo.orders WITH FULLSCAN;
GO
UPDATE STATISTICS dbo.partsupp WITH FULLSCAN;
GO
UPDATE STATISTICS dbo.part WITH FULLSCAN;
GO
UPDATE STATISTICS dbo.customer WITH FULLSCAN;
GO
UPDATE STATISTICS dbo.supplier WITH FULLSCAN;
GO
UPDATE STATISTICS dbo.nation WITH FULLSCAN;
GO
UPDATE STATISTICS dbo.region WITH FULLSCAN;
GO

-- Report on index creation
SELECT
    t.name AS TableName,
    i.name AS IndexName,
    i.type_desc AS IndexType
FROM sys.indexes i
INNER JOIN sys.tables t ON i.object_id = t.object_id
WHERE t.name IN ('lineitem', 'orders', 'partsupp', 'part', 'customer', 'supplier', 'nation', 'region')
  AND i.name IS NOT NULL
ORDER BY t.name, i.name;
GO
