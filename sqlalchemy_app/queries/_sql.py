"""Hand-written TPC-H SQL baselines with the specification's parameters.

One statement per query, with the substitution parameters from the TPC-H
validation set. The original implementation bound every query that took a date
range to the same 1995-01-01 / 1997-01-01 window, so Q4, Q5, Q10, Q12, Q14, Q15
and Q20 all ran against the wrong selectivity. The correct windows are inlined
below, per query.

`sql_for(qnum, vendor)` returns the statement adapted to the dialect. Only the
row-limiting clause and date-literal syntax differ between vendors.

One substitution parameter is not a constant. Q11's FRACTION is defined by the
specification as 0.0001/SF, so it has to shrink as the database grows. Held at
0.0001 it filters out every group above SF1 and Q11 returns an empty result:
at SF10 the German stock total is 810,291,376,524 and the threshold it produces
is 81,029,137, which no single part reaches. The query still aggregates and
sorts, so it still takes time and still looks like a successful measurement,
which is what makes the error easy to miss. Set TPCH_SF to the scale factor in
use.
"""

import re

from tpch_params import SCALE_FACTOR, Q11_FRACTION  # noqa: F401
import tpch_paramsets


def _placeholders(qnum, p):
    """The {P_*} substitution map for one query and one parameter set.

    The end of a date range is *derived* here rather than stored in the
    parameter set, because the specification defines each range by its start
    and a fixed width - one month for Q14, three for Q04/Q10/Q15, a year for
    Q05/Q06/Q12/Q20. Deriving it means a parameter set cannot carry a start and
    an end that disagree, which is the shape defect C9 took when four Oracle
    modules carried Q04's window instead of their own.
    """
    # expand() is idempotent, so this is safe whether the caller passed a raw
    # set or one params() already expanded. It is also what keeps the date
    # widths and the discount bounds defined in exactly one place.
    p = tpch_paramsets.resolve(qnum, p)
    d = p.get("date")
    m = {}
    if qnum == 1:
        m["P_DATE"] = d
    elif qnum == 2:
        m.update(P_SIZE=p["size"], P_TYPE=p["type_suffix"], P_REGION=p["region"])
    elif qnum == 3:
        m.update(P_SEGMENT=p["segment"], P_DATE=d)
    elif qnum == 4:
        m.update(P_DATE=d, P_DATE_END=p["date_end"])
    elif qnum == 5:
        m.update(P_REGION=p["region"], P_DATE=d, P_DATE_END=p["date_end"])
    elif qnum == 6:
        # The specification writes the predicate as DISCOUNT +/- 0.01. Rounding
        # to two places keeps 0.06 - 0.01 from rendering as 0.049999999999999996
        # and changing the emitted SQL for a parameter that did not change.
        m.update(
            P_DATE=d,
            P_DATE_END=p["date_end"],
            P_DISC_LO="%.2f" % p["disc_lo"],
            P_DISC_HI="%.2f" % p["disc_hi"],
            P_QUANTITY=p["quantity"],
        )
    elif qnum == 7:
        m.update(P_NATION1=p["nation1"], P_NATION2=p["nation2"])
    elif qnum == 8:
        m.update(P_NATION=p["nation"], P_REGION=p["region"], P_TYPE=p["type"])
    elif qnum == 9:
        m["P_COLOR"] = p["color"]
    elif qnum == 10:
        m.update(P_DATE=d, P_DATE_END=p["date_end"])
    elif qnum == 11:
        m["P_NATION"] = p["nation"]
    elif qnum == 12:
        m.update(
            P_MODE1=p["shipmode1"],
            P_MODE2=p["shipmode2"],
            P_DATE=d,
            P_DATE_END=p["date_end"],
        )
    elif qnum == 13:
        m.update(P_WORD1=p["word1"], P_WORD2=p["word2"])
    elif qnum == 14:
        m.update(P_DATE=d, P_DATE_END=p["date_end"])
    elif qnum == 15:
        m.update(P_DATE=d, P_DATE_END=p["date_end"])
    elif qnum == 16:
        m.update(P_BRAND=p["brand"], P_TYPE=p["type"], P_SIZES=p["sizes_sql"])
    elif qnum == 17:
        m.update(P_BRAND=p["brand"], P_CONTAINER=p["container"])
    elif qnum == 18:
        m["P_QUANTITY"] = p["quantity"]
    elif qnum == 19:
        m.update(
            P_BRAND1=p["brand1"],
            P_BRAND2=p["brand2"],
            P_BRAND3=p["brand3"],
            P_QTY1=p["quantity1"],
            P_QTY2=p["quantity2"],
            P_QTY3=p["quantity3"],
        )
    elif qnum == 20:
        m.update(
            P_COLOR=p["color"], P_NATION=p["nation"], P_DATE=d, P_DATE_END=p["date_end"]
        )
    elif qnum == 21:
        m["P_NATION"] = p["nation"]
    elif qnum == 22:
        m["P_CODES"] = p["codes_sql"]
    return m


