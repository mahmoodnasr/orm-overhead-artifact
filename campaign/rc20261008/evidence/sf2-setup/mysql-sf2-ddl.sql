CREATE TABLE `region` (
  `r_regionkey` bigint NOT NULL,
  `r_name` char(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `r_comment` varchar(152) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`r_regionkey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `nation` (
  `n_nationkey` bigint NOT NULL,
  `n_name` char(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `n_regionkey` bigint DEFAULT NULL,
  `n_comment` varchar(152) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`n_nationkey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `supplier` (
  `s_suppkey` bigint NOT NULL,
  `s_name` char(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `s_address` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `s_nationkey` bigint DEFAULT NULL,
  `s_phone` char(15) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `s_acctbal` decimal(15,2) DEFAULT NULL,
  `s_comment` varchar(101) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`s_suppkey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `customer` (
  `c_custkey` bigint NOT NULL,
  `c_name` varchar(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `c_address` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `c_nationkey` bigint DEFAULT NULL,
  `c_phone` char(15) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `c_acctbal` decimal(15,2) DEFAULT NULL,
  `c_mktsegment` char(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `c_comment` varchar(117) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`c_custkey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `part` (
  `p_partkey` bigint NOT NULL,
  `p_name` varchar(55) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `p_mfgr` char(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `p_brand` char(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `p_type` varchar(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `p_size` int DEFAULT NULL,
  `p_container` char(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `p_retailprice` decimal(15,2) DEFAULT NULL,
  `p_comment` varchar(23) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`p_partkey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `partsupp` (
  `ps_partkey` bigint NOT NULL,
  `ps_suppkey` bigint NOT NULL,
  `ps_availqty` int DEFAULT NULL,
  `ps_supplycost` decimal(15,2) DEFAULT NULL,
  `ps_comment` varchar(199) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`ps_partkey`,`ps_suppkey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `orders` (
  `o_orderkey` bigint NOT NULL,
  `o_custkey` bigint DEFAULT NULL,
  `o_orderstatus` char(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `o_totalprice` decimal(15,2) DEFAULT NULL,
  `o_orderdate` date DEFAULT NULL,
  `o_orderpriority` char(15) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `o_clerk` char(15) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `o_shippriority` int DEFAULT NULL,
  `o_comment` varchar(79) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`o_orderkey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `lineitem` (
  `l_orderkey` bigint DEFAULT NULL,
  `l_partkey` bigint DEFAULT NULL,
  `l_suppkey` bigint DEFAULT NULL,
  `l_linenumber` int DEFAULT NULL,
  `l_quantity` decimal(15,2) DEFAULT NULL,
  `l_extendedprice` decimal(15,2) DEFAULT NULL,
  `l_discount` decimal(15,2) DEFAULT NULL,
  `l_tax` decimal(15,2) DEFAULT NULL,
  `l_returnflag` char(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `l_linestatus` char(1) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `l_shipdate` date DEFAULT NULL,
  `l_commitdate` date DEFAULT NULL,
  `l_receiptdate` date DEFAULT NULL,
  `l_shipinstruct` char(25) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `l_shipmode` char(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `l_comment` varchar(44) COLLATE utf8mb4_unicode_ci DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
