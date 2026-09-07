-- TPC-C schema for Oracle.
--
-- Extracted from scripts/1-setup/setup_tpcc_oracle_data.py, which embedded it in
-- Python and could not be applied on its own, with one change: every CHAR column
-- is VARCHAR2.
--
-- That change is defect C7. Oracle blank-pads a comparison only when *both*
-- operands are CHAR. A bind variable is VARCHAR2, so an ORM predicate against a
-- CHAR column matches nothing while the same predicate written as a literal
-- matches - silently, with the two frameworks agreeing perfectly on the empty
-- result. schema_oracle.sql already makes this change for TPC-H; the TPC-C
-- schema had not.
--
-- TPC-C lives in its own Oracle user because TPC-H is resident in TPCH and both
-- define a CUSTOMER table. Under Oracle Free's 12 GB cap the two schemas
-- together are about 6.5 GB, so they coexist.
--
-- ORDER is a reserved word and is quoted throughout, as in the PostgreSQL,
-- MySQL and SQL Server schemas.

CREATE TABLE WAREHOUSE (
    W_ID NUMBER(10) PRIMARY KEY,
    W_NAME VARCHAR2(10),
    W_STREET_1 VARCHAR2(20),
    W_STREET_2 VARCHAR2(20),
    W_CITY VARCHAR2(20),
    W_STATE VARCHAR2(2),
    W_ZIP VARCHAR2(9),
    W_TAX NUMBER(4,4),
    W_YTD NUMBER(12,2)
    );

CREATE TABLE DISTRICT (
    D_ID NUMBER(10),
    D_W_ID NUMBER(10),
    D_NAME VARCHAR2(10),
    D_STREET_1 VARCHAR2(20),
    D_STREET_2 VARCHAR2(20),
    D_CITY VARCHAR2(20),
    D_STATE VARCHAR2(2),
    D_ZIP VARCHAR2(9),
    D_TAX NUMBER(4,4),
    D_YTD NUMBER(12,2),
    D_NEXT_O_ID NUMBER(10),
    PRIMARY KEY (D_W_ID, D_ID),
    FOREIGN KEY (D_W_ID) REFERENCES WAREHOUSE(W_ID)
    );

CREATE TABLE CUSTOMER (
    C_ID NUMBER(10),
    C_D_ID NUMBER(10),
    C_W_ID NUMBER(10),
    C_FIRST VARCHAR2(16),
    C_MIDDLE VARCHAR2(2),
    C_LAST VARCHAR2(16),
    C_STREET_1 VARCHAR2(20),
    C_STREET_2 VARCHAR2(20),
    C_CITY VARCHAR2(20),
    C_STATE VARCHAR2(2),
    C_ZIP VARCHAR2(9),
    C_PHONE VARCHAR2(16),
    C_SINCE TIMESTAMP,
    C_CREDIT VARCHAR2(2),
    C_CREDIT_LIM NUMBER(12,2),
    C_DISCOUNT NUMBER(4,4),
    C_BALANCE NUMBER(12,2),
    C_YTD_PAYMENT NUMBER(12,2),
    C_PAYMENT_CNT NUMBER(10),
    C_DELIVERY_CNT NUMBER(10),
    C_DATA VARCHAR2(500),
    PRIMARY KEY (C_W_ID, C_D_ID, C_ID),
    FOREIGN KEY (C_W_ID) REFERENCES WAREHOUSE(W_ID)
    );

CREATE TABLE HISTORY (
    H_C_ID NUMBER(10),
    H_C_D_ID NUMBER(10),
    H_C_W_ID NUMBER(10),
    H_D_ID NUMBER(10),
    H_W_ID NUMBER(10),
    H_DATE TIMESTAMP,
    H_AMOUNT NUMBER(6,2),
    H_DATA VARCHAR2(24)
    );

CREATE TABLE ITEM (
    I_ID NUMBER(10) PRIMARY KEY,
    I_IM_ID NUMBER(10),
    I_NAME VARCHAR2(24),
    I_PRICE NUMBER(5,2),
    I_DATA VARCHAR2(50)
    );

