-- TPC-C Schema for MySQL
-- Creates all 9 TPC-C tables with proper constraints

-- Drop existing tables if they exist
DROP TABLE IF EXISTS history;
DROP TABLE IF EXISTS order_line;
DROP TABLE IF EXISTS new_order;
DROP TABLE IF EXISTS `order`;
DROP TABLE IF EXISTS customer;
DROP TABLE IF EXISTS stock;
DROP TABLE IF EXISTS item;
DROP TABLE IF EXISTS district;
DROP TABLE IF EXISTS warehouse;

-- Create warehouse table
CREATE TABLE warehouse (
    w_id INTEGER PRIMARY KEY,
    w_name CHAR(10),
    w_street_1 VARCHAR(20),
    w_street_2 VARCHAR(20),
    w_city VARCHAR(20),
    w_state CHAR(2),
    w_zip CHAR(9),
    w_tax DECIMAL(4,4),
    w_ytd DECIMAL(12,2)
);

-- Create district table
CREATE TABLE district (
    d_id INTEGER,
    d_w_id INTEGER,
    d_name CHAR(10),
    d_street_1 VARCHAR(20),
    d_street_2 VARCHAR(20),
    d_city VARCHAR(20),
    d_state CHAR(2),
    d_zip CHAR(9),
    d_tax DECIMAL(4,4),
    d_ytd DECIMAL(12,2),
    d_next_o_id INTEGER,
    PRIMARY KEY (d_w_id, d_id),
    FOREIGN KEY (d_w_id) REFERENCES warehouse(w_id)
);

-- Create customer table
CREATE TABLE customer (
    c_id INTEGER,
    c_d_id INTEGER,
    c_w_id INTEGER,
    c_first VARCHAR(16),
    c_middle CHAR(2),
    c_last VARCHAR(16),
    c_street_1 VARCHAR(20),
    c_street_2 VARCHAR(20),
    c_city VARCHAR(20),
    c_state CHAR(2),
    c_zip CHAR(9),
    c_phone CHAR(16),
    c_since DATETIME,
    c_credit CHAR(2),
    c_credit_lim DECIMAL(12,2),
    c_discount DECIMAL(4,4),
    c_balance DECIMAL(12,2),
    c_ytd_payment DECIMAL(12,2),
    c_payment_cnt INTEGER,
    c_delivery_cnt INTEGER,
    c_data VARCHAR(500),
    PRIMARY KEY (c_w_id, c_d_id, c_id),
    FOREIGN KEY (c_w_id) REFERENCES warehouse(w_id)
);

-- Create history table
CREATE TABLE history (
    h_c_id INTEGER,
    h_c_d_id INTEGER,
    h_c_w_id INTEGER,
    h_d_id INTEGER,
    h_w_id INTEGER,
    h_date DATETIME,
    h_amount DECIMAL(6,2),
    h_data VARCHAR(24)
);

-- Create item table
CREATE TABLE item (
    i_id INTEGER PRIMARY KEY,
    i_im_id INTEGER,
    i_name VARCHAR(24),
    i_price DECIMAL(5,2),
    i_data VARCHAR(50)
);

-- Create stock table
CREATE TABLE stock (
    s_i_id INTEGER,
    s_w_id INTEGER,
    s_quantity INTEGER,
    s_dist_01 CHAR(24),
    s_dist_02 CHAR(24),
    s_dist_03 CHAR(24),
    s_dist_04 CHAR(24),
    s_dist_05 CHAR(24),
    s_dist_06 CHAR(24),
    s_dist_07 CHAR(24),
    s_dist_08 CHAR(24),
    s_dist_09 CHAR(24),
    s_dist_10 CHAR(24),
    s_ytd INTEGER,
    s_order_cnt INTEGER,
    s_remote_cnt INTEGER,
    s_data VARCHAR(50),
    PRIMARY KEY (s_w_id, s_i_id),
    -- No FOREIGN KEY (s_i_id) REFERENCES item(i_id): InnoDB will not
    -- drop the index that backs it, which made the non-indexed
    -- configuration unreachable on MySQL alone. See the note above the
    -- index block at the end of this file.
    FOREIGN KEY (s_w_id) REFERENCES warehouse(w_id)
);

