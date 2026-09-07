-- TPC-H schema for SQL Server, non-indexed configuration.
--
-- The repository had no SQL Server TPC-H DDL at all. data/indexes/sqlserver_indexes.sql
-- builds the fifteen secondary indexes that define the *indexed* configuration
-- and assumes the tables already exist, and scripts/1-setup/load_sqlserver_data.sql
-- opens with TRUNCATE TABLE against tables nothing in the repository creates.
-- This file is the missing half.
--
-- Column widths and types follow TPC-H 2.18.0 and match the PostgreSQL and
-- MySQL declarations column for column (docker/postgresql/init-db.sh and
-- scripts/1-setup/schema_mysql.sql), so a difference between the three systems
-- is not a difference in what was stored.
--
-- Two SQL Server specifics are deliberate:
--
-- *Every primary key is NONCLUSTERED.* SQL Server makes a PRIMARY KEY CLUSTERED
-- unless told otherwise, which physically orders the table on that key and
-- hands the non-indexed configuration an ordered access path PostgreSQL's heap
-- does not have. NONCLUSTERED gives a heap plus a separate B-tree, which is
-- exactly PostgreSQL's structure. MySQL cannot be made to match - InnoDB always
-- clusters on the primary key - and that difference is noted in schema_mysql.sql.
--
-- *CHAR columns stay CHAR.* On Oracle this was defect C7: a bind variable is
-- VARCHAR2, Oracle blank-pads a comparison only when both operands are CHAR, and
-- ORM predicates against CHAR columns therefore matched nothing while the same
-- predicate written as a literal matched. SQL Server pads the shorter operand
-- regardless of type, so the same predicate matches through both paths - probed
-- on this server before writing this file:
--
--     c CHAR(10) = 'BRASS', @p VARCHAR(10) = 'BRASS'
--     c = @p -> 1 row     c = 'BRASS' -> 1 row     c LIKE @p + '%' -> 1 row
--
-- so mirroring the other two schemas is safe here and no VARCHAR substitution
-- is needed. The five validation checks would catch it if this were wrong.
--
--     ./scripts/1-setup/init_sqlserver.sh          # creates the database first
--     docker exec -i orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
--         -S localhost -U sa -P "$SQLSERVER_SA_PASSWORD" -C -b -d tpch \
--         < scripts/1-setup/schema_sqlserver.sql

-- The database is chosen by the CONNECTION, never in this file.
--
-- This file used to begin by naming its own target, and on 2026-09-04 that
-- emptied a loaded database: schema_sqlserver.sql carried `USE tpch;`
-- followed by eight DROP TABLE statements, so applying it to tpch_tiny with
-- sqlcmd -d tpch_tiny silently switched back to tpch and dropped all eight
-- SF1 tables. schema_mysql.sql was one step worse - it opened with
-- DROP DATABASE IF EXISTS tpch - and was saved only by the loading role
-- lacking the privilege to get that far.
--
-- A file that selects its own database cannot be aimed, and every caller
-- that thinks it is aiming one is wrong without being told.

DROP TABLE IF EXISTS lineitem;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS partsupp;
DROP TABLE IF EXISTS part;
DROP TABLE IF EXISTS customer;
DROP TABLE IF EXISTS supplier;
DROP TABLE IF EXISTS nation;
DROP TABLE IF EXISTS region;
GO

CREATE TABLE region (
    r_regionkey BIGINT NOT NULL,
    r_name      CHAR(25),
    r_comment   VARCHAR(152),
    CONSTRAINT pk_region PRIMARY KEY NONCLUSTERED (r_regionkey)
);
GO

CREATE TABLE nation (
    n_nationkey BIGINT NOT NULL,
    n_name      CHAR(25),
    n_regionkey BIGINT,
    n_comment   VARCHAR(152),
    CONSTRAINT pk_nation PRIMARY KEY NONCLUSTERED (n_nationkey)
);
GO

CREATE TABLE supplier (
    s_suppkey   BIGINT NOT NULL,
    s_name      CHAR(25),
    s_address   VARCHAR(40),
    s_nationkey BIGINT,
    s_phone     CHAR(15),
    s_acctbal   DECIMAL(15,2),
    s_comment   VARCHAR(101),
    CONSTRAINT pk_supplier PRIMARY KEY NONCLUSTERED (s_suppkey)
);
GO

CREATE TABLE customer (
    c_custkey    BIGINT NOT NULL,
    c_name       VARCHAR(25),
    c_address    VARCHAR(40),
    c_nationkey  BIGINT,
    c_phone      CHAR(15),
    c_acctbal    DECIMAL(15,2),
    c_mktsegment CHAR(10),
    c_comment    VARCHAR(117),
    CONSTRAINT pk_customer PRIMARY KEY NONCLUSTERED (c_custkey)
);
GO

CREATE TABLE part (
    p_partkey     BIGINT NOT NULL,
    p_name        VARCHAR(55),
    p_mfgr        CHAR(25),
    p_brand       CHAR(10),
    p_type        VARCHAR(25),
    p_size        INT,
    p_container   CHAR(10),
    p_retailprice DECIMAL(15,2),
    p_comment     VARCHAR(23),
    CONSTRAINT pk_part PRIMARY KEY NONCLUSTERED (p_partkey)
);
GO

CREATE TABLE partsupp (
    ps_partkey    BIGINT NOT NULL,
    ps_suppkey    BIGINT NOT NULL,
    ps_availqty   INT,
    ps_supplycost DECIMAL(15,2),
    ps_comment    VARCHAR(199),
    CONSTRAINT pk_partsupp PRIMARY KEY NONCLUSTERED (ps_partkey, ps_suppkey)
);
GO

CREATE TABLE orders (
    o_orderkey      BIGINT NOT NULL,
    o_custkey       BIGINT,
    o_orderstatus   CHAR(1),
    o_totalprice    DECIMAL(15,2),
    o_orderdate     DATE,
    o_orderpriority CHAR(15),
    o_clerk         CHAR(15),
    o_shippriority  INT,
    o_comment       VARCHAR(79),
    CONSTRAINT pk_orders PRIMARY KEY NONCLUSTERED (o_orderkey)
);
GO

-- No primary key, matching PostgreSQL and MySQL. lineitem's TPC-H key is
-- (l_orderkey, l_linenumber); declaring it here would add a B-tree the other
-- two systems do not have in this configuration.
CREATE TABLE lineitem (
    l_orderkey      BIGINT,
    l_partkey       BIGINT,
    l_suppkey       BIGINT,
    l_linenumber    INT,
    l_quantity      DECIMAL(15,2),
    l_extendedprice DECIMAL(15,2),
    l_discount      DECIMAL(15,2),
    l_tax           DECIMAL(15,2),
    l_returnflag    CHAR(1),
    l_linestatus    CHAR(1),
    l_shipdate      DATE,
    l_commitdate    DATE,
    l_receiptdate   DATE,
    l_shipinstruct  CHAR(25),
    l_shipmode      CHAR(10),
    l_comment       VARCHAR(44)
);
GO

PRINT 'schema_sqlserver.sql: 8 tables created';
GO