CREATE TABLE STOCK (
    S_I_ID NUMBER(10),
    S_W_ID NUMBER(10),
    S_QUANTITY NUMBER(10),
    S_DIST_01 VARCHAR2(24),
    S_DIST_02 VARCHAR2(24),
    S_DIST_03 VARCHAR2(24),
    S_DIST_04 VARCHAR2(24),
    S_DIST_05 VARCHAR2(24),
    S_DIST_06 VARCHAR2(24),
    S_DIST_07 VARCHAR2(24),
    S_DIST_08 VARCHAR2(24),
    S_DIST_09 VARCHAR2(24),
    S_DIST_10 VARCHAR2(24),
    S_YTD NUMBER(10),
    S_ORDER_CNT NUMBER(10),
    S_REMOTE_CNT NUMBER(10),
    S_DATA VARCHAR2(50),
    PRIMARY KEY (S_W_ID, S_I_ID),
    FOREIGN KEY (S_W_ID) REFERENCES WAREHOUSE(W_ID),
    FOREIGN KEY (S_I_ID) REFERENCES ITEM(I_ID)
    );

CREATE TABLE "ORDER" (
    O_ID NUMBER(10),
    O_D_ID NUMBER(10),
    O_W_ID NUMBER(10),
    O_C_ID NUMBER(10),
    O_ENTRY_D TIMESTAMP,
    O_CARRIER_ID NUMBER(10),
    O_OL_CNT NUMBER(10),
    O_ALL_LOCAL NUMBER(10),
    PRIMARY KEY (O_W_ID, O_D_ID, O_ID),
    FOREIGN KEY (O_W_ID) REFERENCES WAREHOUSE(W_ID)
    );

CREATE TABLE NEW_ORDER (
    NO_O_ID NUMBER(10),
    NO_D_ID NUMBER(10),
    NO_W_ID NUMBER(10),
    PRIMARY KEY (NO_W_ID, NO_D_ID, NO_O_ID),
    FOREIGN KEY (NO_W_ID) REFERENCES WAREHOUSE(W_ID)
    );

CREATE TABLE ORDER_LINE (
    OL_O_ID NUMBER(10),
    OL_D_ID NUMBER(10),
    OL_W_ID NUMBER(10),
    OL_NUMBER NUMBER(10),
    OL_I_ID NUMBER(10),
    OL_SUPPLY_W_ID NUMBER(10),
    OL_DELIVERY_D TIMESTAMP,
    OL_QUANTITY NUMBER(10),
    OL_AMOUNT NUMBER(6,2),
    OL_DIST_INFO VARCHAR2(24),
    PRIMARY KEY (OL_W_ID, OL_D_ID, OL_O_ID, OL_NUMBER),
    FOREIGN KEY (OL_W_ID) REFERENCES WAREHOUSE(W_ID)
    );

-- Secondary indexes.
--
-- The schema embedded in setup_tpcc_oracle_data.py declared none, exactly as
-- create_tpcc_schema_mysql.sql did. The consequence is not a slow Oracle: it is
-- that Oracle's *indexed* and *non-indexed* TPC-C configurations would have been
-- identical, so the two campaigns would produce two sets of the same numbers and
-- the comparison would be an artefact rather than a result.
--
-- Same nine, same tables, same column orders as PostgreSQL, MySQL and SQL
-- Server, so "indexed" denotes one physical design across all four.
CREATE INDEX idx_district_w_id ON district(d_w_id);
CREATE INDEX idx_customer_wd ON customer(c_w_id, c_d_id);
CREATE INDEX idx_customer_wdl ON customer(c_w_id, c_d_id, c_last);
CREATE INDEX idx_history_customer ON history(h_c_w_id, h_c_d_id, h_c_id);
CREATE INDEX idx_stock_w_id ON stock(s_w_id);
CREATE INDEX idx_stock_i_id ON stock(s_i_id);
CREATE INDEX idx_order_customer ON "ORDER"(o_w_id, o_d_id, o_c_id);
CREATE INDEX idx_neworder_wd ON new_order(no_w_id, no_d_id);
CREATE INDEX idx_orderline_order ON order_line(ol_w_id, ol_d_id, ol_o_id);

-- Oracle quotes identifiers case-sensitively, and the two frameworks disagree
-- about the case of this one table. ORDER is reserved in every dialect here, so
-- both must quote it, and quoting is what fixes the case:
--
--   Django   db_table='order'   -> quote_name uppercases  -> "ORDER"
--   SQLAlchemy __tablename__='order' -> quoted as given   -> "order"
--
-- One table cannot answer to both. A synonym can, and costs nothing per row:
-- Oracle resolves it once at parse time and DML through it reaches the table
-- directly. The alternative was a per-vendor table name in one or both model
-- files, which would have put a dialect quirk into code shared by four systems.
-- Defect C28.
CREATE OR REPLACE SYNONYM "order" FOR "ORDER";
