"""Query lookups Django does not provide, shared by every query that needs them.

Registering a lookup is a documented Django extension point and leaves the query
ORM-built: the compiler still generates the SELECT, the joins and the grouping,
and the pattern travels as a bound parameter rather than pasted into the SQL.
`scripts/validate_queries.py`'s ORM? check passes on it.

This module exists because the same lookup was needed twice. It was written
inside `q13_sqlserver.py` for that query, and Q16 then needed the identical
construct on every vendor - at which point a second copy would have been the
shape of defect C9: two definitions of one thing, drifting apart the moment
either is corrected.
"""
from django.db.models import Lookup
from django.db.models.fields import Field


@Field.register_lookup
class Like(Lookup):
    """`field__like='pattern'` -> `field LIKE ?`, wildcards intact.

    Django's built-in string lookups cannot express a pattern with interior
    wildcards. `__contains` produces `LIKE '%value%'` and escapes any `%` and
    `_` inside the value, so it can only match one literal run of characters;
    TPC-H's Q13 and Q16 both need two words in a fixed order with a wildcard
    between them. `__regex` can express it but is not portable here: on SQL
    Server, mssql-django maps `__regex` to `dbo.REGEXP_LIKE`, a user-defined
    function the database does not have, and supplying it would make the ORM
    path carry a scalar UDF over millions of rows - so the measurement would be
    of UDF dispatch rather than of the ORM. See `q13_sqlserver.py`.

    The pattern is bound, not interpolated, which also sidesteps C14: mssql-django
    rewrites `%\\w+` anywhere in a statement containing "GROUP BY", and both
    queries that use this lookup have a GROUP BY. That rewrite operates on the
    query text, so a parameter is untouched by it.

    Registering on `Field` makes `__like` available on every field. Nothing uses
    it except the two queries named above.
    """
    lookup_name = "like"

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return "%s LIKE %s" % (lhs, rhs), lhs_params + rhs_params
