"""TPC-H substitution parameters that depend on the scale factor.

Almost every substitution parameter in the TPC-H validation set is a constant,
which is why it is easy to assume they all are. Q11's FRACTION is not: the
specification defines it as 0.0001/SF, so it has to shrink as the database
grows.

Held at 0.0001 the HAVING clause excludes every group above SF1 and Q11 returns
an empty result. It is a quiet failure — the query still scans PARTSUPP, still
aggregates, still sorts, and still reports a plausible execution time, so a
benchmark harness records it as a successful measurement of a query that is not
Q11. At SF10 the German stock total is 810,291,376,524 and the threshold the
wrong constant produces is 81,029,137, which no individual part reaches.

Set TPCH_SF in the environment to the scale factor of the loaded database. Both
frameworks and both access paths read the value from here, so they cannot drift
apart.
"""

import os

SCALE_FACTOR = float(os.environ.get("TPCH_SF", "1"))

# TPC-H 2.18.0, clause 2.11.3: FRACTION = 0.0001 / SF
Q11_FRACTION = 0.0001 / SCALE_FACTOR
