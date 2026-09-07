-- SQL Server Initialization for TPC-H Benchmark
-- Create tpch database and configure settings
--
-- THIS FILE IS NOT RUN AUTOMATICALLY. docker-compose.yml mounts it at
-- /docker-entrypoint-initdb.d/setup.sql, but that directory is a convention of
-- the PostgreSQL and MySQL images; mcr.microsoft.com/mssql/server has no
-- equivalent mechanism and ignores whatever is placed there. The container
-- therefore came up reporting "healthy" with only master, tempdb, model and
-- msdb present, and the first visible symptom was Django failing to open
-- database "tpch" - which reads as the server being unreachable rather than as
-- an init script that never executed.
--
-- Apply it explicitly instead:
--
--     ./scripts/1-setup/init_sqlserver.sh

-- Create database
IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'tpch')
BEGIN
    CREATE DATABASE tpch;
END
GO

USE tpch;
GO

-- Set database options
ALTER DATABASE tpch SET RECOVERY SIMPLE;
ALTER DATABASE tpch SET AUTO_UPDATE_STATISTICS ON;
ALTER DATABASE tpch SET AUTO_CREATE_STATISTICS ON;
ALTER DATABASE tpch SET PAGE_VERIFY CHECKSUM;
GO

-- Enable Query Store for plan capture (mentioned in paper)
ALTER DATABASE tpch SET QUERY_STORE = ON;
ALTER DATABASE tpch SET QUERY_STORE (
    OPERATION_MODE = READ_WRITE,
    CLEANUP_POLICY = (STALE_QUERY_THRESHOLD_DAYS = 30),
    DATA_FLUSH_INTERVAL_SECONDS = 900,
    MAX_STORAGE_SIZE_MB = 1000,
    INTERVAL_LENGTH_MINUTES = 60,
    SIZE_BASED_CLEANUP_MODE = AUTO,
    QUERY_CAPTURE_MODE = AUTO
);
GO

-- Memory settings
EXEC sp_configure 'show advanced options', 1;
RECONFIGURE;
GO

-- 4096 MB, the same number as the other two systems, and the reason it is the
-- same number rather than an equivalent one is the point.
--
-- This file asked for 8192 originally; it was then set to 6144 on the argument
-- that "max server memory" is a wider budget than a buffer pool - it also
-- covers the plan cache and the other memory clerks that PostgreSQL and MySQL
-- account for outside their buffer settings - so 4 GB of data cache plus ~2 GB
-- of overhead was the closer equivalent.
--
-- That argument is defensible and it is still the wrong choice here, because it
-- makes the sentence "every system was given the same memory" untrue. A
-- reviewer asking whether the four systems ran on equal resources should be
-- able to read one number off each configuration file and see that they match:
--
--     docker/postgresql/postgresql.conf   shared_buffers            = 4GB
--     docker/mysql/my.cnf                 innodb_buffer_pool_size   = 4G
--     docker/sqlserver/setup.sql          max server memory (MB)    = 4096
--
-- An exact match that slightly under-allocates SQL Server is worth more than a
-- carefully reasoned mismatch that has to be explained every time it is
-- questioned. The direction of the error is also the safe one: SQL Server gets
-- marginally less than the equivalent, so no result here can be attributed to
-- having handed it more memory than the others.
EXEC sp_configure 'max server memory (MB)', 4096;
RECONFIGURE;
GO

-- Microsoft's guidance for a single NUMA node with more than 8 logical
-- processors is MAXDOP 8, and the container sees 10. Note for the write-up
-- that this is *not* parity with the other systems: PostgreSQL 14 defaults to
-- max_parallel_workers_per_gather = 2 and MySQL 8 executes these queries
-- serially. Both access paths within SQL Server get the same MAXDOP, so the
-- ORM-versus-SQL comparison this study makes is unaffected, but the absolute
-- times are not comparable across systems and the overhead *percentage* is
-- sensitive to it - faster database execution makes the ORM's fixed
-- row-materialization cost a larger fraction of the total.
EXEC sp_configure 'max degree of parallelism', 8;
RECONFIGURE;
GO

-- Create login for benchmark
IF NOT EXISTS (SELECT name FROM sys.server_principals WHERE name = 'tpch_user')
BEGIN
    CREATE LOGIN tpch_user WITH PASSWORD = 'TpchPass123!';
END
GO

USE tpch;
GO

-- Create user and grant permissions
IF NOT EXISTS (SELECT name FROM sys.database_principals WHERE name = 'tpch_user')
BEGIN
    CREATE USER tpch_user FOR LOGIN tpch_user;
END
GO

ALTER ROLE db_owner ADD MEMBER tpch_user;
GO

PRINT 'SQL Server database tpch setup complete';
GO
