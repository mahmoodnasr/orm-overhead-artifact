"""
TPC-H Query 8: National Market Share Query - Oracle Version
"""

from django.db.models import Sum, F, Q, Case, When, DecimalField
from django.db.models.functions import ExtractYear
from datetime import date
from tpch_paramsets import resolve as _paramset


def run_query_orm(using="default", params=None):
    """Execute TPC-H Q8 via Django ORM"""
    P = _paramset(8, params)
    from django_app.models import LineItem, Part

    start_date = date(1995, 1, 1)
    end_date = date(1996, 12, 31)

    results = (
        LineItem.objects.using(using)
        .select_related(
            "partkey", "suppkey__nationkey", "orderkey__custkey__nationkey__regionkey"
        )
        .filter(
            partkey__type=P["type"],
            orderkey__custkey__nationkey__regionkey__name=P["region"],
            orderkey__orderdate__range=(start_date, end_date),
        )
        .annotate(
            o_year=ExtractYear("orderkey__orderdate"),
            volume=F("extendedprice") * (1 - F("discount")),
            brazil_volume=Case(
                When(
                    suppkey__nationkey__name=P["nation"],
                    then=F("extendedprice") * (1 - F("discount")),
                ),
                default=0,
                output_field=DecimalField(),
            ),
        )
        .values("o_year")
        .annotate(total_volume=Sum("volume"), brazil_total=Sum("brazil_volume"))
        .annotate(mkt_share=F("brazil_total") / F("total_volume"))
        .order_by("o_year")
        # Was: no projection, so each row carried every annotation - o_year,
        # total_volume, brazil_total and mkt_share, four values where this
        # module's own run_query_sql and SQLAlchemy's ORM both return two.
        # scripts/validate_queries.py compares whole rows, so a four-tuple could
        # never equal a two-tuple and MATCH and ORM=SQL were DIFF whatever the
        # market-share numbers were. The recorded verdict was right; the usual
        # reading of it - that Django computed a different answer - was not
        # established. q08.py, the default, has carried this line all along.
        # Defect C26.
        .values("o_year", "mkt_share")
    )

    return list(results)


def run_query_sql(connection, params=None):
    """Execute TPC-H Q8 via direct SQL - Oracle compatible"""
    P = _paramset(8, params)
    sql = f"""
    SELECT
        o_year,
        SUM(CASE WHEN nation = '{P["nation"]}' THEN volume ELSE 0 END) / SUM(volume) as mkt_share
    FROM (
        SELECT
            EXTRACT(YEAR FROM o_orderdate) as o_year,
            l_extendedprice * (1 - l_discount) as volume,
            n2.n_name as nation
        FROM part, supplier, lineitem, orders, customer, nation n1, nation n2, region
        WHERE p_partkey = l_partkey
        AND s_suppkey = l_suppkey
        AND l_orderkey = o_orderkey
        AND o_custkey = c_custkey
        AND c_nationkey = n1.n_nationkey
        AND n1.n_regionkey = r_regionkey
        AND r_name = '{P["region"]}'
        AND s_nationkey = n2.n_nationkey
        AND o_orderdate BETWEEN TO_DATE('1995-01-01', 'YYYY-MM-DD') AND TO_DATE('1996-12-31', 'YYYY-MM-DD')
        AND p_type = '{P["type"]}'
    ) all_nations
    GROUP BY o_year
    ORDER BY o_year
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return results