# ANSI form; {LIMIT_n} placeholders are replaced per dialect.
_Q = {}

_Q[1] = """
SELECT l_returnflag, l_linestatus,
       SUM(l_quantity) AS sum_qty,
       SUM(l_extendedprice) AS sum_base_price,
       SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
       SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
       AVG(l_quantity) AS avg_qty,
       AVG(l_extendedprice) AS avg_price,
       AVG(l_discount) AS avg_disc,
       COUNT(*) AS count_order
FROM lineitem
WHERE l_shipdate <= DATE '{P_DATE}'
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
"""

_Q[2] = """
SELECT s_acctbal, s_name, n_name, p_partkey, p_mfgr, s_address, s_phone, s_comment
FROM part, supplier, partsupp, nation, region
WHERE p_partkey = ps_partkey
  AND s_suppkey = ps_suppkey
  AND p_size = {P_SIZE}
  AND p_type LIKE '%{P_TYPE}'
  AND s_nationkey = n_nationkey
  AND n_regionkey = r_regionkey
  AND r_name = '{P_REGION}'
  AND ps_supplycost = (
        SELECT MIN(ps_supplycost)
        FROM partsupp, supplier, nation, region
        WHERE p_partkey = ps_partkey
          AND s_suppkey = ps_suppkey
          AND s_nationkey = n_nationkey
          AND n_regionkey = r_regionkey
          AND r_name = '{P_REGION}')
ORDER BY s_acctbal DESC, n_name, s_name, p_partkey
{LIMIT_100}
"""

_Q[3] = """
SELECT l_orderkey,
       SUM(l_extendedprice * (1 - l_discount)) AS revenue,
       o_orderdate, o_shippriority
FROM customer, orders, lineitem
WHERE c_mktsegment = '{P_SEGMENT}'
  AND c_custkey = o_custkey
  AND l_orderkey = o_orderkey
  AND o_orderdate < DATE '{P_DATE}'
  AND l_shipdate > DATE '{P_DATE}'
GROUP BY l_orderkey, o_orderdate, o_shippriority
ORDER BY revenue DESC, o_orderdate
{LIMIT_10}
"""

_Q[4] = """
SELECT o_orderpriority, COUNT(*) AS order_count
FROM orders
WHERE o_orderdate >= DATE '{P_DATE}'
  AND o_orderdate < DATE '{P_DATE_END}'
  AND EXISTS (SELECT 1 FROM lineitem
              WHERE l_orderkey = o_orderkey
                AND l_commitdate < l_receiptdate)
GROUP BY o_orderpriority
ORDER BY o_orderpriority
"""

_Q[5] = """
SELECT n_name, SUM(l_extendedprice * (1 - l_discount)) AS revenue
FROM customer, orders, lineitem, supplier, nation, region
WHERE c_custkey = o_custkey
  AND l_orderkey = o_orderkey
  AND l_suppkey = s_suppkey
  AND c_nationkey = s_nationkey
  AND s_nationkey = n_nationkey
  AND n_regionkey = r_regionkey
  AND r_name = '{P_REGION}'
  AND o_orderdate >= DATE '{P_DATE}'
  AND o_orderdate < DATE '{P_DATE_END}'
GROUP BY n_name
ORDER BY revenue DESC
"""

