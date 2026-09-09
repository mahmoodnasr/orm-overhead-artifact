"""
TPC-C Transactions Package

All 5 TPC-C benchmark transactions implemented with both ORM and SQL versions.
"""

from . import t1_neworder, t2_payment, t3_orderstatus, t4_delivery, t5_stocklevel

# Map transaction numbers to modules
TRANSACTION_MODULES = {
    1: t1_neworder,
    2: t2_payment,
    3: t3_orderstatus,
    4: t4_delivery,
    5: t5_stocklevel,
}


def get_transaction_module(transaction_number):
    """Get the module for a specific transaction number."""
    return TRANSACTION_MODULES.get(transaction_number)


def get_all_transactions():
    """Return list of all transaction numbers."""
    return list(TRANSACTION_MODULES.keys())


def get_transaction_module_for_db(transaction_number, database):
    """Get transaction module with database-specific handling."""
    module = TRANSACTION_MODULES.get(transaction_number)
    if not module:
        raise ValueError(f"Invalid transaction number: {transaction_number}")

    # Check for database-specific implementation
    db_specific_name = f"t{transaction_number}_{database}"
    if hasattr(module, db_specific_name):
        return getattr(module, db_specific_name)

    return module
