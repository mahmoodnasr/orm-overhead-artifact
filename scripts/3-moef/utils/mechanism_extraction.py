#!/usr/bin/env python3
"""
Mechanism Extraction Utilities

Extract optimizer mechanisms from query execution plans.

Paper Reference: Section 3.5.3 - "Mechanism Analysis"
Four dimensions:
1. Join Enumeration Strategy (DP vs Greedy)
2. Join Method Selection (Nested Loop, Hash, Merge)
3. Index Utilization (Index Scan vs Sequential Scan)
4. Predicate Pushdown and Subquery Handling
"""

from typing import Dict, List, Any, Optional
from enum import Enum


class JoinEnumerationStrategy(Enum):
    """Join enumeration strategies used by optimizers."""
    DYNAMIC_PROGRAMMING = "dp"  # O(3^n) search space - PostgreSQL
    GREEDY = "greedy"  # O(n^2) search space - MySQL
    ADAPTIVE = "adaptive"  # Runtime-adaptive - Oracle
    HEURISTIC = "heuristic"  # SQL Server
    UNKNOWN = "unknown"


class JoinMethod(Enum):
    """Physical join implementation methods."""
    NESTED_LOOP = "nested_loop"
    HASH_JOIN = "hash_join"
    MERGE_JOIN = "merge_join"
    INDEX_NESTED_LOOP = "index_nested_loop"
    APPLY = "apply"  # SQL Server
    ADAPTIVE_JOIN = "adaptive_join"  # SQL Server 2017+
    UNKNOWN = "unknown"


class ScanType(Enum):
    """Table/index access methods."""
    SEQUENTIAL_SCAN = "seq_scan"
    INDEX_SCAN = "index_scan"
    INDEX_ONLY_SCAN = "index_only_scan"
    BITMAP_INDEX_SCAN = "bitmap_index_scan"
    INDEX_RANGE_SCAN = "index_range_scan"  # Oracle
    FULL_TABLE_SCAN = "full_table_scan"  # Oracle/SQL Server
    CLUSTERED_INDEX_SCAN = "clustered_index_scan"  # SQL Server
    UNKNOWN = "unknown"


def extract_join_methods(plan: Dict[str, Any]) -> List[JoinMethod]:
    """
    Extract all join methods from an execution plan.

    Args:
        plan: Parsed execution plan (DBMS-agnostic format)

    Returns:
        List of JoinMethod enums found in the plan

    Example:
        >>> plan = {'operators': [
        ...     {'type': 'Hash Join'},
        ...     {'type': 'Nested Loop'}
        ... ]}
        >>> methods = extract_join_methods(plan)
        >>> JoinMethod.HASH_JOIN in methods
        True
    """
    join_methods = []

    def traverse(node: Dict[str, Any]):
        """Recursively traverse plan tree."""
        if not isinstance(node, dict):
            return

        node_type = node.get('type', '').lower()

        # Identify join methods
        if 'hash join' in node_type:
            join_methods.append(JoinMethod.HASH_JOIN)
        elif 'nested loop' in node_type:
            join_methods.append(JoinMethod.NESTED_LOOP)
        elif 'merge join' in node_type:
            join_methods.append(JoinMethod.MERGE_JOIN)
        elif 'index nested loop' in node_type:
            join_methods.append(JoinMethod.INDEX_NESTED_LOOP)
        elif 'apply' in node_type:
            join_methods.append(JoinMethod.APPLY)
        elif 'adaptive join' in node_type:
            join_methods.append(JoinMethod.ADAPTIVE_JOIN)

        # Recurse into children
        for child in node.get('children', []):
            traverse(child)

    traverse(plan)
    return join_methods


