-- TPC-H schema for MySQL, non-indexed configuration.
--
-- This file exists because the schema the earlier MySQL run used was never
-- committed, and the only MySQL DDL in the repository, docker/mysql/init-db.sql,
-- is not a non-indexed schema: it declares
--
--     INDEX idx_lineitem_shipdate (l_shipdate),
--     INDEX idx_lineitem_orderkey (l_orderkey)
--
-- inside CREATE TABLE lineitem. Those are two of the fifteen secondary indexes
-- that define the *indexed* configuration, so a database built from that file
-- carries part of the indexed design under the non-indexed label, and
-- data/indexes/mysql_indexes.sql then fails on the duplicate index names.
--
-- The physical design here mirrors docker/postgresql/init-db.sh exactly, which
-- is what "parity with PostgreSQL" means for the non-indexed configuration:
-- a primary key on every table except lineitem, and no secondary index
-- anywhere. The indexed configuration is this schema plus
-- data/indexes/mysql_indexes.sql.
--
-- Column widths and types follow TPC-H 2.18.0 and match the PostgreSQL
-- declarations column for column, so a difference between the two systems is
-- not a difference in what was stored.
--
--     mysql -h 127.0.0.1 -P 33306 -u root -pbench < schema_mysql.sql

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

CREATE TABLE region (
    r_regionkey BIGINT PRIMARY KEY,
    r_name      CHAR(25),
    r_comment   VARCHAR(152)
) ENGINE=InnoDB;

CREATE TABLE nation (
    n_nationkey BIGINT PRIMARY KEY,
    n_name      CHAR(25),
    n_regionkey BIGINT,
    n_comment   VARCHAR(152)
) ENGINE=InnoDB;

CREATE TABLE supplier (
    s_suppkey   BIGINT PRIMARY KEY,
    s_name      CHAR(25),
    s_address   VARCHAR(40),
    s_nationkey BIGINT,
    s_phone     CHAR(15),
    s_acctbal   DECIMAL(15,2),
    s_comment   VARCHAR(101)
) ENGINE=InnoDB;

CREATE TABLE customer (
    c_custkey    BIGINT PRIMARY KEY,
    c_name       VARCHAR(25),
    c_address    VARCHAR(40),
    c_nationkey  BIGINT,
    c_phone      CHAR(15),
    c_acctbal    DECIMAL(15,2),
    c_mktsegment CHAR(10),
    c_comment    VARCHAR(117)
) ENGINE=InnoDB;

CREATE TABLE part (
    p_partkey     BIGINT PRIMARY KEY,
    p_name        VARCHAR(55),
    p_mfgr        CHAR(25),
    p_brand       CHAR(10),
    p_type        VARCHAR(25),
    p_size        INT,
    p_container   CHAR(10),
    p_retailprice DECIMAL(15,2),
    p_comment     VARCHAR(23)
) ENGINE=InnoDB;

CREATE TABLE partsupp (
    ps_partkey    BIGINT,
    ps_suppkey    BIGINT,
    ps_availqty   INT,
    ps_supplycost DECIMAL(15,2),
    ps_comment    VARCHAR(199),
    PRIMARY KEY (ps_partkey, ps_suppkey)
) ENGINE=InnoDB;

CREATE TABLE orders (
    o_orderkey      BIGINT PRIMARY KEY,
    o_custkey       BIGINT,
    o_orderstatus   CHAR(1),
    o_totalprice    DECIMAL(15,2),
    o_orderdate     DATE,
    o_orderpriority CHAR(15),
    o_clerk         CHAR(15),
    o_shippriority  INT,
    o_comment       VARCHAR(79)
) ENGINE=InnoDB;

-- No primary key, matching PostgreSQL. lineitem's TPC-H key is
-- (l_orderkey, l_linenumber); declaring it in InnoDB would cluster the table on
-- that key and give the non-indexed configuration an ordered access path
-- PostgreSQL's heap does not have, which is a physical design difference
-- between the two systems rather than between the two frameworks.
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
) ENGINE=InnoDB;
