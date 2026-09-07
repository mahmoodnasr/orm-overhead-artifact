"""
Helper module for dynamically importing and managing TPC-H query modules.
Provides utilities to load query modules (q01.py - q22.py) and access their metadata.
"""

import importlib
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Query complexity mapping from research paper
COMPLEXITY_MAP = {
    1: 'Medium', 2: 'Complex', 3: 'Medium', 4: 'Medium',
    5: 'Complex', 6: 'Simple', 7: 'Complex', 8: 'Very Complex',
    9: 'Very Complex', 10: 'Complex', 11: 'Medium', 12: 'Medium',
    13: 'Complex', 14: 'Simple', 15: 'Complex', 16: 'Medium',
    17: 'Complex', 18: 'Complex', 19: 'Simple', 20: 'Complex',
    21: 'Very Complex', 22: 'Very Complex'
}


def get_query_module(query_number: int):
    """
    Dynamically import a query module by number.
    
    Args:
        query_number: Query number (1-22)
        
    Returns:
        Imported query module with run_query_orm(), run_query_sql(), and get_query_info()
        
    Raises:
        ImportError: If query module cannot be imported
        ValueError: If query_number is invalid
    """
    if not 1 <= query_number <= 22:
        raise ValueError(f"Query number must be between 1 and 22, got {query_number}")
    
    module_name = f'django_app.queries.q{query_number:02d}'
    
    try:
        module = importlib.import_module(module_name)
        
        # Validate that required functions exist
        required_functions = ['run_query_orm', 'run_query_sql', 'get_query_info']
        missing = [f for f in required_functions if not hasattr(module, f)]
        
        if missing:
            raise AttributeError(
                f"Query module {module_name} missing functions: {', '.join(missing)}"
            )
        
        return module
        
    except ImportError as e:
        logger.error(f"Failed to import {module_name}: {e}")
        raise ImportError(f"Cannot load query {query_number}: {e}")


def get_all_queries() -> List[int]:
    """
    Return list of all available query numbers.
    
    Returns:
        List [1, 2, 3, ..., 22]
    """
    return list(range(1, 23))


def get_query_complexity(query_number: int) -> str:
    """
    Get the complexity classification for a query.
    
    Args:
        query_number: Query number (1-22)
        
    Returns:
        Complexity string: 'Simple', 'Medium', 'Complex', or 'Very Complex'
        
    Raises:
        ValueError: If query_number is invalid
    """
    if query_number not in COMPLEXITY_MAP:
        raise ValueError(f"Query number must be between 1 and 22, got {query_number}")
    
    return COMPLEXITY_MAP[query_number]


def get_query_name(query_number: int) -> str:
    """
    Get the formatted query name.
    
    Args:
        query_number: Query number (1-22)
        
    Returns:
        Query name like "TPC-H Q01"
    """
    return f"TPC-H Q{query_number:02d}"


def get_query_info(query_number: int) -> Dict[str, Any]:
    """
    Get full metadata for a query by loading its module and calling get_query_info().
    
    Args:
        query_number: Query number (1-22)
        
    Returns:
        Dictionary with query metadata including number, name, complexity, etc.
    """
    module = get_query_module(query_number)
    info = module.get_query_info()
    
    # Ensure complexity is set from our mapping
    info['complexity'] = get_query_complexity(query_number)
    
    return info


def validate_query_module(query_number: int) -> tuple[bool, Optional[str]]:
    """
    Validate that a query module exists and has required functions.
    
    Args:
        query_number: Query number to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        module = get_query_module(query_number)
        
        # Try calling get_query_info to ensure it works
        info = module.get_query_info()
        
        if 'number' not in info:
            return False, "get_query_info() must return dict with 'number' key"
        
        if info['number'] != query_number:
            return False, f"Query module reports number {info['number']}, expected {query_number}"
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def list_available_queries() -> List[Dict[str, Any]]:
    """
    List all available queries with their basic metadata.
    
    Returns:
        List of dicts with query_number, name, complexity, and availability status
    """
    queries = []
    
    for query_num in range(1, 23):
        is_valid, error = validate_query_module(query_num)
        
        queries.append({
            'query_number': query_num,
            'name': get_query_name(query_num),
            'complexity': get_query_complexity(query_num),
            'available': is_valid,
            'error': error if not is_valid else None
        })
    
    return queries
