--
-- PostgreSQL database dump
--

\restrict ZEYXlwRz71qvYeGSzqhVyHHKFKZvChwR8XgsQw3429zBcHq4gvDRM5gg5PSZnXw

-- Dumped from database version 18.6 (Ubuntu 18.6-1.pgdg24.04+2)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-1.pgdg24.04+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: customer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer (
    c_custkey bigint NOT NULL,
    c_name character varying(25),
    c_address character varying(40),
    c_nationkey bigint,
    c_phone character(15),
    c_acctbal numeric(15,2),
    c_mktsegment character(10),
    c_comment character varying(117)
);


--
-- Name: lineitem; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lineitem (
    l_orderkey bigint,
    l_partkey bigint,
    l_suppkey bigint,
    l_linenumber integer,
    l_quantity numeric(15,2),
    l_extendedprice numeric(15,2),
    l_discount numeric(15,2),
    l_tax numeric(15,2),
    l_returnflag character(1),
    l_linestatus character(1),
    l_shipdate date,
    l_commitdate date,
    l_receiptdate date,
    l_shipinstruct character(25),
    l_shipmode character(10),
    l_comment character varying(44)
);


--
-- Name: nation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nation (
    n_nationkey bigint NOT NULL,
    n_name character(25),
    n_regionkey bigint,
    n_comment character varying(152)
);


--
-- Name: orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orders (
    o_orderkey bigint NOT NULL,
    o_custkey bigint,
    o_orderstatus character(1),
    o_totalprice numeric(15,2),
    o_orderdate date,
    o_orderpriority character(15),
    o_clerk character(15),
    o_shippriority integer,
    o_comment character varying(79)
);


--
-- Name: part; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.part (
    p_partkey bigint NOT NULL,
    p_name character varying(55),
    p_mfgr character(25),
    p_brand character(10),
    p_type character varying(25),
    p_size integer,
    p_container character(10),
    p_retailprice numeric(15,2),
    p_comment character varying(23)
);


--
-- Name: partsupp; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.partsupp (
    ps_partkey bigint NOT NULL,
    ps_suppkey bigint NOT NULL,
    ps_availqty integer,
    ps_supplycost numeric(15,2),
    ps_comment character varying(199)
);


--
-- Name: region; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.region (
    r_regionkey bigint NOT NULL,
    r_name character(25),
    r_comment character varying(152)
);


--
-- Name: supplier; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplier (
    s_suppkey bigint NOT NULL,
    s_name character(25),
    s_address character varying(40),
    s_nationkey bigint,
    s_phone character(15),
    s_acctbal numeric(15,2),
    s_comment character varying(101)
);


--
-- Name: customer customer_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer
    ADD CONSTRAINT customer_pkey PRIMARY KEY (c_custkey);


--
-- Name: nation nation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nation
    ADD CONSTRAINT nation_pkey PRIMARY KEY (n_nationkey);


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (o_orderkey);


--
-- Name: part part_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.part
    ADD CONSTRAINT part_pkey PRIMARY KEY (p_partkey);


--
-- Name: partsupp partsupp_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.partsupp
    ADD CONSTRAINT partsupp_pkey PRIMARY KEY (ps_partkey, ps_suppkey);


--
-- Name: region region_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.region
    ADD CONSTRAINT region_pkey PRIMARY KEY (r_regionkey);


--
-- Name: supplier supplier_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier
    ADD CONSTRAINT supplier_pkey PRIMARY KEY (s_suppkey);


--
-- PostgreSQL database dump complete
--

\unrestrict ZEYXlwRz71qvYeGSzqhVyHHKFKZvChwR8XgsQw3429zBcHq4gvDRM5gg5PSZnXw
