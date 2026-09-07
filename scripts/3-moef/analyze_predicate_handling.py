#!/usr/bin/env python3
"""
Predicate Pushdown and Filter Handling Analysis

Analyzes how effectively database optimizers push down filter predicates
and handle subqueries.

Paper Reference: Section 5.2.4 - "Predicate Handling"

Key Finding:
    PostgreSQL and Oracle effectively push down predicates to base table scans,
    reducing intermediate result sizes early in execution.

    MySQL sometimes applies filters late in the plan (after joins),
    resulting in unnecessary processing of rows that will be filtered out.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import argparse
import pandas as pd
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class PredicateHandlingAnalyzer:
    """
    Analyzes predicate pushdown and filter placement in execution plans.

    Evaluates:
    1. Predicate pushdown effectiveness (filters at base table scans)
    2. Filter placement in plan tree
    3. Subquery handling (decorrelation, materialization)
    4. ORM-generated filter patterns
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
        Analyze predicate handling from a single execution plan.

        Args:
            plan: Parsed execution plan

        Returns:
            Dictionary with predicate handling analysis
        """
        # Extract metadata
        metadata = plan.get('metadata', {})
        database = metadata.get('database', 'unknown')
        query_id = metadata.get('query_id', 'unknown')
        orm = metadata.get('orm', 'unknown')
        schema = metadata.get('schema', 'unknown')

        # Extract predicates/filters
        predicates = self._extract_predicates(plan)

        # Count predicate placement
        pushed_down = sum(1 for p in predicates if p['pushed_down'])
        applied_late = len(predicates) - pushed_down
        pushdown_ratio = pushed_down / len(predicates) if predicates else 0.0

        # Calculate filter selectivity
        filter_selectivities = []
        for pred in predicates:
            if pred.get('rows_removed') is not None and pred.get('rows_input') is not None:
                rows_input = pred['rows_input']
                rows_removed = pred['rows_removed']
                if rows_input > 0:
                    selectivity = (rows_input - rows_removed) / rows_input
                    filter_selectivities.append(selectivity)

        avg_selectivity = sum(filter_selectivities) / len(filter_selectivities) if filter_selectivities else 0.0

        # Extract subquery handling
        subquery_info = self._analyze_subqueries(plan)

        # Identify late filters (potential optimization opportunities)
        late_filters = [p for p in predicates if not p['pushed_down'] and p.get('rows_input', 0) > 1000]

        return {
            'database': database,
            'orm': orm,
            'schema': schema,
            'query_id': query_id,
            'total_predicates': len(predicates),
            'predicates_pushed_down': pushed_down,
            'predicates_applied_late': applied_late,
            'pushdown_ratio': pushdown_ratio,
            'avg_filter_selectivity': avg_selectivity,
            'subquery_count': subquery_info['subquery_count'],
            'subqueries_decorrelated': subquery_info['decorrelated'],
            'subqueries_materialized': subquery_info['materialized'],
            'late_filters_count': len(late_filters),
            'predicate_details': predicates,
            'metadata': metadata
        }

    def _extract_predicates(self, node: Dict[str, Any], predicates: Optional[List[Dict]] = None, depth: int = 0) -> List[Dict]:
        """
        Recursively extract all filter predicates from plan.

        Returns list of predicate information dictionaries.
        """
        if predicates is None:
            predicates = []

        if not isinstance(node, dict):
            return predicates

        node_type = node.get('type', '')

        # Check for filters in this node
        filters = node.get('filters', [])

        for filter_info in filters:
            # Determine if filter is pushed down (on a scan node)
            is_scan = any(scan_type in node_type.lower() for scan_type in
                         ['scan', 'seek', 'lookup'])

            predicate = {
                'condition': filter_info.get('condition', ''),
                'type': filter_info.get('type', 'unknown'),
                'pushed_down': is_scan,
                'node_type': node_type,
                'depth': depth,
                'rows_input': node.get('actual_rows', 0),
                'rows_removed': filter_info.get('rows_removed', None)
            }
            predicates.append(predicate)

        # Recurse into children
        for child in node.get('children', []):
            self._extract_predicates(child, predicates, depth + 1)

        return predicates

    def _analyze_subqueries(self, node: Dict[str, Any], subquery_info: Optional[Dict] = None) -> Dict[str, int]:
        """
        Analyze subquery handling strategies.

        Returns dictionary with subquery statistics.
        """
        if subquery_info is None:
            subquery_info = {
                'subquery_count': 0,
                'decorrelated': 0,
                'materialized': 0,
                'apply_operators': 0
            }

        if not isinstance(node, dict):
            return subquery_info

        node_type = node.get('type', '').lower()

        # Detect subquery patterns
        if 'subquery' in node_type or 'subplan' in node_type:
            subquery_info['subquery_count'] += 1

            if 'materialized' in node_type:
                subquery_info['materialized'] += 1

        # Detect apply operators (SQL Server subquery execution)
        if 'apply' in node_type:
            subquery_info['apply_operators'] += 1

        # Decorrelation detection: subquery converted to join
        # This is heuristic - would need query text analysis for certainty
        if 'join' in node_type:
            # Check for markers that suggest decorrelated subquery
            if node.get('metadata', {}).get('decorrelated', False):
                subquery_info['decorrelated'] += 1

        # Recurse into children
        for child in node.get('children', []):
            self._analyze_subqueries(child, subquery_info)

        return subquery_info

    def analyze_all_plans(self) -> pd.DataFrame:
        """
        Analyze all execution plans in the directory.

        Returns:
            DataFrame with predicate handling analysis for all plans
        """
        logger.info(f"Analyzing predicate handling in {self.plans_dir}")

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
        Generate comprehensive predicate handling analysis report.

        Includes:
        - Pushdown effectiveness by database
        - Filter selectivity analysis
        - Subquery handling strategies
        - Late filter identification
        """
        if df.empty:
            logger.warning("No data to generate report")
            return

        report = []
        report.append("=" * 80)
        report.append("PREDICATE PUSHDOWN AND FILTER HANDLING ANALYSIS")
        report.append("Paper Reference: Section 5.2.4 - Predicate Handling")
        report.append("=" * 80)
        report.append("")

        # Pushdown effectiveness by database
        report.append("1. Predicate Pushdown Effectiveness by Database:")
        report.append("-" * 80)
        report.append("   Higher ratio = better optimization (filters applied early)")
        report.append("")

        for database in df['database'].unique():
            db_df = df[df['database'] == database]
            avg_ratio = db_df['pushdown_ratio'].mean()
            avg_pushed = db_df['predicates_pushed_down'].mean()
            avg_late = db_df['predicates_applied_late'].mean()

            # Classification
            if avg_ratio > 0.8:
                quality = "Excellent"
                indicator = "✓"
            elif avg_ratio > 0.6:
                quality = "Good"
                indicator = "✓"
            elif avg_ratio > 0.4:
                quality = "Acceptable"
                indicator = "~"
            else:
                quality = "Poor"
                indicator = "⚠"

            report.append(f"  {indicator} {database:<15} Pushdown: {avg_ratio:>5.1%}  "
                        f"Avg pushed: {avg_pushed:.1f}  Avg late: {avg_late:.1f}  [{quality}]")

        report.append("\n")

        # Filter selectivity analysis
        report.append("2. Filter Selectivity Analysis:")
        report.append("-" * 80)
        report.append("   Lower selectivity = more rows filtered (more effective)")
        report.append("")

        for database in df['database'].unique():
            db_df = df[df['database'] == database]
            avg_sel = db_df['avg_filter_selectivity'].mean()

            # Note: Lower selectivity means more filtering
            efficiency = "High" if avg_sel < 0.5 else ("Medium" if avg_sel < 0.8 else "Low")

            report.append(f"  {database:<15} Avg selectivity: {avg_sel:>5.1%}  [{efficiency} filtering efficiency]")

        report.append("\n")

        # Subquery handling
        report.append("3. Subquery Handling Strategies:")
        report.append("-" * 80)

        total_subqueries = df['subquery_count'].sum()
        total_decorrelated = df['subqueries_decorrelated'].sum()
        total_materialized = df['subqueries_materialized'].sum()

        if total_subqueries > 0:
            report.append(f"   Total subqueries: {total_subqueries}")
            report.append(f"   Decorrelated: {total_decorrelated} ({total_decorrelated/total_subqueries*100:.1f}%)")
            report.append(f"   Materialized: {total_materialized} ({total_materialized/total_subqueries*100:.1f}%)")
            report.append("")

            for database in df['database'].unique():
                db_df = df[df['database'] == database]
                db_subqueries = db_df['subquery_count'].sum()
                db_decorrelated = db_df['subqueries_decorrelated'].sum()
                db_materialized = db_df['subqueries_materialized'].sum()

                if db_subqueries > 0:
                    report.append(f"  {database:<15} Total: {db_subqueries:>3}  "
                                f"Decorrelated: {db_decorrelated:>3}  "
                                f"Materialized: {db_materialized:>3}")
        else:
            report.append("   No subqueries detected in analyzed plans")

        report.append("\n")

        # Late filters (optimization opportunities)
        report.append("4. Late Filter Application (Optimization Opportunities):")
        report.append("-" * 80)

        total_late_filters = df['late_filters_count'].sum()

        if total_late_filters > 0:
            report.append(f"   Total late filters on large inputs: {total_late_filters}")
            report.append(f"   These represent opportunities to push filters earlier in the plan")
            report.append("")

            for database in df['database'].unique():
                db_df = df[df['database'] == database]
                db_late = db_df['late_filters_count'].sum()

                if db_late > 0:
                    indicator = "⚠"
                    report.append(f"  {indicator} {database:<15} {db_late:>3} late filters on large inputs")
        else:
            report.append("   ✓ No significant late filter issues detected")

        report.append("\n")

        # Paper findings validation
        report.append("5. Paper Findings Validation:")
        report.append("-" * 80)
        report.append("   PostgreSQL and Oracle: Effective predicate pushdown")
        report.append("   MySQL: Sometimes applies filters late")
        report.append("")

        # Check PostgreSQL
        pg_df = df[df['database'] == 'postgresql']
        if not pg_df.empty:
            pg_ratio = pg_df['pushdown_ratio'].mean()
            report.append(f"  PostgreSQL: {pg_ratio:.1%} pushdown ratio")
            if pg_ratio > 0.7:
                report.append(f"    Status: ✓ Effective pushdown confirmed")
            else:
                report.append(f"    Status: ~ Lower than expected")

        # Check MySQL
        mysql_df = df[df['database'] == 'mysql']
        if not mysql_df.empty:
            mysql_ratio = mysql_df['pushdown_ratio'].mean()
            mysql_late = mysql_df['late_filters_count'].sum()

            report.append(f"\n  MySQL: {mysql_ratio:.1%} pushdown ratio, {mysql_late} late filters")
            if mysql_ratio < 0.7 or mysql_late > 0:
                report.append(f"    Status: ⚠ Late filter application confirmed")
            else:
                report.append(f"    Status: ✓ Better than expected")

        # Check Oracle
        oracle_df = df[df['database'] == 'oracle']
        if not oracle_df.empty:
            oracle_ratio = oracle_df['pushdown_ratio'].mean()
            report.append(f"\n  Oracle: {oracle_ratio:.1%} pushdown ratio")
            if oracle_ratio > 0.7:
                report.append(f"    Status: ✓ Effective pushdown confirmed")

        report.append("\n")

        # Overall statistics
        report.append("6. Overall Statistics:")
        report.append("-" * 80)
        report.append(f"  Total plans analyzed: {len(df)}")
        report.append(f"  Total predicates: {df['total_predicates'].sum()}")
        report.append(f"  Predicates pushed down: {df['predicates_pushed_down'].sum()}")
        report.append(f"  Predicates applied late: {df['predicates_applied_late'].sum()}")
        report.append(f"  Overall pushdown ratio: {df['pushdown_ratio'].mean():.1%}")
        report.append(f"  Databases: {', '.join(df['database'].unique())}")
        report.append(f"  ORMs: {', '.join(df['orm'].unique())}")

        report.append("\n" + "=" * 80)

        # Write to file
        with open(output_file, 'w') as f:
            f.write('\n'.join(report))

        # Also print to console
        print('\n'.join(report))


def main():
    parser = argparse.ArgumentParser(
        description='Analyze predicate pushdown and filter handling from execution plans'
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
        default=Path('results/moef/predicate_handling_analysis.txt'),
        help='Output file for analysis report'
    )
    parser.add_argument(
        '--csv',
        type=Path,
        default=Path('results/moef/predicate_handling.csv'),
        help='Output CSV file for predicate handling data'
    )

    args = parser.parse_args()

    # Initialize analyzer
    analyzer = PredicateHandlingAnalyzer(args.plans_dir)

    # Analyze all plans
    logger.info("Analyzing predicate handling...")
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
    logger.info(f"\nPredicate handling data saved to {args.csv}")
    logger.info(f"Analysis report saved to {args.output}")


if __name__ == '__main__':
    main()
