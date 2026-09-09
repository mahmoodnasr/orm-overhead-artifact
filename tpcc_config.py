"""The three TPC-C choices that must be identical across both frameworks.

All ten transaction modules import from here. Before this file existed each of
them carried its own remembered constants, and the two frameworks disagreed on
key range, locking policy and transaction boundary — so measuring them compared
those three choices rather than Django against SQLAlchemy. This module
C10 records what that cost.

The rule is the same one `tpch_params.py` follows: a parameter that both
frameworks depend on lives in exactly one place, so the two cannot drift apart.

## The cardinalities

These describe the database that is actually loaded, and they default to what
`scripts/1-setup/generate_tpcc_data.py` generates.

Note for anyone reading C10 alongside this file: C10 states that the database
holds 100 warehouses and that drawing `w_id` from `randint(1, 10)` therefore
confined every worker to a tenth of it. The repository contains no loader that
builds 100 warehouses — `generate_tpcc_data.py` sets `NUM_WAREHOUSES = 10`, and
it is the only TPC-C generator here. On a 10-warehouse database the original
range was correct and the defect C10 describes is, in that one respect, not
present. The value is still centralised, because the real hazard is a config
that disagrees with the data: drawing `w_id` from 1..100 against ten loaded
warehouses makes nine of every ten transactions fail on a missing row, and a
harness that counts a returned dict as success would report that as throughput.

`verify_against()` exists so the disagreement is caught loudly instead. Call it
before measuring.

Override any of these from the environment when the loaded scale differs:

    TPCC_WAREHOUSES  TPCC_DISTRICTS  TPCC_CUSTOMERS  TPCC_ITEMS

## The locking policy

`LOCK_DISTRICT` selects one policy for both frameworks and both access paths.
It defaults to True, which is the specification's reading: New-Order takes
`d_next_o_id`, increments it, and uses it as the order key, so two concurrent
New-Orders on the same district must serialise or they assign the same order id.
Django's `F()` increment makes the *update* atomic but does not stop the second
transaction reading the same value first, so without the lock the two frameworks
are not merely different, they are both wrong in a way that only shows up under
concurrency.

Set `TPCC_LOCK_DISTRICT=0` to measure the unlocked policy deliberately — but
then report it as an experimental factor, because it changes what is measured.
"""

import os

# --------------------------------------------------------------- cardinalities

WAREHOUSES = int(os.environ.get("TPCC_WAREHOUSES", "10"))
DISTRICTS_PER_WAREHOUSE = int(os.environ.get("TPCC_DISTRICTS", "10"))
CUSTOMERS_PER_DISTRICT = int(os.environ.get("TPCC_CUSTOMERS", "3000"))
ITEMS = int(os.environ.get("TPCC_ITEMS", "100000"))

# ------------------------------------------------------------- locking policy

LOCK_DISTRICT = os.environ.get("TPCC_LOCK_DISTRICT", "1") not in ("0", "false", "False")

# TPC-H clause 2.4.1.3: a New-Order carries between 5 and 15 order lines. This
# is fixed by the specification and does not scale with the database, so unlike
# the cardinalities above it is not overridable.
OL_CNT_MIN, OL_CNT_MAX = 5, 15


def pick_keys(rng):
    """Draw the keys one business transaction operates on.

    Returns (w_id, d_id, c_id, ol_cnt). Callers that do not order anything
    discard ol_cnt; drawing it here anyway keeps every transaction consuming the
    same number of values from the generator, so two runs with the same seed
    line up transaction for transaction across the two frameworks.

    `rng` is passed in rather than taken from module scope so a caller can hand
    over a seeded Random and get a reproducible stream.
    """
    return (
        rng.randint(1, WAREHOUSES),
        rng.randint(1, DISTRICTS_PER_WAREHOUSE),
        rng.randint(1, CUSTOMERS_PER_DISTRICT),
        rng.randint(OL_CNT_MIN, OL_CNT_MAX),
    )


def verify_against(cursor):
    """Check these constants against the loaded database. Raises on mismatch.

    A key range wider than the data does not error in any obvious way: the
    transaction simply fails to find its row. Django's ORM paths used to turn
    that into a returned dict rather than an exception (C10), so the failure
    would have been recorded as a completed transaction. Checking up front is
    the only point at which the mismatch is cheap to see.
    """
    expected = {
        "warehouse": WAREHOUSES,
        "district": WAREHOUSES * DISTRICTS_PER_WAREHOUSE,
        "customer": WAREHOUSES * DISTRICTS_PER_WAREHOUSE * CUSTOMERS_PER_DISTRICT,
        "item": ITEMS,
    }
    wrong = []
    for table, want in expected.items():
        cursor.execute("SELECT COUNT(*) FROM %s" % table)
        got = cursor.fetchone()[0]
        if got != want:
            wrong.append(
                "%s: config expects %s, database holds %s"
                % (table, format(want, ","), format(got, ","))
            )
    if wrong:
        raise RuntimeError(
            "tpcc_config does not describe the loaded database:\n  "
            + "\n  ".join(wrong)
            + "\nSet TPCC_WAREHOUSES / TPCC_DISTRICTS / TPCC_CUSTOMERS / TPCC_ITEMS "
            "to match, or reload the data. Measuring against a mismatch records "
            "failed transactions as completed ones."
        )
    return True


def summary():
    """One line for the run log, so a campaign records what it measured."""
    return (
        "TPC-C: %d warehouses x %d districts x %d customers, %d items, "
        "lock_district=%s"
        % (
            WAREHOUSES,
            DISTRICTS_PER_WAREHOUSE,
            CUSTOMERS_PER_DISTRICT,
            ITEMS,
            LOCK_DISTRICT,
        )
    )


def district_lock_sql(vendor):
    """How to take an update lock on one district row, per dialect.

    Returns (table_hint, trailing_clause) to splice into

        SELECT d_next_o_id FROM district{table_hint} WHERE ...{trailing_clause}

    Both are empty when LOCK_DISTRICT is off.

    This exists because `FOR UPDATE` is not portable and the hand-written
    baselines assumed it was. PostgreSQL, MySQL and Oracle all take a trailing
    `FOR UPDATE`; SQL Server has no such clause outside a cursor and answers
    with "FOR UPDATE clause allowed only for DECLARE CURSOR". Its equivalent is
    the UPDLOCK table hint, which holds the update lock to the end of the
    transaction - the same semantics, in a different position in the statement.

    Measured consequence before this existed: both raw-SQL paths of T1 failed
    outright on SQL Server while both ORM paths succeeded, because Django's
    `select_for_update()` and SQLAlchemy's `with_for_update()` each emit the
    hint their dialect needs. That is worth a line in the write-up: on this
    query the ORM is the *more* portable of the two, which is the opposite of
    the direction C17 records for Q13.
    """
    if not LOCK_DISTRICT:
        return "", ""
    if vendor in ("mssql", "microsoft", "sqlserver"):
        return " WITH (UPDLOCK, ROWLOCK)", ""
    return "", " FOR UPDATE"
