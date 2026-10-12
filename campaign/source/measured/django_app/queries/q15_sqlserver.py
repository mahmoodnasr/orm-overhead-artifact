"""
TPC-H Query 15 - SQL Server Version
This version uses SQL Server-specific syntax (CAST instead of TO_DATE, YEAR() instead of EXTRACT, etc.)
"""


from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Max
from ..models import Supplier, LineItem
from tpch_paramsets import resolve as _paramset


def run_query_orm(using='default', params=None):
    """Execute Q15 via Django ORM."""
    P = _paramset(15, params)
    
    # Calculate revenue for each supplier
    supplier_revenue = (
        LineItem.objects
        .using(using)
        .filter(
            shipdate__gte=P['date'],
            shipdate__lt=P['date_end']
        )
        .values('suppkey')
        .annotate(
            total_revenue=Sum(
                ExpressionWrapper(
                    F('extendedprice') * (1 - F('discount')),
                    # Scale 4, not the scale 2 the shared q15.py declares.
                    # l_extendedprice and l_discount are both DECIMAL(15,2), so
                    # extendedprice * (1 - discount) has scale 4 and the summed
                    # revenue really is 2194132.8166. Declaring scale 2 was
                    # always wrong; PostgreSQL simply never charged for it,
                    # because its backend overrides adapt_decimalfield_value to
                    # pass Decimals through untouched.
                    #
                    # mssql-django uses Django's default implementation, which
                    # quantises a bound Decimal to the declared decimal_places.
                    # So `max_revenue` came back from the database correct at
                    # 2194132.8166, and then went back in as the parameter
                    # 2194132.82, which equals no group's total. Django's Q15
                    # returned zero rows while the other three paths returned
                    # the one correct row. Defect C15.
                    output_field=DecimalField(max_digits=25, decimal_places=4)
                )
            )
        )
    )

    # Find max revenue
    max_revenue = supplier_revenue.aggregate(max_rev=Max('total_revenue'))['max_rev']
    
    # Get suppliers with max revenue
    top_suppliers = supplier_revenue.filter(total_revenue=max_revenue)
    
    results = (
        Supplier.objects
        .using(using)
        .filter(suppkey__in=[s['suppkey'] for s in top_suppliers])
        .annotate(
            s_suppkey=F('suppkey'),
            s_name=F('name'),
            s_address=F('address'),
            s_phone=F('phone')
        )
        .values('s_suppkey', 's_name', 's_address', 's_phone')
        .order_by('s_suppkey')
    )
    
    # Add revenue to results
    revenue_map = {s['suppkey']: s['total_revenue'] for s in top_suppliers}
    results_list = list(results)
    for r in results_list:
        r['total_revenue'] = revenue_map.get(r['s_suppkey'])
    
    return results_list


def run_query_sql(connection, params=None):
    """Execute Q15 via direct SQL."""
    P = _paramset(15, params)
    
    sql = f"""
    WITH revenue0 (supplier_no, total_revenue) AS (
      SELECT l_suppkey, SUM(l_extendedprice * (1 - l_discount))
      FROM lineitem
      WHERE l_shipdate >= CAST('{P['date']}' AS DATE)
        AND l_shipdate < CAST('{P['date_end']}' AS DATE)
      GROUP BY l_suppkey
    )
    SELECT s_suppkey, s_name, s_address, s_phone, total_revenue
    FROM supplier, revenue0
    WHERE s_suppkey = supplier_no
      AND total_revenue = (SELECT MAX(total_revenue) FROM revenue0)
    ORDER BY s_suppkey
    """
    
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    return results


def get_query_info():
    """Return metadata about this query."""
    return {
        'number': 15,
        'name': 'Top Supplier',
        'complexity': 'Complex',
        'description': 'Supplier with maximum total revenue in a period',
        'tables': ['supplier', 'lineitem'],
        'joins': 1,
        'aggregations': 2,
        'subqueries': 1
    }