_Q[6] = """
SELECT SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_shipdate >= DATE '{P_DATE}'
  AND l_shipdate < DATE '{P_DATE_END}'
  AND l_discount BETWEEN {P_DISC_LO} AND {P_DISC_HI}
  AND l_quantity < {P_QUANTITY}
"""

_Q[7] = """
SELECT supp_nation, cust_nation, l_year, SUM(volume) AS revenue
FROM (SELECT n1.n_name AS supp_nation, n2.n_name AS cust_nation,
             EXTRACT(YEAR FROM l_shipdate) AS l_year,
             l_extendedprice * (1 - l_discount) AS volume
      FROM supplier, lineitem, orders, customer, nation n1, nation n2
      WHERE s_suppkey = l_suppkey
        AND o_orderkey = l_orderkey
        AND c_custkey = o_custkey
        AND s_nationkey = n1.n_nationkey
        AND c_nationkey = n2.n_nationkey
        AND ((n1.n_name = '{P_NATION1}' AND n2.n_name = '{P_NATION2}')
          OR (n1.n_name = '{P_NATION2}' AND n2.n_name = '{P_NATION1}'))
        AND l_shipdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'
     ) AS shipping
GROUP BY supp_nation, cust_nation, l_year
ORDER BY supp_nation, cust_nation, l_year
"""

_Q[8] = """
SELECT o_year,
       SUM(CASE WHEN nation = '{P_NATION}' THEN volume ELSE 0 END) / SUM(volume) AS mkt_share
FROM (SELECT EXTRACT(YEAR FROM o_orderdate) AS o_year,
             l_extendedprice * (1 - l_discount) AS volume,
             n2.n_name AS nation
      FROM part, supplier, lineitem, orders, customer, nation n1, nation n2, region
      WHERE p_partkey = l_partkey
        AND s_suppkey = l_suppkey
        AND l_orderkey = o_orderkey
        AND o_custkey = c_custkey
        AND c_nationkey = n1.n_nationkey
        AND n1.n_regionkey = r_regionkey
        AND r_name = '{P_REGION}'
        AND s_nationkey = n2.n_nationkey
        AND o_orderdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'
        AND p_type = '{P_TYPE}'
     ) AS all_nations
GROUP BY o_year
ORDER BY o_year
"""

_Q[9] = """
SELECT nation, o_year, SUM(amount) AS sum_profit
FROM (SELECT n_name AS nation,
             EXTRACT(YEAR FROM o_orderdate) AS o_year,
             l_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity AS amount
      FROM part, supplier, lineitem, partsupp, orders, nation
      WHERE s_suppkey = l_suppkey
        AND ps_suppkey = l_suppkey
        AND ps_partkey = l_partkey
        AND p_partkey = l_partkey
        AND o_orderkey = l_orderkey
        AND s_nationkey = n_nationkey
        AND p_name LIKE '%{P_COLOR}%'
     ) AS profit
GROUP BY nation, o_year
ORDER BY nation, o_year DESC
"""

_Q[10] = """
SELECT c_custkey, c_name,
       SUM(l_extendedprice * (1 - l_discount)) AS revenue,
       c_acctbal, n_name, c_address, c_phone, c_comment
FROM customer, orders, lineitem, nation
WHERE c_custkey = o_custkey
  AND l_orderkey = o_orderkey
  AND o_orderdate >= DATE '{P_DATE}'
  AND o_orderdate < DATE '{P_DATE_END}'
  AND l_returnflag = 'R'
  AND c_nationkey = n_nationkey
GROUP BY c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment
ORDER BY revenue DESC
{LIMIT_20}
"""

