#!/usr/bin/env python3
"""
MySQL Execution Plan Parser

Parses MySQL EXPLAIN ANALYZE and EXPLAIN FORMAT=JSON output
into standardized format for MOEF analysis.

Paper Reference: Section 3.5.2 - "Phase 2: Plan Collection"

MySQL Notes:
- EXPLAIN ANALYZE available in MySQL 8.0.18+
- Limited runtime statistics compared to PostgreSQL
- Cost model calibrated for HDD (paper finding)
- Greedy join enumeration O(n^2) (paper finding)
"""

import json
from typing import Dict, List, Any, Optional, Union


def parse_mysql_plan(plan_data: Any) -> Dict[str, Any]:
    """
    Parse MySQL EXPLAIN output into standardized format.

    Args:
        plan_data: Either:
            - JSON string from EXPLAIN FORMAT=JSON
            - Dict from parsed JSON
            - Text from EXPLAIN ANALYZE

    Returns:
        Standardized plan dictionary

    Paper Findings (MySQL):
        - Greedy join enumeration struggles with complex queries
        - Q8 q-error: 8.7 (poor cardinality estimation)
        - Cost model doesn't align with SSD performance
        - Indexing provides limited benefit on complex queries
    """
    # Handle different input formats
    if isinstance(plan_data, str):
        # Try to parse as JSON first
        try:
            plan_data = json.loads(plan_data)
        except json.JSONDecodeError:
            # It's text from EXPLAIN ANALYZE
            return _parse_mysql_analyze_text(plan_data)

    # Handle JSON format
    if isinstance(plan_data, dict):
        if 'query_block' in plan_data:
            # EXPLAIN FORMAT=JSON structure
            return _parse_mysql_json_plan(plan_data)
        elif 'raw_output' in plan_data:
            # Already processed EXPLAIN ANALYZE text
            return plan_data

    raise ValueError(f"Unsupported MySQL plan format: {type(plan_data)}")