-- Create order table (order is a reserved word in MySQL, so we use backticks)
CREATE TABLE `order` (
    o_id INTEGER,
    o_d_id INTEGER,
    o_w_id INTEGER,
    o_c_id INTEGER,
    o_entry_d DATETIME,
    o_carrier_id INTEGER,
    o_ol_cnt INTEGER,
    o_all_local INTEGER,
    PRIMARY KEY (o_w_id, o_d_id, o_id),
    FOREIGN KEY (o_w_id) REFERENCES warehouse(w_id)
);

-- Create new_order table
CREATE TABLE new_order (
    no_o_id INTEGER,
    no_d_id INTEGER,
    no_w_id INTEGER,
    PRIMARY KEY (no_w_id, no_d_id, no_o_id),
    FOREIGN KEY (no_w_id) REFERENCES warehouse(w_id)
);

-- Create order_line table
CREATE TABLE order_line (
    ol_o_id INTEGER,
    ol_d_id INTEGER,
    ol_w_id INTEGER,
    ol_number INTEGER,
    ol_i_id INTEGER,
    ol_supply_w_id INTEGER,
    ol_delivery_d DATETIME,
    ol_quantity INTEGER,
    ol_amount DECIMAL(6,2),
    ol_dist_info CHAR(24),
    PRIMARY KEY (ol_w_id, ol_d_id, ol_o_id, ol_number),
    FOREIGN KEY (ol_w_id) REFERENCES warehouse(w_id)
);

-- Secondary indexes.
--
-- These nine were missing from this file entirely, while
-- create_tpcc_schema_postgres.sql and create_tpcc_schema_sqlserver.sql each
-- declared the same nine. The consequence was not a slow MySQL: it was that
-- MySQL's *indexed* TPC-C configuration would have been byte-identical to its
-- non-indexed one, so the two campaigns would have produced two sets of the
-- same numbers and the indexed-versus-non-indexed comparison for MySQL TPC-C
-- would have been an artefact rather than a result.
--
-- Same names, same tables, same column orders as the other two vendors, so
-- "indexed" denotes one physical design across all three - the rule TPC-H
-- already follows with its fifteen.
--
-- Two things had to change here before that rule actually held on MySQL.
--
-- The nine were declared twice - once inline in the CREATE TABLE statements
-- and once in this block. MySQL created the inline copies, so this block then
-- failed at its second statement with "Duplicate key name 'idx_customer_wd'"
-- and every statement after it was abandoned. The end state happened to be
-- correct, which is the worst version of this: the script reports an error,
-- leaves a usable database, and gives no way to tell those two facts apart.
-- The inline copies are gone; these nine statements are now the only place a
-- TPC-C index is created, as on the other vendors.
--
-- And the stock table's foreign key to item was removed. InnoDB requires an
-- index on a foreign key's child column and refuses to drop the last one, so
-- `manage_indexes.py --benchmark tpcc --action drop` dropped eight indexes and
-- failed on idx_stock_i_id, leaving the database in neither configuration.
-- PostgreSQL reaches 0/9 because it has no such rule. Keeping the constraint
-- would have meant "non-indexed" denoting one physical design on PostgreSQL
-- and a different one on MySQL, which is the failure this comment block was
-- written to prevent, one level further down.
CREATE INDEX idx_district_w_id ON district(d_w_id);
CREATE INDEX idx_customer_wd ON customer(c_w_id, c_d_id);
CREATE INDEX idx_customer_wdl ON customer(c_w_id, c_d_id, c_last);
CREATE INDEX idx_history_customer ON history(h_c_w_id, h_c_d_id, h_c_id);
CREATE INDEX idx_stock_w_id ON stock(s_w_id);
CREATE INDEX idx_stock_i_id ON stock(s_i_id);
CREATE INDEX idx_order_customer ON `order`(o_w_id, o_d_id, o_c_id);
CREATE INDEX idx_neworder_wd ON new_order(no_w_id, no_d_id);
CREATE INDEX idx_orderline_order ON order_line(ol_w_id, ol_d_id, ol_o_id);