_Q[11] = """
SELECT ps_partkey, SUM(ps_supplycost * ps_availqty) AS value
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey
  AND s_nationkey = n_nationkey
  AND n_name = '{P_NATION}'
GROUP BY ps_partkey
HAVING SUM(ps_supplycost * ps_availqty) > (
    SELECT SUM(ps_supplycost * ps_availqty) * {Q11_FRACTION}
    FROM partsupp, supplier, nation
    WHERE ps_suppkey = s_suppkey
      AND s_nationkey = n_nationkey
      AND n_name = '{P_NATION}')
ORDER BY value DESC
"""

_Q[12] = """
SELECT l_shipmode,
       SUM(CASE WHEN o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH'
                THEN 1 ELSE 0 END) AS high_line_count,
       SUM(CASE WHEN o_orderpriority <> '1-URGENT' AND o_orderpriority <> '2-HIGH'
                THEN 1 ELSE 0 END) AS low_line_count
FROM orders, lineitem
WHERE o_orderkey = l_orderkey
  AND l_shipmode IN ('{P_MODE1}', '{P_MODE2}')
  AND l_commitdate < l_receiptdate
  AND l_shipdate < l_commitdate
  AND l_receiptdate >= DATE '{P_DATE}'
  AND l_receiptdate < DATE '{P_DATE_END}'
GROUP BY l_shipmode
ORDER BY l_shipmode
"""

_Q[13] = """
SELECT c_count, COUNT(*) AS custdist
FROM (SELECT c_custkey, COUNT(o_orderkey) AS c_count
      FROM customer LEFT OUTER JOIN orders
        ON c_custkey = o_custkey
       AND o_comment NOT LIKE '%{P_WORD1}%{P_WORD2}%'
      GROUP BY c_custkey) AS c_orders
GROUP BY c_count
ORDER BY custdist DESC, c_count DESC
"""

_Q[14] = """
SELECT 100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%'
                         THEN l_extendedprice * (1 - l_discount)
                         ELSE 0 END) /
       SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
FROM lineitem, part
WHERE l_partkey = p_partkey
  AND l_shipdate >= DATE '{P_DATE}'
  AND l_shipdate < DATE '{P_DATE_END}'
"""

_Q[15] = """
SELECT s_suppkey, s_name, s_address, s_phone, total_revenue
FROM supplier,
     (SELECT l_suppkey AS supplier_no,
             SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
      FROM lineitem
      WHERE l_shipdate >= DATE '{P_DATE}'
        AND l_shipdate < DATE '{P_DATE_END}'
      GROUP BY l_suppkey) AS revenue0
WHERE s_suppkey = supplier_no
  AND total_revenue = (SELECT MAX(total_revenue)
                       FROM (SELECT l_suppkey AS supplier_no,
                                    SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
                             FROM lineitem
                             WHERE l_shipdate >= DATE '{P_DATE}'
                               AND l_shipdate < DATE '{P_DATE_END}'
                             GROUP BY l_suppkey) AS r2)
ORDER BY s_suppkey
"""

_Q[16] = """
SELECT p_brand, p_type, p_size, COUNT(DISTINCT ps_suppkey) AS supplier_cnt
FROM partsupp, part
WHERE p_partkey = ps_partkey
  AND p_brand <> '{P_BRAND}'
  AND p_type NOT LIKE '{P_TYPE}%'
  AND p_size IN ({P_SIZES})
  AND ps_suppkey NOT IN (SELECT s_suppkey FROM supplier
                         WHERE s_comment LIKE '%Customer%Complaints%')
GROUP BY p_brand, p_type, p_size
ORDER BY supplier_cnt DESC, p_brand, p_type, p_size
"""

_Q[17] = """
SELECT SUM(l_extendedprice) / 7.0 AS avg_yearly
FROM lineitem, part
WHERE p_partkey = l_partkey
  AND p_brand = '{P_BRAND}'
  AND p_container = '{P_CONTAINER}'
  AND l_quantity < (SELECT 0.2 * AVG(l_quantity) FROM lineitem
                    WHERE l_partkey = p_partkey)
"""