def _parse_mysql_json_plan(plan_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse EXPLAIN FORMAT=JSON output.

    MySQL JSON Plan Structure:
        {
            "query_block": {
                "select_id": 1,
                "cost_info": {
                    "query_cost": "15.50"
                },
                "table": {...} or "nested_loop": [...]
            }
        }

    Note: EXPLAIN FORMAT=JSON does NOT include actual runtime statistics.
    Only estimates are available.
    """
    query_block = plan_json.get('query_block', {})

    # Extract cost information
    cost_info = query_block.get('cost_info', {})
    query_cost = float(cost_info.get('query_cost', 0.0))

    # Parse the query block
    parsed_plan = _parse_query_block(query_block)

    # Add top-level metadata
    parsed_plan['metadata']['mysql_version'] = '8.0'
    parsed_plan['metadata']['plan_type'] = 'EXPLAIN FORMAT=JSON'
    parsed_plan['metadata']['total_cost'] = query_cost

    return parsed_plan


def _parse_query_block(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively parse MySQL query block.

    Query blocks can contain:
    - table: Single table access
    - nested_loop: Join operation
    - grouping_operation: GROUP BY
    - ordering_operation: ORDER BY
    - union_result: UNION operation
    """
    # Handle nested loop (join)
    if 'nested_loop' in block:
        return _parse_nested_loop(block['nested_loop'])

    # Handle single table access
    elif 'table' in block:
        return _parse_table(block['table'])

    # Handle grouping
    elif 'grouping_operation' in block:
        grouping_op = block['grouping_operation']
        return {
            'type': 'Group',
            'estimated_rows': 0,  # Not available in EXPLAIN FORMAT=JSON
            'actual_rows': 0,
            'children': [_parse_query_block(grouping_op)] if 'nested_loop' in grouping_op or 'table' in grouping_op else [],
            'metadata': {
                'group_by': grouping_op.get('group_by_subqueries', [])
            }
        }

    # Handle ordering
    elif 'ordering_operation' in block:
        ordering_op = block['ordering_operation']
        return {
            'type': 'Sort',
            'estimated_rows': 0,
            'actual_rows': 0,
            'children': [_parse_query_block(ordering_op)] if 'nested_loop' in ordering_op or 'table' in ordering_op else [],
            'metadata': {}
        }

    # Default
    else:
        return {
            'type': 'Unknown',
            'estimated_rows': 0,
            'actual_rows': 0,
            'children': [],
            'metadata': {}
        }


def _parse_nested_loop(nested_loop: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Parse MySQL nested loop (join) operation.

    MySQL represents joins as nested loops in the plan structure.
    """
    children = []

    for item in nested_loop:
        if 'table' in item:
            children.append(_parse_table(item['table']))
        elif 'nested_loop' in item:
            children.append(_parse_nested_loop(item['nested_loop']))

    # MySQL doesn't explicitly label join type in EXPLAIN FORMAT=JSON
    # We can infer it from access type
    join_type = 'Nested Loop Join'  # Default assumption

    return {
        'type': join_type,
        'estimated_rows': 0,  # Sum from children
        'actual_rows': 0,
        'children': children,
        'metadata': {
            'join_algorithm': 'nested_loop'
        }
    }


def _parse_table(table: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse MySQL table access.

    Table structure contains:
    - table_name: Table being accessed
    - access_type: ALL (full scan), index, range, etc.
    - key: Index used (if any)
    - rows_examined_per_scan: Estimated rows
    - filtered: Percentage of rows filtered
    - cost_info: Cost estimates
    """
    table_name = table.get('table_name', 'unknown')
    access_type = table.get('access_type', 'ALL')

    # Map MySQL access types to standardized scan types
    scan_type_map = {
        'ALL': 'Seq Scan',
        'index': 'Index Scan',
        'range': 'Index Range Scan',
        'ref': 'Index Scan',
        'eq_ref': 'Index Scan',
        'const': 'Index Scan',
        'unique_subquery': 'Index Scan',
        'index_subquery': 'Index Scan',
        'fulltext': 'Full Text Scan'
    }

    scan_type = scan_type_map.get(access_type, 'Table Scan')

    # Extract cost information
    cost_info = table.get('cost_info', {})
    read_cost = float(cost_info.get('read_cost', 0.0))
    eval_cost = float(cost_info.get('eval_cost', 0.0))
    total_cost = read_cost + eval_cost

    # Extract row estimates
    rows_examined = table.get('rows_examined_per_scan', 0)
    filtered_percent = table.get('filtered', 100.0)
    estimated_rows = int(rows_examined * (filtered_percent / 100.0))

    # Extract key information
    key_used = table.get('key')
    possible_keys = table.get('possible_keys', [])

    # Extract attached conditions
    attached_condition = table.get('attached_condition')

    return {
        'type': scan_type,
        'estimated_rows': estimated_rows,
        'actual_rows': 0,  # Not available in EXPLAIN FORMAT=JSON
        'estimated_cost_total': total_cost,
        'metadata': {
            'table_name': table_name,
            'access_type': access_type,
            'key': key_used,
            'possible_keys': possible_keys,
            'rows_examined_per_scan': rows_examined,
            'filtered_percent': filtered_percent,
            'attached_condition': attached_condition
        },
        'children': []
    }


def _parse_mysql_analyze_text(analyze_text: str) -> Dict[str, Any]:
    """
    Parse MySQL EXPLAIN ANALYZE text output.

    EXPLAIN ANALYZE provides actual execution statistics but in text format.

    Example output:
        -> Nested loop inner join  (cost=15.50 rows=100) (actual time=0.050..1.250 rows=95 loops=1)
            -> Table scan on orders  (cost=5.00 rows=100) (actual time=0.010..0.500 rows=100 loops=1)
            -> Index lookup on customer using PRIMARY (c_custkey=o.c_custkey)  (cost=0.50 rows=1) (actual time=0.002..0.003 rows=1 loops=100)

    This is more complex to parse than JSON, so we'll extract key information.
    """
    lines = analyze_text.strip().split('\n')

    # Extract root operator (first line)
    root_line = lines[0] if lines else ""

    # Parse root operator
    operator_type = _extract_operator_type(root_line)
    estimated_rows = _extract_estimated_rows(root_line)
    actual_rows = _extract_actual_rows(root_line)
    estimated_cost = _extract_estimated_cost(root_line)
    actual_time = _extract_actual_time(root_line)

    return {
        'type': operator_type,
        'estimated_rows': estimated_rows,
        'actual_rows': actual_rows,
        'estimated_cost_total': estimated_cost,
        'actual_time_total': actual_time,
        'children': [],  # TODO: Parse child operators
        'metadata': {
            'raw_explain': analyze_text,
            'plan_type': 'EXPLAIN ANALYZE'
        }
    }


def _extract_operator_type(line: str) -> str:
    """Extract operator type from EXPLAIN ANALYZE line."""
    # Extract text before (cost=...)
    if '(cost=' in line:
        operator_part = line.split('(cost=')[0].strip()
        # Remove leading arrow
        operator_part = operator_part.lstrip('-> ')
        return operator_part
    return 'Unknown'


def _extract_estimated_rows(line: str) -> int:
    """Extract estimated rows from EXPLAIN ANALYZE line."""
    # Format: (cost=15.50 rows=100)
    import re
    match = re.search(r'rows=(\d+)', line)
    return int(match.group(1)) if match else 0


def _extract_actual_rows(line: str) -> int:
    """Extract actual rows from EXPLAIN ANALYZE line."""
    # Format: (actual time=0.050..1.250 rows=95 loops=1)
    import re
    # Look for rows= after 'actual'
    actual_part = line.split('actual')[1] if 'actual' in line else ''
    match = re.search(r'rows=(\d+)', actual_part)
    return int(match.group(1)) if match else 0


def _extract_estimated_cost(line: str) -> float:
    """Extract estimated cost from EXPLAIN ANALYZE line."""
    # Format: (cost=15.50 rows=100)
    import re
    match = re.search(r'cost=([\d.]+)', line)
    return float(match.group(1)) if match else 0.0


def _extract_actual_time(line: str) -> float:
    """Extract actual time from EXPLAIN ANALYZE line."""
    # Format: (actual time=0.050..1.250 rows=95 loops=1)
    # Return the upper bound (total time)
    import re
    match = re.search(r'time=[\d.]+\.\.([\d.]+)', line)
    return float(match.group(1)) if match else 0.0


# Example usage and testing
if __name__ == '__main__':
    # Example MySQL EXPLAIN FORMAT=JSON output
    example_json = {
        "query_block": {
            "select_id": 1,
            "cost_info": {
                "query_cost": "15.50"
            },
            "nested_loop": [
                {
                    "table": {
                        "table_name": "orders",
                        "access_type": "ALL",
                        "rows_examined_per_scan": 100,
                        "rows_produced_per_join": 50,
                        "filtered": "50.00",
                        "cost_info": {
                            "read_cost": "4.00",
                            "eval_cost": "1.00",
                            "prefix_cost": "5.00",
                            "data_read_per_join": "800"
                        },
                        "attached_condition": "(o_orderdate > '1995-01-01')"
                    }
                },
                {
                    "table": {
                        "table_name": "customer",
                        "access_type": "eq_ref",
                        "possible_keys": ["PRIMARY"],
                        "key": "PRIMARY",
                        "used_key_parts": ["c_custkey"],
                        "key_length": "4",
                        "ref": ["orders.o_custkey"],
                        "rows_examined_per_scan": 1,
                        "rows_produced_per_join": 50,
                        "filtered": "100.00",
                        "cost_info": {
                            "read_cost": "10.00",
                            "eval_cost": "0.50",
                            "prefix_cost": "15.50",
                            "data_read_per_join": "800"
                        }
                    }
                }
            ]
        }
    }

    print("MySQL Plan Parser Example")
    print("=" * 70)

    # Parse the plan
    parsed = parse_mysql_plan(example_json)

    print(f"\nRoot Operator: {parsed['type']}")
    print(f"Estimated Rows: {parsed['estimated_rows']}")
    print(f"Total Cost: {parsed['metadata'].get('total_cost', 0):.2f}")
    print(f"Number of children: {len(parsed['children'])}")

    for i, child in enumerate(parsed['children']):
        print(f"\n  Child {i+1}:")
        print(f"    Type: {child['type']}")
        print(f"    Table: {child['metadata'].get('table_name', 'N/A')}")
        print(f"    Access Type: {child['metadata'].get('access_type', 'N/A')}")
        print(f"    Key: {child['metadata'].get('key', 'None')}")
        print(f"    Estimated Rows: {child['estimated_rows']}")

    print("\n" + "=" * 70)

    # Example EXPLAIN ANALYZE text
    example_analyze = """-> Nested loop inner join  (cost=15.50 rows=100) (actual time=0.050..1.250 rows=95 loops=1)
    -> Table scan on orders  (cost=5.00 rows=100) (actual time=0.010..0.500 rows=100 loops=1)
    -> Index lookup on customer using PRIMARY (c_custkey=o.c_custkey)  (cost=0.50 rows=1) (actual time=0.002..0.003 rows=1 loops=100)
"""

    print("\nEXPLAIN ANALYZE Parsing:")
    print("=" * 70)

    parsed_analyze = _parse_mysql_analyze_text(example_analyze)
    print(f"Operator: {parsed_analyze['type']}")
    print(f"Estimated Rows: {parsed_analyze['estimated_rows']}")
    print(f"Actual Rows: {parsed_analyze['actual_rows']}")
    print(f"Estimated Cost: {parsed_analyze['estimated_cost_total']:.2f}")
    print(f"Actual Time: {parsed_analyze['actual_time_total']:.3f} ms")

    # Calculate q-error
    from ..utils.qerror import calculate_qerror
    qerror = calculate_qerror(parsed_analyze['estimated_rows'], parsed_analyze['actual_rows'])
    print(f"Q-error: {qerror:.2f}")

    print("=" * 70)