def extract_scan_types(plan: Dict[str, Any]) -> List[ScanType]:
    """
    Extract all scan/access methods from an execution plan.

    Args:
        plan: Parsed execution plan

    Returns:
        List of ScanType enums found in the plan

    Paper Finding:
        PostgreSQL indexing paradox - Django causes sequential scans
        even when indexes are available, while SQLAlchemy uses index scans.
    """
    scan_types = []

    def traverse(node: Dict[str, Any]):
        """Recursively traverse plan tree."""
        if not isinstance(node, dict):
            return

        node_type = node.get('type', '').lower()

        # Identify scan types
        if 'seq scan' in node_type or 'sequential scan' in node_type:
            scan_types.append(ScanType.SEQUENTIAL_SCAN)
        elif 'index only scan' in node_type:
            scan_types.append(ScanType.INDEX_ONLY_SCAN)
        elif 'index scan' in node_type:
            scan_types.append(ScanType.INDEX_SCAN)
        elif 'bitmap index scan' in node_type:
            scan_types.append(ScanType.BITMAP_INDEX_SCAN)
        elif 'index range scan' in node_type:
            scan_types.append(ScanType.INDEX_RANGE_SCAN)
        elif 'full table scan' in node_type or 'table scan' in node_type:
            scan_types.append(ScanType.FULL_TABLE_SCAN)
        elif 'clustered index scan' in node_type:
            scan_types.append(ScanType.CLUSTERED_INDEX_SCAN)

        # Recurse into children
        for child in node.get('children', []):
            traverse(child)

    traverse(plan)
    return scan_types


def count_joins(plan: Dict[str, Any]) -> int:
    """
    Count the number of join operations in a plan.

    Used to classify query complexity:
    - Simple: 1-2 joins
    - Medium: 3-4 joins
    - Complex: 5-7 joins
    - Very Complex: 8+ joins
    """
    join_count = 0

    def traverse(node: Dict[str, Any]):
        nonlocal join_count
        if not isinstance(node, dict):
            return

        node_type = node.get('type', '').lower()
        if 'join' in node_type:
            join_count += 1

        for child in node.get('children', []):
            traverse(child)

    traverse(plan)
    return join_count