_Q[18] = """
SELECT c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice, SUM(l_quantity) AS total_qty
FROM customer, orders, lineitem
WHERE o_orderkey IN (SELECT l_orderkey FROM lineitem
                     GROUP BY l_orderkey HAVING SUM(l_quantity) > {P_QUANTITY})
  AND c_custkey = o_custkey
  AND o_orderkey = l_orderkey
GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
ORDER BY o_totalprice DESC, o_orderdate
{LIMIT_100}
"""

_Q[19] = """
SELECT SUM(l_extendedprice * (1 - l_discount)) AS revenue
FROM lineitem, part
WHERE (p_partkey = l_partkey AND p_brand = '{P_BRAND1}'
       AND p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
       AND l_quantity >= {P_QTY1} AND l_quantity <= {P_QTY1} + 10
       AND p_size BETWEEN 1 AND 5
       AND l_shipmode IN ('AIR', 'AIR REG')
       AND l_shipinstruct = 'DELIVER IN PERSON')
   OR (p_partkey = l_partkey AND p_brand = '{P_BRAND2}'
       AND p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
       AND l_quantity >= {P_QTY2} AND l_quantity <= {P_QTY2} + 10
       AND p_size BETWEEN 1 AND 10
       AND l_shipmode IN ('AIR', 'AIR REG')
       AND l_shipinstruct = 'DELIVER IN PERSON')
   OR (p_partkey = l_partkey AND p_brand = '{P_BRAND3}'
       AND p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
       AND l_quantity >= {P_QTY3} AND l_quantity <= {P_QTY3} + 10
       AND p_size BETWEEN 1 AND 15
       AND l_shipmode IN ('AIR', 'AIR REG')
       AND l_shipinstruct = 'DELIVER IN PERSON')
"""

_Q[20] = """
SELECT s_name, s_address
FROM supplier, nation
WHERE s_suppkey IN (
        SELECT ps_suppkey FROM partsupp
        WHERE ps_partkey IN (SELECT p_partkey FROM part WHERE p_name LIKE '{P_COLOR}%')
          AND ps_availqty > (SELECT 0.5 * SUM(l_quantity) FROM lineitem
                             WHERE l_partkey = ps_partkey
                               AND l_suppkey = ps_suppkey
                               AND l_shipdate >= DATE '{P_DATE}'
                               AND l_shipdate < DATE '{P_DATE_END}'))
  AND s_nationkey = n_nationkey
  AND n_name = '{P_NATION}'
ORDER BY s_name
"""

_Q[21] = """
SELECT s_name, COUNT(*) AS numwait
FROM supplier, lineitem l1, orders, nation
WHERE s_suppkey = l1.l_suppkey
  AND o_orderkey = l1.l_orderkey
  AND o_orderstatus = 'F'
  AND l1.l_receiptdate > l1.l_commitdate
  AND EXISTS (SELECT 1 FROM lineitem l2
              WHERE l2.l_orderkey = l1.l_orderkey
                AND l2.l_suppkey <> l1.l_suppkey)
  AND NOT EXISTS (SELECT 1 FROM lineitem l3
                  WHERE l3.l_orderkey = l1.l_orderkey
                    AND l3.l_suppkey <> l1.l_suppkey
                    AND l3.l_receiptdate > l3.l_commitdate)
  AND s_nationkey = n_nationkey
  AND n_name = '{P_NATION}'
GROUP BY s_name
ORDER BY numwait DESC, s_name
{LIMIT_100}
"""

_Q[22] = """
SELECT cntrycode, COUNT(*) AS numcust, SUM(c_acctbal) AS totacctbal
FROM (SELECT {SUBSTR2} AS cntrycode, c_acctbal
      FROM customer
      WHERE {SUBSTR2} IN ({P_CODES})
        AND c_acctbal > (SELECT AVG(c_acctbal) FROM customer
                         WHERE c_acctbal > 0.00
                           AND {SUBSTR2} IN ({P_CODES}))
        AND NOT EXISTS (SELECT 1 FROM orders WHERE o_custkey = c_custkey)
     ) AS custsale
GROUP BY cntrycode
ORDER BY cntrycode
"""


