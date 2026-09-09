"""
TPC-H Query 7: Volume Shipping Query - Oracle Version
"""

from django.db.models import Sum, F, Q, Value
from django.db.models.functions import ExtractYear
from datetime import date
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute TPC-H Q7 via Django ORM"""
    P = _paramset(7, params)
    from django_app.models import LineItem, Supplier, Nation

    start_date = date(1995, 1, 1)
    end_date = date(1996, 12, 31)

    results = (
        LineItem.objects.using(using)
        .select_related("suppkey__nationkey", "orderkey__custkey__nationkey")
        .filter(
            Q(
                suppkey__nationkey__name=P["nation1"],
                orderkey__custkey__nationkey__name=P["nation2"],
            )
            | Q(
                suppkey__nationkey__name=P["nation2"],
                orderkey__custkey__nationkey__name=P["nation1"],
            ),
            shipdate__range=(start_date, end_date),
        )
        .annotate(
            supp_nation=F("suppkey__nationkey__name"),
            cust_nation=F("orderkey__custkey__nationkey__name"),
            l_year=ExtractYear("shipdate"),
            volume=F("extendedprice") * (1 - F("discount")),
        )
        .values("supp_nation", "cust_nation", "l_year")
        .annotate(revenue=Sum("volume"))
        .order_by("supp_nation", "cust_nation", "l_year")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute TPC-H Q7 via direct SQL - Oracle compatible"""
    P = _paramset(7, params)
    sql = f"""
    SELECT
        supp_nation,
        cust_nation,
        l_year,
        SUM(volume) as revenue
    FROM (
        SELECT
            n1.n_name as supp_nation,
            n2.n_name as cust_nation,
            EXTRACT(YEAR FROM l_shipdate) as l_year,
            l_extendedprice * (1 - l_discount) as volume
        FROM supplier, lineitem, orders, customer, nation n1, nation n2
        WHERE s_suppkey = l_suppkey
        AND o_orderkey = l_orderkey
        AND c_custkey = o_custkey
        AND s_nationkey = n1.n_nationkey
        AND c_nationkey = n2.n_nationkey
        AND ((n1.n_name = '{P["nation1"]}' AND n2.n_name = '{P["nation2"]}')
          OR (n1.n_name = '{P["nation2"]}' AND n2.n_name = '{P["nation1"]}'))
        AND l_shipdate BETWEEN TO_DATE('1995-01-01', 'YYYY-MM-DD') AND TO_DATE('1996-12-31', 'YYYY-MM-DD')
    ) shipping
    GROUP BY supp_nation, cust_nation, l_year
    ORDER BY supp_nation, cust_nation, l_year
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results