def extract_predicate_pushdown(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze predicate pushdown effectiveness.

    Returns:
        Dictionary with:
        - total_predicates: Total filter conditions
        - pushed_down: Predicates applied at base table access
        - applied_late: Predicates applied after joins
        - pushdown_ratio: pushed_down / total_predicates

    Paper Finding:
        PostgreSQL and Oracle effectively push down predicates,
        while MySQL sometimes applies filters late in the plan.
    """
    total_predicates = 0
    pushed_down = 0
    applied_late = 0

    def traverse(node: Dict[str, Any], depth: int = 0):
        nonlocal total_predicates, pushed_down, applied_late

        if not isinstance(node, dict):
            return

        # Count predicates
        if 'filter' in node or 'condition' in node:
            total_predicates += 1

            # If filter is on a scan node, it's pushed down
            node_type = node.get('type', '').lower()
            if 'scan' in node_type:
                pushed_down += 1
            else:
                applied_late += 1

        for child in node.get('children', []):
            traverse(child, depth + 1)

    traverse(plan)

    return {
        'total_predicates': total_predicates,
        'pushed_down': pushed_down,
        'applied_late': applied_late,
        'pushdown_ratio': pushed_down / total_predicates if total_predicates > 0 else 0.0
    }


def identify_subquery_handling(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Identify how subqueries are handled.

    Strategies:
    - Decorrelation: Subquery transformed to join
    - Materialization: Subquery executed once, results cached
    - Apply: Subquery executed for each outer row (SQL Server)
    - Flattening: Subquery eliminated entirely

    Returns:
        Dictionary with subquery handling statistics
    """
    subquery_count = 0
    decorrelated = 0
    materialized = 0
    apply_operators = 0

    def traverse(node: Dict[str, Any]):
        nonlocal subquery_count, decorrelated, materialized, apply_operators

        if not isinstance(node, dict):
            return

        node_type = node.get('type', '').lower()

        if 'subquery' in node_type or 'subplan' in node_type:
            subquery_count += 1

            if 'materialized' in node_type:
                materialized += 1

        if 'apply' in node_type:
            apply_operators += 1

        # Decorrelation detection: subquery converted to join
        if 'join' in node_type:
            # Check if it was originally a subquery (heuristic)
            if node.get('original_type') == 'subquery':
                decorrelated += 1

        for child in node.get('children', []):
            traverse(child)

    traverse(plan)

    return {
        'subquery_count': subquery_count,
        'decorrelated': decorrelated,
        'materialized': materialized,
        'apply_operators': apply_operators
    }


def calculate_plan_complexity_score(plan: Dict[str, Any]) -> float:
    """
    Calculate overall plan complexity score.

    Factors:
    - Number of operators
    - Join count
    - Nesting depth
    - Parallelism

    Returns:
        Complexity score (higher = more complex)
    """
    operator_count = 0
    max_depth = 0
    parallel_operators = 0

    def traverse(node: Dict[str, Any], depth: int = 0):
        nonlocal operator_count, max_depth, parallel_operators

        if not isinstance(node, dict):
            return

        operator_count += 1
        max_depth = max(max_depth, depth)

        if node.get('parallel', False):
            parallel_operators += 1

        for child in node.get('children', []):
            traverse(child, depth + 1)

    traverse(plan)

    # Complexity score formula
    # Higher operator count and depth increase complexity
    # Parallelism slightly increases complexity (coordination overhead)
    score = (operator_count * 1.0) + (max_depth * 2.0) + (parallel_operators * 0.5)

    return score


def extract_parallelism_info(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract parallelism information from plan.

    Returns:
        Dictionary with:
        - parallel_workers: Number of parallel workers
        - parallel_operators: Count of parallelized operators
        - parallel_strategy: Type of parallelism used

    Paper Finding:
        - PostgreSQL: Single-threaded for most queries
        - Oracle: Adaptive parallelism (4 threads)
        - SQL Server: Aggressive parallelism (8 threads)
    """
    parallel_workers = 0
    parallel_operators = 0
    parallel_strategy = "none"

    def traverse(node: Dict[str, Any]):
        nonlocal parallel_workers, parallel_operators, parallel_strategy

        if not isinstance(node, dict):
            return

        # Check for parallelism indicators
        if node.get('parallel', False):
            parallel_operators += 1

        workers = node.get('workers', 0)
        if workers > 0:
            parallel_workers = max(parallel_workers, workers)

        node_type = node.get('type', '').lower()
        if 'parallel' in node_type:
            parallel_operators += 1
            if 'gather' in node_type:
                parallel_strategy = "gather"
            elif 'exchange' in node_type:
                parallel_strategy = "exchange"

        for child in node.get('children', []):
            traverse(child)

    traverse(plan)

    return {
        'parallel_workers': parallel_workers,
        'parallel_operators': parallel_operators,
        'parallel_strategy': parallel_strategy
    }


# Example usage
if __name__ == '__main__':
    # Example plan structure
    example_plan = {
        'type': 'Hash Join',
        'estimated_rows': 1000,
        'actual_rows': 1000,
        'children': [
            {
                'type': 'Seq Scan',
                'table': 'orders',
                'filter': 'o_orderdate > 1995-01-01'
            },
            {
                'type': 'Hash',
                'children': [
                    {
                        'type': 'Index Scan',
                        'table': 'customer',
                        'index': 'customer_pkey'
                    }
                ]
            }
        ]
    }

    print("Mechanism Extraction Example")
    print("=" * 60)

    join_methods = extract_join_methods(example_plan)
    print(f"Join Methods: {[j.value for j in join_methods]}")

    scan_types = extract_scan_types(example_plan)
    print(f"Scan Types: {[s.value for s in scan_types]}")

    join_count = count_joins(example_plan)
    print(f"Join Count: {join_count}")

    predicate_info = extract_predicate_pushdown(example_plan)
    print(f"Predicate Pushdown: {predicate_info}")

    complexity = calculate_plan_complexity_score(example_plan)
    print(f"Plan Complexity Score: {complexity:.1f}")