def sql_for(qnum: int, vendor: str, params=None) -> str:
    """Return the TPC-H statement for `qnum`, adapted to `vendor`.

    `params` is one substitution-parameter set from tpch_paramsets; omitting it
    uses set 0, the validation instance, which is what every caller written
    before the eight-block protocol existed expects. With set 0 this function
    returns exactly the statement it returned before parameterisation -
    asserted, not assumed, by tests/test_paramsets.py.

    The parameters are interpolated as *literals*, not bound. That is
    deliberate and it is a measurement decision: the hand-written baseline has
    always emitted literals, the ORM path necessarily emits binds, and the
    difference between the two - generic versus specific plans, parameter
    sniffing - is part of what the study compares. Switching the baseline to
    binds here would silently change every prior comparison.
    """
    # resolve() accepts None (set 0), an integer block index, or a set that is
    # already built. It has to be resolve() and not params(): the validator and
    # the block runner both pass a bare block index, and dict(0) raises
    # "'int' object is not iterable" - which is how this was caught, on all 22
    # queries at once, the first time the validator ran after the refactor.
    params = tpch_paramsets.resolve(qnum, params)
    sql = _Q[qnum]
    for key, val in _placeholders(qnum, params).items():
        sql = sql.replace("{%s}" % key, str(val))

    if vendor in ("mysql",):
        for n in (10, 20, 100):
            sql = sql.replace("{LIMIT_%d}" % n, "LIMIT %d" % n)
        sql = sql.replace("DATE '", "'")
        substr = "SUBSTRING(c_phone, 1, 2)"
    elif vendor in ("mssql", "microsoft", "sqlserver"):
        for n in (10, 20, 100):
            sql = sql.replace(
                "{LIMIT_%d}" % n, "OFFSET 0 ROWS FETCH NEXT %d ROWS ONLY" % n
            )
        sql = sql.replace("DATE '", "'")
        # Was: .replace("EXTRACT(YEAR FROM ", "YEAR((").replace("))", "))").
        # The first replacement opened two parentheses and closed one, so
        # EXTRACT(YEAR FROM o_orderdate) became YEAR((o_orderdate) and every
        # statement using it was unbalanced; the second replacement substituted
        # "))" for "))" and did nothing at all. Q07, Q08 and Q09 are the three
        # queries that extract a year, and all three were invalid SQL Server
        # syntax that would fail on the first execution. Match the whole
        # construct instead, the same way the Oracle branch below does.
        sql = re.sub(r"EXTRACT\(YEAR FROM ([^)]+)\)", r"YEAR(\1)", sql)
        substr = "SUBSTRING(c_phone, 1, 2)"
    elif vendor == "oracle":
        for n in (10, 20, 100):
            sql = sql.replace("{LIMIT_%d}" % n, "FETCH FIRST %d ROWS ONLY" % n)
        sql = re.sub(
            r"DATE '(\d{4})-(\d{2})-(\d{2})'", r"TO_DATE('\1-\2-\3', 'YYYY-MM-DD')", sql
        )
        # Oracle accepts AS only before a *column* alias. A derived table or a
        # correlation name written `) AS x` raises ORA-03048. The previous
        # version listed the aliases it knew about one by one and silently
        # missed the ones in Q13 and Q22; match the construct instead.
        sql = re.sub(r"\)\s*\n?\s*AS\s+(\w+)", r") \1", sql)
        substr = "SUBSTR(c_phone, 1, 2)"
    else:  # postgresql
        for n in (10, 20, 100):
            sql = sql.replace("{LIMIT_%d}" % n, "LIMIT %d" % n)
        substr = "SUBSTRING(c_phone FROM 1 FOR 2)"

    return (
        sql.replace("{SUBSTR2}", substr)
        .replace("{Q11_FRACTION}", "%.12f" % Q11_FRACTION)
        .strip()
    )
