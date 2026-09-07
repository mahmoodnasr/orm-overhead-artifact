#!/usr/bin/env python3
"""
PostgreSQL Execution Plan Parser

Parses PostgreSQL EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output
into a standardized format for MOEF analysis.

Paper Reference: Section 3.5.2 - "Phase 2: Plan Collection"
PostgreSQL uses EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) for runtime statistics.
"""

import json
from typing import Dict, List, Any, Optional


def parse_postgres_plan(plan_json: Any) -> Dict[str, Any]:
    """
    Parse PostgreSQL EXPLAIN JSON output into standardized format.

    Args:
        plan_json: Either JSON string or dict from EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)

    Returns:
        Standardized plan dictionary with:
        - type: Operator type
        - estimated_rows: Optimizer's cardinality estimate
        - actual_rows: Actual rows from execution
        - estimated_cost: Optimizer's cost estimate
        - actual_time: Actual execution time (ms)
        - children: List of child operators
        - buffers: Buffer usage statistics
        - metadata: Additional DBMS-specific info

    Example PostgreSQL EXPLAIN output:
        ```sql
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT * FROM orders WHERE o_orderdate > '1995-01-01';
        ```

    Paper Findings:
        - PostgreSQL uses Dynamic Programming for join enumeration (O(3^n))
        - Q-error for Q8: 1.4 (excellent cardinality estimation)
        - Effective predicate pushdown and subquery decorrelation
    """
    # Handle JSON string input
    if isinstance(plan_json, str):
        plan_json = json.loads(plan_json)

    # PostgreSQL wraps plan in array with "Plan" key
    if isinstance(plan_json, list) and len(plan_json) > 0:
        plan_json = plan_json[0]

    if 'Plan' in plan_json:
        root_plan = plan_json['Plan']
        metadata = {
            'execution_time': plan_json.get('Execution Time'),
            'planning_time': plan_json.get('Planning Time'),
            'total_cost': plan_json.get('Total Cost'),
            'triggers': plan_json.get('Triggers', [])
        }
    else:
        root_plan = plan_json
        metadata = {}

    return _parse_node(root_plan, metadata)


