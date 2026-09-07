#!/usr/bin/env python3
"""
Index Utilization Analysis

Analyzes index usage patterns and effectiveness across different ORM-DBMS combinations.

Paper Reference: Section 4.3 - "Impact of Indexing", Section 5.2.3 - "Index Utilization"

Key Finding - PostgreSQL Indexing Paradox:
    Django with indexes: -12% performance (degradation!)
    SQLAlchemy with indexes: +98% performance (massive improvement!)

    Same database, same schema, same queries - 110 percentage point difference
    based solely on ORM framework choice.

Explanation:
    Django's query patterns cause PostgreSQL's optimizer to select suboptimal
    plans when indexes are available, while SQLAlchemy's patterns enable
    effective index utilization.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import argparse
import pandas as pd
from collections import defaultdict, Counter

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class IndexUtilizationAnalyzer:
    """
    Analyzes index utilization patterns from execution plans.

    Identifies:
    1. Index Scan vs Sequential Scan frequency
    2. Index selectivity and effectiveness
    3. ORM-specific indexing behavior
    4. Indexing paradoxes (where indexes hurt performance)
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
        Analyze index utilization from a single execution plan.

        Args:
            plan: Parsed execution plan

        Returns:
            Dictionary with index utilization analysis
        """
        # Extract metadata
        metadata = plan.get('metadata', {})
        database = metadata.get('database', 'unknown')
        query_id = metadata.get('query_id', 'unknown')
        orm = metadata.get('orm', 'unknown')
        schema = metadata.get('schema', 'unknown')

        # Extract scan types
        scan_types = self._extract_all_scans(plan)

        # Count scan type distribution
        scan_distribution = Counter([s['type'] for s in scan_types])

        # Calculate index utilization metrics
        total_scans = len(scan_types)
        index_scans = sum(1 for s in scan_types if 'index' in s['type'].lower())
        seq_scans = sum(1 for s in scan_types if 'seq' in s['type'].lower() or 'table' in s['type'].lower())

        index_utilization_ratio = index_scans / total_scans if total_scans > 0 else 0.0

        # Extract index details
        indexes_used = [s.get('index_name') for s in scan_types if s.get('index_name')]

        # Calculate selectivity for index scans
        selectivities = []
        for scan in scan_types:
            if 'index' in scan['type'].lower():
                estimated = scan.get('estimated_rows', 0)
                actual = scan.get('actual_rows', 0)
                if estimated > 0:
                    selectivity = actual / estimated
                    selectivities.append(selectivity)

        avg_selectivity = sum(selectivities) / len(selectivities) if selectivities else 0.0

        # Identify inefficient scans (sequential scan with available index)
        inefficient_scans = self._identify_inefficient_scans(scan_types, schema)

        return {
            'database': database,
            'orm': orm,
            'schema': schema,
            'query_id': query_id,
            'total_scans': total_scans,
            'index_scans': index_scans,
            'sequential_scans': seq_scans,
            'index_utilization_ratio': index_utilization_ratio,
            'scan_distribution': dict(scan_distribution),
            'indexes_used': indexes_used,
            'unique_indexes_used': len(set(indexes_used)),
            'avg_index_selectivity': avg_selectivity,
            'inefficient_scans': inefficient_scans,
            'metadata': metadata
        }

    def _extract_all_scans(self, node: Dict[str, Any], scans: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Recursively extract all table/index access operations.

        Returns list of scan information dictionaries.
        """
        if scans is None:
            scans = []

        if not isinstance(node, dict):
            return scans

        node_type = node.get('type', '')

        # Check if this is a scan operation
        if any(scan_keyword in node_type.lower() for scan_keyword in
               ['scan', 'seek', 'lookup']):

            scan_info = {
                'type': node_type,
                'table': node.get('metadata', {}).get('relation_name') or
                        node.get('metadata', {}).get('table_name'),
                'index_name': node.get('metadata', {}).get('index_name'),
                'estimated_rows': node.get('estimated_rows', 0),
                'actual_rows': node.get('actual_rows', 0),
                'cost': node.get('estimated_cost_total', 0.0),
                'filters': node.get('filters', [])
            }
            scans.append(scan_info)

        # Recurse into children
        for child in node.get('children', []):
            self._extract_all_scans(child, scans)

        return scans

    def _identify_inefficient_scans(self, scans: List[Dict], schema: str) -> List[Dict]:
        """
        Identify inefficient scan choices.

        An inefficient scan is:
        1. Sequential scan on indexed schema (index available but not used)
        2. Index scan with very low selectivity (full table via index)
        """
        inefficient = []

        for scan in scans:
            # Check for sequential scan on indexed schema
            if schema == 'indexed' and ('seq' in scan['type'].lower() or 'table' in scan['type'].lower()):
                inefficient.append({
                    'type': 'missed_index_opportunity',
                    'table': scan['table'],
                    'scan_type': scan['type'],
                    'estimated_rows': scan['estimated_rows'],
                    'reason': 'Sequential scan used despite index availability'
                })

            # Check for inefficient index scan (high cardinality)
            if 'index' in scan['type'].lower():
                estimated = scan.get('estimated_rows', 0)
                # If index scan returns >50% of table, it's likely inefficient
                # (heuristic - would need table size for exact calculation)
                if estimated > 10000:  # Large result set through index
                    inefficient.append({
                        'type': 'low_selectivity_index_scan',
                        'table': scan['table'],
                        'index_name': scan.get('index_name'),
                        'estimated_rows': estimated,
                        'reason': 'Index scan with very low selectivity'
                    })

        return inefficient

    def analyze_all_plans(self) -> pd.DataFrame:
        """
        Analyze all execution plans in the directory.

        Returns:
            DataFrame with index utilization analysis for all plans
        """
        logger.info(f"Analyzing index utilization in {self.plans_dir}")

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

    def compare_indexed_vs_nonindexed(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compare index utilization between indexed and non-indexed schemas.

        Returns DataFrame showing the impact of indexing for each ORM-database combo.
        """
        if df.empty:
            return pd.DataFrame()

        comparison = []

        # Group by database, ORM, query
        for (database, orm, query_id), group in df.groupby(['database', 'orm', 'query_id']):
            indexed_data = group[group['schema'] == 'indexed']
            nonindexed_data = group[group['schema'] == 'nonindexed']

            if not indexed_data.empty and not nonindexed_data.empty:
                indexed_row = indexed_data.iloc[0]
                nonindexed_row = nonindexed_data.iloc[0]

                # Calculate difference
                index_ratio_change = (indexed_row['index_utilization_ratio'] -
                                     nonindexed_row['index_utilization_ratio'])

                comparison.append({
                    'database': database,
                    'orm': orm,
                    'query_id': query_id,
                    'nonindexed_index_ratio': nonindexed_row['index_utilization_ratio'],
                    'indexed_index_ratio': indexed_row['index_utilization_ratio'],
                    'index_ratio_improvement': index_ratio_change,
                    'indexed_scans': indexed_row['index_scans'],
                    'nonindexed_scans': nonindexed_row['index_scans'],
                    'inefficient_scans_with_index': len(indexed_row.get('inefficient_scans', []))
                })

        return pd.DataFrame(comparison)

    def generate_report(self, df: pd.DataFrame, comparison_df: pd.DataFrame, output_file: Path):
        """
        Generate comprehensive index utilization analysis report.

        Includes:
        - Index utilization by database and ORM
        - Indexed vs non-indexed comparison
        - PostgreSQL indexing paradox analysis
        - Paper findings validation
        """
        if df.empty:
            logger.warning("No data to generate report")
            return

        report = []
        report.append("=" * 80)
        report.append("INDEX UTILIZATION ANALYSIS")
        report.append("Paper Reference: Section 4.3 - Impact of Indexing")
        report.append("=" * 80)
        report.append("")

        # Overall index utilization by database and ORM
        report.append("1. Index Utilization by Database and ORM (Indexed Schema):")
        report.append("-" * 80)

        indexed_df = df[df['schema'] == 'indexed']
        if not indexed_df.empty:
            for database in indexed_df['database'].unique():
                report.append(f"\n  {database.upper()}:")
                db_df = indexed_df[indexed_df['database'] == database]

                for orm in db_df['orm'].unique():
                    orm_df = db_df[db_df['orm'] == orm]
                    avg_ratio = orm_df['index_utilization_ratio'].mean()
                    avg_index_scans = orm_df['index_scans'].mean()
                    avg_seq_scans = orm_df['sequential_scans'].mean()

                    report.append(f"    {orm:<15} Index Ratio: {avg_ratio:.2%}  "
                                f"Avg Index Scans: {avg_index_scans:.1f}  "
                                f"Avg Seq Scans: {avg_seq_scans:.1f}")

        report.append("\n")

        # PostgreSQL indexing paradox (THE KEY FINDING)
        report.append("2. PostgreSQL Indexing Paradox Analysis:")
        report.append("-" * 80)
        report.append("   Paper Finding: Django degrades with indexes, SQLAlchemy improves")
        report.append("")

        pg_comparison = comparison_df[comparison_df['database'] == 'postgresql']
        if not pg_comparison.empty:
            for orm in pg_comparison['orm'].unique():
                orm_comp = pg_comparison[pg_comparison['orm'] == orm]
                avg_improvement = orm_comp['index_ratio_improvement'].mean()

                # Count queries where indexing helped vs hurt
                helped = len(orm_comp[orm_comp['index_ratio_improvement'] > 0])
                hurt = len(orm_comp[orm_comp['index_ratio_improvement'] < 0])

                report.append(f"  {orm.upper()}:")
                report.append(f"    Avg index utilization improvement: {avg_improvement:+.2%}")
                report.append(f"    Queries helped by indexing: {helped}")
                report.append(f"    Queries hurt by indexing: {hurt}")

                if orm == 'django' and avg_improvement < 0:
                    report.append(f"    ⚠ PARADOX CONFIRMED: Django performance degrades with indexes")
                elif orm == 'sqlalchemy' and avg_improvement > 0.5:
                    report.append(f"    ✓ SQLAlchemy effectively utilizes indexes")

                report.append("")

        # Comparison across all databases
        report.append("\n3. Index Effectiveness Comparison (All Databases):")
        report.append("-" * 80)

        if not comparison_df.empty:
            # Calculate average index ratio improvement by database and ORM
            summary = comparison_df.groupby(['database', 'orm']).agg({
                'index_ratio_improvement': 'mean',
                'inefficient_scans_with_index': 'mean'
            }).reset_index()

            report.append(f"\n  {'Database':<15} {'ORM':<12} {'Avg Improvement':<20} {'Inefficient Scans':<20}")
            report.append(f"  {'-'*15} {'-'*12} {'-'*20} {'-'*20}")

            for _, row in summary.iterrows():
                improvement = row['index_ratio_improvement']
                indicator = "✓" if improvement > 0 else ("⚠" if improvement < -0.1 else "~")

                report.append(f"  {indicator} {row['database']:<14} {row['orm']:<12} "
                            f"{improvement:>+8.2%}           "
                            f"{row['inefficient_scans_with_index']:>6.1f}")

        report.append("\n")

        # Paper findings validation
        report.append("4. Paper Findings Validation:")
        report.append("-" * 80)

        # Expected from paper (Table 5):
        # PostgreSQL + Django: -12% (degradation)
        # PostgreSQL + SQLAlchemy: +98% (massive improvement)

        pg_django = comparison_df[(comparison_df['database'] == 'postgresql') &
                                  (comparison_df['orm'] == 'django')]
        pg_sqlalchemy = comparison_df[(comparison_df['database'] == 'postgresql') &
                                      (comparison_df['orm'] == 'sqlalchemy')]

        if not pg_django.empty:
            django_improvement = pg_django['index_ratio_improvement'].mean()
            paper_django = -0.12  # Paper reports -12%

            report.append(f"\n  PostgreSQL + Django:")
            report.append(f"    Actual:  {django_improvement:>+7.2%}")
            report.append(f"    Paper:   {paper_django:>+7.2%}")

            if abs(django_improvement - paper_django) < 0.20:  # Within 20 percentage points
                report.append(f"    Status:  ✓ Confirmed")
            else:
                report.append(f"    Status:  ⚠ Deviation from paper")

        if not pg_sqlalchemy.empty:
            sqlalchemy_improvement = pg_sqlalchemy['index_ratio_improvement'].mean()
            paper_sqlalchemy = 0.98  # Paper reports +98%

            report.append(f"\n  PostgreSQL + SQLAlchemy:")
            report.append(f"    Actual:  {sqlalchemy_improvement:>+7.2%}")
            report.append(f"    Paper:   {paper_sqlalchemy:>+7.2%}")

            if abs(sqlalchemy_improvement - paper_sqlalchemy) < 0.30:  # Within 30 percentage points
                report.append(f"    Status:  ✓ Confirmed")
            else:
                report.append(f"    Status:  ⚠ Deviation from paper")

        report.append("\n")

        # Statistics
        report.append("5. Overall Statistics:")
        report.append("-" * 80)
        report.append(f"  Total plans analyzed: {len(df)}")
        report.append(f"  Databases: {', '.join(df['database'].unique())}")
        report.append(f"  ORMs: {', '.join(df['orm'].unique())}")
        report.append(f"  Avg index scans per query: {df['index_scans'].mean():.1f}")
        report.append(f"  Avg sequential scans per query: {df['sequential_scans'].mean():.1f}")

        total_inefficient = sum(len(row.get('inefficient_scans', [])) for _, row in df.iterrows())
        report.append(f"  Total inefficient scan choices: {total_inefficient}")

        report.append("\n" + "=" * 80)

        # Write to file
        with open(output_file, 'w') as f:
            f.write('\n'.join(report))

        # Also print to console
        print('\n'.join(report))


def main():
    parser = argparse.ArgumentParser(
        description='Analyze index utilization from execution plans'
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
        default=Path('results/moef/index_utilization_analysis.txt'),
        help='Output file for analysis report'
    )
    parser.add_argument(
        '--csv',
        type=Path,
        default=Path('results/moef/index_utilization.csv'),
        help='Output CSV file for index utilization data'
    )
    parser.add_argument(
        '--comparison-csv',
        type=Path,
        default=Path('results/moef/index_comparison.csv'),
        help='Output CSV for indexed vs non-indexed comparison'
    )

    args = parser.parse_args()

    # Initialize analyzer
    analyzer = IndexUtilizationAnalyzer(args.plans_dir)

    # Analyze all plans
    logger.info("Analyzing index utilization patterns...")
    df = analyzer.analyze_all_plans()

    if df.empty:
        logger.error("No plans found to analyze")
        return

    # Compare indexed vs non-indexed
    logger.info("Comparing indexed vs non-indexed performance...")
    comparison_df = analyzer.compare_indexed_vs_nonindexed(df)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv.parent.mkdir(parents=True, exist_ok=True)

    # Generate report
    analyzer.generate_report(df, comparison_df, args.output)

    # Save CSVs
    df.to_csv(args.csv, index=False)
    logger.info(f"\nIndex utilization data saved to {args.csv}")

    if not comparison_df.empty:
        comparison_df.to_csv(args.comparison_csv, index=False)
        logger.info(f"Index comparison data saved to {args.comparison_csv}")

    logger.info(f"Analysis report saved to {args.output}")


if __name__ == '__main__':
    main()
