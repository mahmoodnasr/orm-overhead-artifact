"""mssql-django truncates Decimal parameters to integers in grouped queries.

`mssql/base.py::_as_sql_type` returns the bare string 'NUMERIC' for a Decimal.
In T-SQL, NUMERIC without arguments means NUMERIC(18, 0) - scale zero - so the
fractional part is silently discarded. That function is reached only through
`format_group_by_params`, which `execute()` calls when 'GROUP BY' appears in the
statement, so the corruption is invisible except in grouped queries.

Measured on the campaign host, mssql-django 1.8.0, SQL Server 2025, pyodbc
5.3.0, ODBC Driver 18:

    SELECT TOP 1 CONVERT(varchar(60), ?) FROM lineitem WHERE l_shipdate >= ?
      -> 1772627.2087            (correct)
    ... the same statement with GROUP BY l_suppkey appended
      -> 1772627                 (fraction gone)

Raw pyodbc is correct in both cases, so this is mssql-django and not the
driver, the ODBC layer or the server.

What it cost here: TPC-H Q15 reads the maximum supplier revenue as
Decimal('1772627.2087'), correct, and then filters on it. The filter is a
HAVING on a grouped query, so the parameter arrived as 1772627, matched no
group, and Django's Q15 returned zero rows while the other three paths returned
the correct row. That is defect C15 recurring: the earlier fix addressed a
different mechanism - Django quantising the value to the field's declared
decimal_places - which was real but is not this.

This patch is measurement-affecting and is disclosed as such. It changes only
the declared type of a bound parameter, never a value or a query plan choice,
and it is applied identically to every timed and untimed path on this system.
"""

from decimal import Decimal


def apply():
    """Idempotently correct _as_sql_type for Decimal parameters."""
    try:
        from mssql import base as mssql_base
    except ImportError:
        return False
    cls = mssql_base.CursorWrapper
    if getattr(cls, "_decimal_scale_patched", False):
        return True
    original = cls._as_sql_type

    def _as_sql_type(self, typ, value):
        if isinstance(value, Decimal):
            exponent = value.as_tuple().exponent
            # exponent is negative for fractional values; 'n' for NaN/Inf.
            scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
            # Always declare the maximum precision the server supports and
            # let the scale carry the value. Computing a tight precision from
            # the digit count leaves no headroom for the integer part and the
            # server rejects the bind with 22003, numeric value out of range.
            scale = min(scale, 30)
            return "NUMERIC(38, %d)" % scale
        return original(self, typ, value)

    cls._as_sql_type = _as_sql_type

    # --- second defect, same family, different hook -----------------------
    # SQL Server's AVG over a NUMERIC column comes back through mssql-django
    # as a float converted straight to Decimal, so it carries the float's full
    # binary expansion:
    #
    #   Avg('acctbal') -> Decimal('5003.685765215157516649924218654632568359375')
    #                     43 digits, scale 39
    #
    # SQL Server's NUMERIC tops out at 38 digits of precision, so pyodbc cannot
    # bind it at all and raises, before any SQL runs:
    #
    #   ('HY104', '[Microsoft][ODBC Driver 18 for SQL Server]
    #    Invalid precision value (0) (SQLBindParameter)')
    #
    # That is what stopped TPC-H Q22's Django ORM path, which computes the
    # average account balance in Python and binds it back as a filter bound.
    # Quantising to a scale the server can represent does not change the
    # comparison: acctbal is DECIMAL(15,2), so twenty decimal places is
    # eighteen more than can affect the result.
    original_format = cls.format_params

    def format_params(self, params):
        if params:
            params = [_fit_decimal(p) if isinstance(p, Decimal) else p for p in params]
        return original_format(self, params)

    cls.format_params = format_params
    cls._decimal_scale_patched = True
    return True


def _fit_decimal(value, max_precision=38, max_scale=10):
    """Return value quantised to something SQL Server can bind, or unchanged."""
    t = value.as_tuple()
    if not isinstance(t.exponent, int):  # NaN / Infinity
        return value
    scale = -t.exponent if t.exponent < 0 else 0
    if len(t.digits) <= max_precision and scale <= max_scale:
        return value
    integer_digits = max(1, len(t.digits) + t.exponent)
    room = max(0, max_precision - integer_digits)
    target = min(scale, room, max_scale)
    return value.quantize(Decimal(1).scaleb(-target))
