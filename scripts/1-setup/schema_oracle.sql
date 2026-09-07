-- TPC-H schema for Oracle, non-indexed configuration.
--
-- Parity with schema.sql (PostgreSQL): primary keys only, no secondary indexes.
-- Oracle materialises a unique index for each primary key exactly as PostgreSQL
-- does, so the two "non-indexed" configurations carry the same access
-- structures and the comparison is like for like.
--
-- Type mapping: INT -> NUMBER(10), DECIMAL(15,2) -> NUMBER(15,2),
-- VARCHAR(n) -> VARCHAR2(n CHAR), and CHAR(n) -> VARCHAR2(n CHAR) as well.
--
-- That last one is deliberate and it is not cosmetic. Oracle applies
-- blank-padded comparison semantics only when both operands are CHAR. A bind
-- variable is VARCHAR2, so `r_name = :1` against a CHAR column compares
-- 'EUROPE' with 'EUROPE' plus nineteen spaces and matches nothing - while the
-- same predicate written as a literal matches, because a literal against CHAR
-- is blank-padded. The effect is that the hand-written SQL baseline returns 100
-- rows for Q2 and both ORM paths return 0, silently, with no error.
--
-- PostgreSQL and MySQL both ignore trailing blanks when comparing CHAR, so
-- declaring these columns VARCHAR2 here is what makes Oracle agree with the
-- other three systems rather than diverge from them. It also removes the
-- padding from storage, which on this dataset is worth about 1 GB - and under
-- Oracle Free's 12 GB ceiling that is not a rounding error.

CREATE TABLE region (
  r_regionkey  NUMBER(10)      NOT NULL,
  r_name       VARCHAR2(25 CHAR),
  r_comment    VARCHAR2(152 CHAR),
  CONSTRAINT pk_region PRIMARY KEY (r_regionkey)
);

CREATE TABLE nation (
  n_nationkey  NUMBER(10)      NOT NULL,
  n_name       VARCHAR2(25 CHAR),
  n_regionkey  NUMBER(10),
  n_comment    VARCHAR2(152 CHAR),
  CONSTRAINT pk_nation PRIMARY KEY (n_nationkey)
);

CREATE TABLE supplier (
  s_suppkey    NUMBER(10)      NOT NULL,
  s_name       VARCHAR2(25 CHAR),
  s_address    VARCHAR2(40 CHAR),
  s_nationkey  NUMBER(10),
  s_phone      VARCHAR2(15 CHAR),
  s_acctbal    NUMBER(15,2),
  s_comment    VARCHAR2(101 CHAR),
  CONSTRAINT pk_supplier PRIMARY KEY (s_suppkey)
);

CREATE TABLE customer (
  c_custkey    NUMBER(10)      NOT NULL,
  c_name       VARCHAR2(25 CHAR),
  c_address    VARCHAR2(40 CHAR),
  c_nationkey  NUMBER(10),
  c_phone      VARCHAR2(15 CHAR),
  c_acctbal    NUMBER(15,2),
  c_mktsegment VARCHAR2(10 CHAR),
  c_comment    VARCHAR2(117 CHAR),
  CONSTRAINT pk_customer PRIMARY KEY (c_custkey)
);

CREATE TABLE part (
  p_partkey     NUMBER(10)     NOT NULL,
  p_name        VARCHAR2(55 CHAR),
  p_mfgr        VARCHAR2(25 CHAR),
  p_brand       VARCHAR2(10 CHAR),
  p_type        VARCHAR2(25 CHAR),
  p_size        NUMBER(10),
  p_container   VARCHAR2(10 CHAR),
  p_retailprice NUMBER(15,2),
  p_comment     VARCHAR2(23 CHAR),
  CONSTRAINT pk_part PRIMARY KEY (p_partkey)
);

CREATE TABLE partsupp (
  ps_partkey    NUMBER(10)     NOT NULL,
  ps_suppkey    NUMBER(10)     NOT NULL,
  ps_availqty   NUMBER(10),
  ps_supplycost NUMBER(15,2),
  ps_comment    VARCHAR2(199 CHAR),
  CONSTRAINT pk_partsupp PRIMARY KEY (ps_partkey, ps_suppkey)
);

CREATE TABLE orders (
  o_orderkey      NUMBER(10)   NOT NULL,
  o_custkey       NUMBER(10),
  o_orderstatus   VARCHAR2(1 CHAR),
  o_totalprice    NUMBER(15,2),
  o_orderdate     DATE,
  o_orderpriority VARCHAR2(15 CHAR),
  o_clerk         VARCHAR2(15 CHAR),
  o_shippriority  NUMBER(10),
  o_comment       VARCHAR2(79 CHAR),
  CONSTRAINT pk_orders PRIMARY KEY (o_orderkey)
);

CREATE TABLE lineitem (
  l_orderkey      NUMBER(10)   NOT NULL,
  l_partkey       NUMBER(10),
  l_suppkey       NUMBER(10),
  l_linenumber    NUMBER(10)   NOT NULL,
  l_quantity      NUMBER(15,2),
  l_extendedprice NUMBER(15,2),
  l_discount      NUMBER(15,2),
  l_tax           NUMBER(15,2),
  l_returnflag    VARCHAR2(1 CHAR),
  l_linestatus    VARCHAR2(1 CHAR),
  l_shipdate      DATE,
  l_commitdate    DATE,
  l_receiptdate   DATE,
  l_shipinstruct  VARCHAR2(25 CHAR),
  l_shipmode      VARCHAR2(10 CHAR),
  l_comment       VARCHAR2(44 CHAR),
  CONSTRAINT pk_lineitem PRIMARY KEY (l_orderkey, l_linenumber)
);
