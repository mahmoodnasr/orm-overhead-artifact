-- Load TPC-H Data into SQL Server
-- Run this script inside the SQL Server container

USE tpch;
GO

-- Disable constraints for faster loading
ALTER TABLE lineitem NOCHECK CONSTRAINT ALL;
ALTER TABLE orders NOCHECK CONSTRAINT ALL;
ALTER TABLE partsupp NOCHECK CONSTRAINT ALL;
ALTER TABLE customer NOCHECK CONSTRAINT ALL;
ALTER TABLE part NOCHECK CONSTRAINT ALL;
ALTER TABLE supplier NOCHECK CONSTRAINT ALL;
ALTER TABLE nation NOCHECK CONSTRAINT ALL;
GO

-- Truncate tables
TRUNCATE TABLE lineitem;
TRUNCATE TABLE orders;
TRUNCATE TABLE partsupp;
TRUNCATE TABLE customer;
TRUNCATE TABLE part;
TRUNCATE TABLE supplier;
TRUNCATE TABLE nation;
TRUNCATE TABLE region;
GO

-- Bulk insert data
-- Note: Files must be accessible to SQL Server container

BULK INSERT region
FROM '/tpch-data/region.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1
);

BULK INSERT nation
FROM '/tpch-data/nation.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1
);

BULK INSERT supplier
FROM '/tpch-data/supplier.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1,
    TABLOCK
);

BULK INSERT customer
FROM '/tpch-data/customer.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1,
    TABLOCK
);

BULK INSERT part
FROM '/tpch-data/part.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1,
    TABLOCK
);

BULK INSERT partsupp
FROM '/tpch-data/partsupp.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1,
    TABLOCK
);

BULK INSERT orders
FROM '/tpch-data/orders.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1,
    TABLOCK
);

BULK INSERT lineitem
FROM '/tpch-data/lineitem.tbl.clean'
WITH (
    FIELDTERMINATOR = '|',
    ROWTERMINATOR = '\n',
    FIRSTROW = 1,
    TABLOCK
);
GO

-- Re-enable constraints
ALTER TABLE lineitem CHECK CONSTRAINT ALL;
ALTER TABLE orders CHECK CONSTRAINT ALL;
ALTER TABLE partsupp CHECK CONSTRAINT ALL;
ALTER TABLE customer CHECK CONSTRAINT ALL;
ALTER TABLE part CHECK CONSTRAINT ALL;
ALTER TABLE supplier CHECK CONSTRAINT ALL;
ALTER TABLE nation CHECK CONSTRAINT ALL;
GO

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
GO

