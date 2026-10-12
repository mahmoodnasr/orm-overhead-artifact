"""
TPC-C Transactions Package for SQLAlchemy

All 5 TPC-C benchmark transactions implemented with both ORM and SQL versions.
"""
import importlib

def get_transaction_module(transaction_number: int):
    """Get the module for a specific transaction number."""
    if not 1 <= transaction_number <= 5:
        raise ValueError(f"Transaction number must be between 1 and 5, got {transaction_number}")
    
    module_name = f'sqlalchemy_app.tpcc_queries.t{transaction_number}'
    try:
        module = importlib.import_module(module_name)
        return module
    except ImportError as e:
        raise ImportError(f"Cannot load transaction {transaction_number}: {e}")

def get_transaction_module_for_db(transaction_number: int, database: str):
    """Get transaction module with database-specific handling."""
    return get_transaction_module(transaction_number)

def get_all_transactions():
    """Return list of all transaction numbers."""
    return list(range(1, 6))

