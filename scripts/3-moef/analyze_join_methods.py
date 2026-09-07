#!/usr/bin/env python3
"""
Join Method Selection Analysis

Analyzes join method choices and their correlation with cardinality estimation quality.

Paper Reference: Section 4.1 - "Mechanistic Analysis", Section 5.2.2 - "Join Method Selection"

Key Finding:
    High q-error (poor cardinality estimation) leads to suboptimal join method selection.

    MySQL Q8:
    - Q-error: 8.7 (poor estimation)
    - Result: Selects Nested Loop joins for large inputs
    - Impact: 117 seconds execution time

    PostgreSQL Q8:
    - Q-error: 1.4 (excellent estimation)
    - Result: Selects Hash joins for large inputs
    - Impact: 6.3 seconds execution time

    18× performance difference explained by join method selection!
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import argparse
import pandas as pd
from collections import defaultdict, Counter
import numpy as np

# Add project root to path
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.moef.utils.qerror import calculate_qerror
from scripts.moef.utils.mechanism_extraction import extract_join_methods, JoinMethod

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class JoinMethodAnalyzer:
    """
    Analyzes join method selection from execution plans.

    Correlates join method choices with:
    1. Cardinality estimation quality (q-error)
    2. Input sizes
    3. Query performance
    """

    def __init__(self, plans_dir: Path):
        """
        Initialize analyzer.

        Args:
            plans_dir: Directory containing execution plans
        """
        self.plans_dir = plans_dir
        self.results = []

    def analyze_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze join method selection from a single execution plan.

        Args:
            plan: Parsed execution plan

        Returns:
            Dictionary with join method analysis
        """
        # Extract metadata
        metadata = plan.get('metadata', {})
        database = metadata.get('database', 'unknown')
        query_id = metadata.get('query_id', 'unknown')
        orm = metadata.get('orm', 'unknown')
        schema = metadata.get('schema', 'unknown')

        # Extract all joins with their details
        joins = self._extract_join_details(plan)

        # Count join method distribution
        join_methods = [j['method'] for j in joins]
        method_distribution = Counter(join_methods)

        # Calculate average q-error for joins
        join_qerrors = [j['qerror'] for j in joins if j['qerror'] is not None and not np.isinf(j['qerror'])]
        avg_qerror = np.mean(join_qerrors) if join_qerrors else 0.0
        max_qerror = max(join_qerrors) if join_qerrors else 0.0

        # Identify suboptimal join choices
        suboptimal_joins = self._identify_suboptimal_joins(joins)

        # Calculate total join cost
        total_join_cost = sum(j['cost'] for j in joins)

        return {
            'database': database,
            'orm': orm,
            'schema': schema,
            'query_id': query_id,
            'num_joins': len(joins),
            'join_method_distribution': dict(method_distribution),
            'dominant_join_method': method_distribution.most_common(1)[0][0] if method_distribution else 'None',
            'avg_join_qerror': avg_qerror,
            'max_join_qerror': max_qerror,
            'total_join_cost': total_join_cost,
            'suboptimal_joins': len(suboptimal_joins),
            'join_details': joins,
            'metadata': metadata
        }

    def _extract_join_details(self, node: Dict[str, Any], joins: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Recursively extract all join operations with their details.

        Returns list of join information dictionaries.
        """
        if joins is None:
            joins = []

        if not isinstance(node, dict):
            return joins

        node_type = node.get('type', '')

        # Check if this is a join operation
        if 'join' in node_type.lower():
            # Determine join method
            if 'nested loop' in node_type.lower():
                method = 'Nested Loop'
            elif 'hash' in node_type.lower():
                method = 'Hash Join'
            elif 'merge' in node_type.lower():
                method = 'Merge Join'
            elif 'index' in node_type.lower():
                method = 'Index Nested Loop'
            else:
                method = 'Unknown'

            # Calculate q-error for this join
            estimated = node.get('estimated_rows', 0)
            actual = node.get('actual_rows', 0)
            qerror = calculate_qerror(estimated, actual) if estimated > 0 and actual > 0 else None

            join_info = {
                'method': method,
                'estimated_rows': estimated,
                'actual_rows': actual,
                'qerror': qerror,
                'cost': node.get('estimated_cost_total', 0.0),
                'join_type': node.get('metadata', {}).get('join_type', 'inner')
            }
            joins.append(join_info)

        # Recurse into children
        for child in node.get('children', []):
            self._extract_join_details(child, joins)

        return joins

    def _identify_suboptimal_joins(self, joins: List[Dict]) -> List[Dict]:
        """
        Identify likely suboptimal join choices.

        Heuristics:
        1. Nested Loop with large input (>1000 rows) and high q-error (>5.0)
        2. Hash Join with very small input (<10 rows)
        3. Any join with q-error > 10.0
        """
        suboptimal = []

        for join in joins:
            method = join['method']
            actual_rows = join['actual_rows']
            qerror = join.get('qerror', 1.0)

            if qerror is None or np.isinf(qerror):
                continue

            # Nested Loop with large input and poor estimation
            if method == 'Nested Loop' and actual_rows > 1000 and qerror > 5.0:
                suboptimal.append({
                    **join,
                    'reason': f'Nested Loop on {actual_rows} rows with q-error {qerror:.1f}'
                })

            # Hash Join on very small input (overhead not justified)
            elif method == 'Hash Join' and actual_rows < 10:
                suboptimal.append({
                    **join,
                    'reason': f'Hash Join on only {actual_rows} rows (overhead likely > benefit)'
                })

            # Any join with very high q-error
            elif qerror > 10.0:
                suboptimal.append({
                    **join,
                    'reason': f'Very poor cardinality estimation (q-error {qerror:.1f})'
                })

        return suboptimal

    def analyze_all_plans(self) -> pd.DataFrame:
        """
        Analyze all execution plans in the directory.

        Returns:
            DataFrame with join method analysis for all plans
        """
        logger.info(f"Analyzing join methods in {self.plans_dir}")

        # Find all plan JSON files
        plan_files = list(self.plans_dir.rglob('*_plan.json'))
        logger.info(f"Found {len(plan_files)} plan files")

        for plan_file in plan_files:
            try:
                with open(plan_file, 'r') as f:
                    plan = json.load(f)

                analysis = self.analyze_plan(plan)
                self.results.append(analysis)

            except Exception as e:
                logger.error(f"Failed to analyze {plan_file}: {e}")

        # Convert to DataFrame
        if self.results:
            df = pd.DataFrame(self.results)
            return df
        else:
            logger.warning("No results to analyze")
            return pd.DataFrame()

    def generate_report(self, df: pd.DataFrame, output_file: Path):
        """
        Generate comprehensive join method analysis report.

        Includes:
        - Join method distribution by database
        - Correlation between q-error and join method
        - Suboptimal join identification
        - Paper findings validation
        """
        if df.empty:
            logger.warning("No data to generate report")
            return

        report = []
        report.append("=" * 80)
        report.append("JOIN METHOD SELECTION ANALYSIS")
        report.append("Paper Reference: Section 5.2.2 - Join Method Selection")
        report.append("=" * 80)
        report.append("")

        # Join method distribution by database
        report.append("1. Join Method Distribution by Database:")
        report.append("-" * 80)

        for database in df['database'].unique():
            db_df = df[df['database'] == database]

            # Aggregate join method counts
            all_methods = []
            for methods_dict in db_df['join_method_distribution']:
                all_methods.extend([method for method, count in methods_dict.items() for _ in range(count)])

            method_counts = Counter(all_methods)
            total_joins = sum(method_counts.values())

            report.append(f"\n  {database.upper()} ({total_joins} total joins):")
            for method, count in method_counts.most_common():
                percentage = (count / total_joins) * 100 if total_joins > 0 else 0
                bar = "█" * int(percentage / 2)
                report.append(f"    {method:<20} {count:>5} ({percentage:>5.1f}%) {bar}")

        report.append("\n")

        # Q-error vs Join Method correlation
        report.append("2. Cardinality Estimation Quality (Q-error) by Database:")
        report.append("-" * 80)
        report.append("   Lower q-error = better estimation = better join choices")
        report.append("")

        for database in df['database'].unique():
            db_df = df[df['database'] == database]
            avg_qerror = db_df['avg_join_qerror'].mean()
            max_qerror = db_df['max_join_qerror'].max()

            # Classification
            if avg_qerror < 2.0:
                quality = "Excellent"
                indicator = "✓"
            elif avg_qerror < 5.0:
                quality = "Good"
                indicator = "✓"
            elif avg_qerror < 10.0:
                quality = "Acceptable"
                indicator = "~"
            else:
                quality = "Poor"
                indicator = "⚠"

            report.append(f"  {indicator} {database:<15} Avg Q-error: {avg_qerror:>6.2f}  "
                        f"Max: {max_qerror:>6.2f}  [{quality}]")

        report.append("\n")

        # Suboptimal joins analysis
        report.append("3. Suboptimal Join Choices:")
        report.append("-" * 80)

        total_suboptimal = df['suboptimal_joins'].sum()
        total_joins = df['num_joins'].sum()
        suboptimal_rate = (total_suboptimal / total_joins) * 100 if total_joins > 0 else 0

        report.append(f"   Total suboptimal joins: {total_suboptimal} / {total_joins} ({suboptimal_rate:.1f}%)")
        report.append("")

        for database in df['database'].unique():
            db_df = df[df['database'] == database]
            db_suboptimal = db_df['suboptimal_joins'].sum()
            db_total_joins = db_df['num_joins'].sum()
            db_rate = (db_suboptimal / db_total_joins) * 100 if db_total_joins > 0 else 0

            indicator = "✓" if db_rate < 10 else ("~" if db_rate < 30 else "⚠")
            report.append(f"  {indicator} {database:<15} {db_suboptimal:>4} / {db_total_joins:>4} ({db_rate:>5.1f}%)")

        report.append("\n")

        # Paper findings validation
        report.append("4. Paper Findings Validation:")
        report.append("-" * 80)
        report.append("   MySQL Q8: q-error = 8.7, selects Nested Loop → slow")
        report.append("   PostgreSQL Q8: q-error = 1.4, selects Hash Join → fast")
        report.append("")

        # Check MySQL Q8
        mysql_q8 = df[(df['database'] == 'mysql') & (df['query_id'] == 'Q8')]
        if not mysql_q8.empty:
            q8_row = mysql_q8.iloc[0]
            q8_qerror = q8_row['avg_join_qerror']
            q8_methods = q8_row['join_method_distribution']

            report.append(f"  MySQL Q8:")
            report.append(f"    Avg Q-error: {q8_qerror:.2f} (Paper: 8.7)")
            report.append(f"    Join methods: {q8_methods}")

            if q8_qerror > 5.0:
                report.append(f"    Status: ⚠ Poor estimation confirmed")
            else:
                report.append(f"    Status: ✓ Better than paper (possibly improved optimizer)")

        # Check PostgreSQL Q8
        pg_q8 = df[(df['database'] == 'postgresql') & (df['query_id'] == 'Q8')]
        if not pg_q8.empty:
            q8_row = pg_q8.iloc[0]
            q8_qerror = q8_row['avg_join_qerror']
            q8_methods = q8_row['join_method_distribution']

            report.append(f"\n  PostgreSQL Q8:")
            report.append(f"    Avg Q-error: {q8_qerror:.2f} (Paper: 1.4)")
            report.append(f"    Join methods: {q8_methods}")

            if q8_qerror < 2.0:
                report.append(f"    Status: ✓ Excellent estimation confirmed")
            else:
                report.append(f"    Status: ~ Higher than paper")

        report.append("\n")

        # Statistics summary
        report.append("5. Overall Statistics:")
        report.append("-" * 80)
        report.append(f"  Total plans analyzed: {len(df)}")
        report.append(f"  Total joins analyzed: {total_joins}")
        report.append(f"  Databases: {', '.join(df['database'].unique())}")
        report.append(f"  ORMs: {', '.join(df['orm'].unique())}")
        report.append(f"  Avg joins per query: {df['num_joins'].mean():.1f}")
        report.append(f"  Global avg q-error: {df['avg_join_qerror'].mean():.2f}")
        report.append(f"  Suboptimal join rate: {suboptimal_rate:.1f}%")

        report.append("\n" + "=" * 80)

        # Write to file
        with open(output_file, 'w') as f:
            f.write('\n'.join(report))

        # Also print to console
        print('\n'.join(report))


def main():
    parser = argparse.ArgumentParser(
        description='Analyze join method selection from execution plans'
    )
    parser.add_argument(
        '--plans-dir',
        type=Path,
        default=Path('results/execution_plans'),
        help='Directory containing execution plans'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('results/moef/join_methods_analysis.txt'),
        help='Output file for analysis report'
    )
    parser.add_argument(
        '--csv',
        type=Path,
        default=Path('results/moef/join_methods.csv'),
        help='Output CSV file for join method data'
    )

    args = parser.parse_args()

    # Initialize analyzer
    analyzer = JoinMethodAnalyzer(args.plans_dir)

    # Analyze all plans
    logger.info("Analyzing join method selection...")
    df = analyzer.analyze_all_plans()

    if df.empty:
        logger.error("No plans found to analyze")
        return

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv.parent.mkdir(parents=True, exist_ok=True)

    # Generate report
    analyzer.generate_report(df, args.output)

    # Save CSV
    df.to_csv(args.csv, index=False)
    logger.info(f"\nJoin method data saved to {args.csv}")
    logger.info(f"Analysis report saved to {args.output}")


if __name__ == '__main__':
    main()