def _parse_node(node: Dict[str, Any], global_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively parse a PostgreSQL plan node.

    PostgreSQL Plan Node Structure:
        - Node Type: e.g., "Seq Scan", "Hash Join", "Index Scan"
        - Startup Cost: Cost to return first row
        - Total Cost: Cost to return all rows
        - Plan Rows: Estimated row count
        - Plan Width: Estimated row width (bytes)
        - Actual Startup Time: Time to first row (ms)
        - Actual Total Time: Time to all rows (ms)
        - Actual Rows: Actual row count from execution
        - Actual Loops: Number of times operator executed
        - Shared Hit Blocks: Pages found in buffer cache
        - Shared Read Blocks: Pages read from disk
    """
    node_type = node.get('Node Type', 'Unknown')

    # Extract cardinality estimates
    estimated_rows = node.get('Plan Rows', 0)
    actual_rows = node.get('Actual Rows', 0)
    actual_loops = node.get('Actual Loops', 1)

    # Total actual rows = rows per loop × number of loops
    total_actual_rows = actual_rows * actual_loops

    # Extract cost estimates
    startup_cost = node.get('Startup Cost', 0.0)
    total_cost = node.get('Total Cost', 0.0)

    # Extract timing (in milliseconds)
    actual_startup_time = node.get('Actual Startup Time', 0.0)
    actual_total_time = node.get('Actual Total Time', 0.0)

    # Total actual time = time per loop × number of loops
    total_actual_time = actual_total_time * actual_loops

    # Extract buffer statistics
    buffers = _extract_buffer_stats(node)

    # Extract filters and conditions
    filters = []
    if 'Filter' in node:
        filters.append({
            'type': 'filter',
            'condition': node['Filter'],
            'rows_removed': node.get('Rows Removed by Filter', 0)
        })
    if 'Index Cond' in node:
        filters.append({
            'type': 'index_condition',
            'condition': node['Index Cond']
        })
    if 'Hash Cond' in node:
        filters.append({
            'type': 'hash_condition',
            'condition': node['Hash Cond']
        })
    if 'Join Filter' in node:
        filters.append({
            'type': 'join_filter',
            'condition': node['Join Filter'],
            'rows_removed': node.get('Rows Removed by Join Filter', 0)
        })

    # Determine if this is a scan, join, or other operator
    is_scan = any(scan_type in node_type for scan_type in
                  ['Seq Scan', 'Index Scan', 'Index Only Scan', 'Bitmap Heap Scan'])
    is_join = 'Join' in node_type
    is_aggregate = any(agg_type in node_type for agg_type in
                      ['Aggregate', 'Group', 'HashAggregate', 'GroupAggregate'])

    # Build standardized node
    standardized_node = {
        'type': node_type,
        'estimated_rows': estimated_rows,
        'actual_rows': total_actual_rows,
        'estimated_cost_startup': startup_cost,
        'estimated_cost_total': total_cost,
        'actual_time_startup': actual_startup_time,
        'actual_time_total': total_actual_time,
        'actual_loops': actual_loops,
        'plan_width': node.get('Plan Width', 0),
        'buffers': buffers,
        'filters': filters,
        'children': [],
        'metadata': {}
    }

    # Add scan-specific metadata
    if is_scan:
        standardized_node['metadata']['relation_name'] = node.get('Relation Name')
        standardized_node['metadata']['alias'] = node.get('Alias')
        standardized_node['metadata']['scan_direction'] = node.get('Scan Direction')
        if 'Index Name' in node:
            standardized_node['metadata']['index_name'] = node['Index Name']

    # Add join-specific metadata
    if is_join:
        standardized_node['metadata']['join_type'] = node.get('Join Type')
        standardized_node['metadata']['inner_unique'] = node.get('Inner Unique', False)

    # Add aggregate-specific metadata
    if is_aggregate:
        standardized_node['metadata']['group_key'] = node.get('Group Key', [])
        standardized_node['metadata']['strategy'] = node.get('Strategy')

    # Add parallel execution info
    if 'Workers Planned' in node:
        standardized_node['metadata']['workers_planned'] = node['Workers Planned']
    if 'Workers Launched' in node:
        standardized_node['metadata']['workers_launched'] = node['Workers Launched']
    if 'Parallel Aware' in node:
        standardized_node['metadata']['parallel_aware'] = node['Parallel Aware']

    # Recursively parse children
    if 'Plans' in node:
        for child in node['Plans']:
            standardized_node['children'].append(_parse_node(child, global_metadata))

    return standardized_node


def _extract_buffer_stats(node: Dict[str, Any]) -> Dict[str, int]:
    """
    Extract buffer statistics from PostgreSQL plan node.

    Buffer statistics show memory vs disk I/O:
    - Shared Hit Blocks: Pages found in PostgreSQL buffer cache (fast)
    - Shared Read Blocks: Pages read from OS or disk (slower)
    - Shared Dirtied Blocks: Pages modified
    - Shared Written Blocks: Pages written to disk
    - Local Hit/Read/Dirtied/Written: Local buffer pool (temp tables)
    - Temp Read/Written: Temporary files on disk

    Returns:
        Dictionary with buffer statistics
    """
    return {
        'shared_hit': node.get('Shared Hit Blocks', 0),
        'shared_read': node.get('Shared Read Blocks', 0),
        'shared_dirtied': node.get('Shared Dirtied Blocks', 0),
        'shared_written': node.get('Shared Written Blocks', 0),
        'local_hit': node.get('Local Hit Blocks', 0),
        'local_read': node.get('Local Read Blocks', 0),
        'local_dirtied': node.get('Local Dirtied Blocks', 0),
        'local_written': node.get('Local Written Blocks', 0),
        'temp_read': node.get('Temp Read Blocks', 0),
        'temp_written': node.get('Temp Written Blocks', 0)
    }


def calculate_buffer_hit_ratio(buffers: Dict[str, int]) -> float:
    """
    Calculate buffer cache hit ratio.

    Hit ratio = hits / (hits + reads)

    A high hit ratio (>0.95) indicates good caching.
    A low hit ratio suggests the dataset doesn't fit in memory.

    Args:
        buffers: Buffer statistics from _extract_buffer_stats

    Returns:
        Hit ratio between 0.0 and 1.0
    """
    hits = buffers.get('shared_hit', 0) + buffers.get('local_hit', 0)
    reads = buffers.get('shared_read', 0) + buffers.get('local_read', 0)

    total = hits + reads
    if total == 0:
        return 1.0  # No I/O = perfect cache hit

    return hits / total


def extract_join_order(plan: Dict[str, Any]) -> List[str]:
    """
    Extract the join order from a PostgreSQL plan.

    PostgreSQL's dynamic programming optimizer considers many join orders.
    The actual join order chosen is visible in the plan tree structure.

    Returns:
        List of table names in join order (bottom-up from plan tree)
    """
    join_order = []

    def traverse(node: Dict[str, Any]):
        """Depth-first traversal to extract join order."""
        # If this is a base table scan, add it
        if 'Scan' in node.get('type', ''):
            relation = node.get('metadata', {}).get('relation_name')
            if relation and relation not in join_order:
                join_order.append(relation)

        # Recurse into children (left child first for join order)
        for child in node.get('children', []):
            traverse(child)

    traverse(plan)
    return join_order


# Example usage and testing
if __name__ == '__main__':
    # Example PostgreSQL EXPLAIN JSON output
    example_plan_json = [{
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Startup Cost": 5.00,
            "Total Cost": 15.50,
            "Plan Rows": 100,
            "Plan Width": 16,
            "Actual Startup Time": 0.050,
            "Actual Total Time": 1.250,
            "Actual Rows": 95,
            "Actual Loops": 1,
            "Hash Cond": "(o.c_custkey = c.c_custkey)",
            "Shared Hit Blocks": 50,
            "Shared Read Blocks": 10,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Parent Relationship": "Outer",
                    "Relation Name": "orders",
                    "Alias": "o",
                    "Startup Cost": 0.00,
                    "Total Cost": 5.00,
                    "Plan Rows": 100,
                    "Plan Width": 8,
                    "Actual Startup Time": 0.010,
                    "Actual Total Time": 0.500,
                    "Actual Rows": 100,
                    "Actual Loops": 1,
                    "Filter": "(o_orderdate > '1995-01-01'::date)",
                    "Rows Removed by Filter": 50,
                    "Shared Hit Blocks": 30,
                    "Shared Read Blocks": 5
                },
                {
                    "Node Type": "Hash",
                    "Parent Relationship": "Inner",
                    "Startup Cost": 3.00,
                    "Total Cost": 3.00,
                    "Plan Rows": 50,
                    "Plan Width": 8,
                    "Actual Startup Time": 0.200,
                    "Actual Total Time": 0.200,
                    "Actual Rows": 50,
                    "Actual Loops": 1,
                    "Shared Hit Blocks": 20,
                    "Shared Read Blocks": 5,
                    "Plans": [
                        {
                            "Node Type": "Index Scan",
                            "Parent Relationship": "Outer",
                            "Scan Direction": "Forward",
                            "Index Name": "customer_pkey",
                            "Relation Name": "customer",
                            "Alias": "c",
                            "Startup Cost": 0.00,
                            "Total Cost": 3.00,
                            "Plan Rows": 50,
                            "Plan Width": 8,
                            "Actual Startup Time": 0.010,
                            "Actual Total Time": 0.150,
                            "Actual Rows": 50,
                            "Actual Loops": 1,
                            "Index Cond": "(c_custkey < 100)",
                            "Shared Hit Blocks": 20,
                            "Shared Read Blocks": 5
                        }
                    ]
                }
            ]
        },
        "Execution Time": 1.500,
        "Planning Time": 0.250
    }]

    print("PostgreSQL Plan Parser Example")
    print("=" * 70)

    # Parse the plan
    parsed = parse_postgres_plan(example_plan_json)

    print(f"\nRoot Operator: {parsed['type']}")
    print(f"Estimated Rows: {parsed['estimated_rows']}")
    print(f"Actual Rows: {parsed['actual_rows']}")
    print(f"Estimated Cost: {parsed['estimated_cost_total']:.2f}")
    print(f"Actual Time: {parsed['actual_time_total']:.3f} ms")

    # Calculate q-error (need to import from utils)
    from ..utils.qerror import calculate_qerror
    qerror = calculate_qerror(parsed['estimated_rows'], parsed['actual_rows'])
    print(f"Q-error: {qerror:.2f}")

    # Buffer statistics
    hit_ratio = calculate_buffer_hit_ratio(parsed['buffers'])
    print(f"\nBuffer Hit Ratio: {hit_ratio:.2%}")
    print(f"Shared Blocks - Hit: {parsed['buffers']['shared_hit']}, "
          f"Read: {parsed['buffers']['shared_read']}")

    # Join order
    join_order = extract_join_order(parsed)
    print(f"\nJoin Order: {' -> '.join(join_order)}")

    # Children
    print(f"\nNumber of child operators: {len(parsed['children'])}")
    for i, child in enumerate(parsed['children']):
        print(f"  Child {i+1}: {child['type']} on {child.get('metadata', {}).get('relation_name', 'N/A')}")

    print("\n" + "=" * 70)
