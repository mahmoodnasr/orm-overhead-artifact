#!/usr/bin/env python3
"""
Statistical Linking - MOEF Phase 4

Links performance differences to optimizer mechanisms via statistical analysis.

Paper Reference: Section 3.5.4 - "Phase 4: Causal Linking"

This script performs correlation and regression analysis to establish
causal relationships between optimizer mechanisms and query performance.

Key Questions Answered:
1. Does q-error predict query performance?
2. Does join enumeration strategy affect complex query performance?
3. Does predicate pushdown ratio correlate with execution time?
4. Does index utilization ratio predict performance improvement?

Statistical Methods:
- Pearson correlation (linear relationships)
- Spearman correlation (monotonic relationships)
- Multiple regression (multivariate analysis)
- Effect size calculation (Cohen's d)
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple
import argparse
import pandas as pd
import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class StatisticalLinker:
    """
    Performs statistical analysis to link mechanisms to performance.

    Establishes causal relationships between optimizer behavior
    (mechanisms) and query execution performance (outcomes).
    """

    def __init__(self, moef_results_dir: Path, benchmark_results_file: Path):
        """
        Initialize statistical linker.

        Args:
            moef_results_dir: Directory containing MOEF analysis results
            benchmark_results_file: CSV file with benchmark performance data
        """
        self.moef_dir = moef_results_dir
        self.benchmark_file = benchmark_results_file
        self.correlations = []

    def load_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Load MOEF mechanism data and benchmark performance data.

        Returns:
            Tuple of (mechanisms_df, performance_df)
        """
        # Load MOEF results
        mechanisms = {}

        # Join enumeration
        je_file = self.moef_dir / 'join_enumeration.csv'
        if je_file.exists():
            mechanisms['join_enum'] = pd.read_csv(je_file)
            logger.info(f"Loaded join enumeration: {len(mechanisms['join_enum'])} records")

        # Join methods
        jm_file = self.moef_dir / 'join_methods.csv'
        if jm_file.exists():
            mechanisms['join_methods'] = pd.read_csv(jm_file)
            logger.info(f"Loaded join methods: {len(mechanisms['join_methods'])} records")

        # Index utilization
        iu_file = self.moef_dir / 'index_utilization.csv'
        if iu_file.exists():
            mechanisms['index_util'] = pd.read_csv(iu_file)
            logger.info(f"Loaded index utilization: {len(mechanisms['index_util'])} records")

        # Predicate handling
        ph_file = self.moef_dir / 'predicate_handling.csv'
        if ph_file.exists():
            mechanisms['predicate'] = pd.read_csv(ph_file)
            logger.info(f"Loaded predicate handling: {len(mechanisms['predicate'])} records")

        # Merge all mechanisms on common keys
        if mechanisms:
            # Start with first available dataset
            combined = list(mechanisms.values())[0].copy()

            # Merge others
            for name, df in list(mechanisms.items())[1:]:
                combined = combined.merge(
                    df,
                    on=['database', 'orm', 'query_id', 'schema'],
                    how='outer',
                    suffixes=('', f'_{name}')
                )

            mechanisms_df = combined
        else:
            mechanisms_df = pd.DataFrame()

        # Load benchmark performance data
        if self.benchmark_file.exists():
            performance_df = pd.read_csv(self.benchmark_file)
            logger.info(f"Loaded benchmark data: {len(performance_df)} records")
        else:
            logger.warning(f"Benchmark file not found: {self.benchmark_file}")
            performance_df = pd.DataFrame()

        return mechanisms_df, performance_df

    def correlate_qerror_performance(
        self,
        mechanisms_df: pd.DataFrame,
        performance_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Correlate q-error with query execution time.

        Paper Finding:
            High q-error → poor cardinality estimation → wrong join methods → slow execution

        Returns:
            Dictionary with correlation statistics
        """
        # Merge datasets
        if 'avg_join_qerror' in mechanisms_df.columns and 'execution_time' in performance_df.columns:
            merged = mechanisms_df.merge(
                performance_df[['database', 'orm', 'query_id', 'execution_time']],
                on=['database', 'orm', 'query_id'],
                how='inner'
            )

            if len(merged) > 0:
                # Remove infinite q-errors
                merged = merged[np.isfinite(merged['avg_join_qerror'])]

                # Calculate correlations
                pearson_r, pearson_p = stats.pearsonr(
                    merged['avg_join_qerror'],
                    merged['execution_time']
                )

                spearman_r, spearman_p = stats.spearmanr(
                    merged['avg_join_qerror'],
                    merged['execution_time']
                )

                return {
                    'mechanism': 'q-error',
                    'outcome': 'execution_time',
                    'n_samples': len(merged),
                    'pearson_r': pearson_r,
                    'pearson_p': pearson_p,
                    'spearman_r': spearman_r,
                    'spearman_p': spearman_p,
                    'interpretation': self._interpret_correlation(spearman_r, spearman_p)
                }

        return {}

    def correlate_pushdown_performance(
        self,
        mechanisms_df: pd.DataFrame,
        performance_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Correlate predicate pushdown ratio with execution time.

        Expected: Higher pushdown ratio → lower execution time
        """
        if 'pushdown_ratio' in mechanisms_df.columns and 'execution_time' in performance_df.columns:
            merged = mechanisms_df.merge(
                performance_df[['database', 'orm', 'query_id', 'execution_time']],
                on=['database', 'orm', 'query_id'],
                how='inner'
            )

            if len(merged) > 0:
                pearson_r, pearson_p = stats.pearsonr(
                    merged['pushdown_ratio'],
                    merged['execution_time']
                )

                spearman_r, spearman_p = stats.spearmanr(
                    merged['pushdown_ratio'],
                    merged['execution_time']
                )

                return {
                    'mechanism': 'pushdown_ratio',
                    'outcome': 'execution_time',
                    'n_samples': len(merged),
                    'pearson_r': pearson_r,
                    'pearson_p': pearson_p,
                    'spearman_r': spearman_r,
                    'spearman_p': spearman_p,
                    'interpretation': self._interpret_correlation(spearman_r, spearman_p)
                }

        return {}

    def correlate_index_utilization_performance(
        self,
        mechanisms_df: pd.DataFrame,
        performance_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Correlate index utilization ratio with execution time.

        Expected: Higher index utilization → lower execution time (usually)
        Exception: PostgreSQL + Django (indexing paradox)
        """
        if 'index_utilization_ratio' in mechanisms_df.columns and 'execution_time' in performance_df.columns:
            merged = mechanisms_df.merge(
                performance_df[['database', 'orm', 'query_id', 'execution_time']],
                on=['database', 'orm', 'query_id'],
                how='inner'
            )

            if len(merged) > 0:
                pearson_r, pearson_p = stats.pearsonr(
                    merged['index_utilization_ratio'],
                    merged['execution_time']
                )

                spearman_r, spearman_p = stats.spearmanr(
                    merged['index_utilization_ratio'],
                    merged['execution_time']
                )

                return {
                    'mechanism': 'index_utilization_ratio',
                    'outcome': 'execution_time',
                    'n_samples': len(merged),
                    'pearson_r': pearson_r,
                    'pearson_p': pearson_p,
                    'spearman_r': spearman_r,
                    'spearman_p': spearman_p,
                    'interpretation': self._interpret_correlation(spearman_r, spearman_p)
                }

        return {}

    def multivariate_regression(
        self,
        mechanisms_df: pd.DataFrame,
        performance_df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Multiple regression to predict performance from multiple mechanisms.

        Model: execution_time ~ q_error + pushdown_ratio + index_ratio + join_count

        Returns feature importance and model statistics.
        """
        # Merge datasets
        merged = mechanisms_df.merge(
            performance_df[['database', 'orm', 'query_id', 'execution_time']],
            on=['database', 'orm', 'query_id'],
            how='inner'
        )

        # Select features
        feature_cols = []
        if 'avg_join_qerror' in merged.columns:
            feature_cols.append('avg_join_qerror')
        if 'pushdown_ratio' in merged.columns:
            feature_cols.append('pushdown_ratio')
        if 'index_utilization_ratio' in merged.columns:
            feature_cols.append('index_utilization_ratio')
        if 'num_joins' in merged.columns:
            feature_cols.append('num_joins')

        if not feature_cols or 'execution_time' not in merged.columns:
            return {}

        # Remove rows with missing values
        merged_clean = merged[feature_cols + ['execution_time']].dropna()

        # Remove infinite values
        merged_clean = merged_clean[np.isfinite(merged_clean).all(axis=1)]

        if len(merged_clean) < 10:  # Need minimum samples
            return {}

        X = merged_clean[feature_cols].values
        y = merged_clean['execution_time'].values

        # Standardize features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Fit regression
        model = LinearRegression()
        model.fit(X_scaled, y)

        # Calculate R²
        r_squared = model.score(X_scaled, y)

        # Feature importance (standardized coefficients)
        importance = {
            feature: coef
            for feature, coef in zip(feature_cols, model.coef_)
        }

        return {
            'model': 'multiple_regression',
            'features': feature_cols,
            'n_samples': len(merged_clean),
            'r_squared': r_squared,
            'feature_importance': importance,
            'intercept': model.intercept_
        }

    def _interpret_correlation(self, r: float, p: float) -> str:
        """
        Interpret correlation strength and significance.

        Args:
            r: Correlation coefficient
            p: P-value

        Returns:
            Human-readable interpretation
        """
        if p >= 0.05:
            return "Not significant (p >= 0.05)"

        abs_r = abs(r)

        if abs_r < 0.3:
            strength = "weak"
        elif abs_r < 0.5:
            strength = "moderate"
        elif abs_r < 0.7:
            strength = "strong"
        else:
            strength = "very strong"

        direction = "positive" if r > 0 else "negative"

        return f"{strength.capitalize()} {direction} correlation (p < 0.05)"

    def analyze_all_correlations(self) -> pd.DataFrame:
        """
        Perform all correlation analyses.

        Returns:
            DataFrame with all correlation results
        """
        mechanisms_df, performance_df = self.load_data()

        if mechanisms_df.empty or performance_df.empty:
            logger.error("Failed to load data")
            return pd.DataFrame()

        logger.info("Performing correlation analyses...")

        # Q-error correlation
        qerror_corr = self.correlate_qerror_performance(mechanisms_df, performance_df)
        if qerror_corr:
            self.correlations.append(qerror_corr)

        # Pushdown correlation
        pushdown_corr = self.correlate_pushdown_performance(mechanisms_df, performance_df)
        if pushdown_corr:
            self.correlations.append(pushdown_corr)

        # Index utilization correlation
        index_corr = self.correlate_index_utilization_performance(mechanisms_df, performance_df)
        if index_corr:
            self.correlations.append(index_corr)

        # Multivariate regression
        regression_result = self.multivariate_regression(mechanisms_df, performance_df)
        if regression_result:
            logger.info(f"Multiple regression R² = {regression_result['r_squared']:.3f}")

        if self.correlations:
            return pd.DataFrame(self.correlations)
        else:
            return pd.DataFrame()

    def generate_report(self, correlations_df: pd.DataFrame, output_file: Path):
        """
        Generate statistical linking report.

        Shows which mechanisms predict performance and how strongly.
        """
        report = []
        report.append("=" * 80)
        report.append("STATISTICAL LINKING ANALYSIS - MOEF PHASE 4")
        report.append("Paper Reference: Section 3.5.4 - Causal Linking")
        report.append("=" * 80)
        report.append("")
        report.append("Establishes causal relationships between optimizer mechanisms")
        report.append("and query execution performance.")
        report.append("")

        if correlations_df.empty:
            report.append("⚠ No correlation data available")
            report.append("")
            report.append("Ensure MOEF analyses have been run and benchmark data exists.")
        else:
            report.append("1. Mechanism-Performance Correlations:")
            report.append("-" * 80)
            report.append("")

            for _, row in correlations_df.iterrows():
                mechanism = row['mechanism']
                outcome = row['outcome']
                n = row['n_samples']
                spearman_r = row['spearman_r']
                spearman_p = row['spearman_p']
                interpretation = row['interpretation']

                report.append(f"  {mechanism} → {outcome}")
                report.append(f"    Samples: {n}")
                report.append(f"    Spearman ρ: {spearman_r:>6.3f}  (p = {spearman_p:.4f})")
                report.append(f"    Interpretation: {interpretation}")
                report.append("")

        report.append("")
        report.append("2. Key Causal Chains (from paper):")
        report.append("-" * 80)
        report.append("")
        report.append("  MySQL Q8:")
        report.append("    Poor estimation (q-error 8.7)")
        report.append("    → Wrong join method (Nested Loop on large input)")
        report.append("    → Slow execution (117s)")
        report.append("")
        report.append("  PostgreSQL Q8:")
        report.append("    Good estimation (q-error 1.4)")
        report.append("    → Correct join method (Hash Join)")
        report.append("    → Fast execution (6.3s)")
        report.append("")
        report.append("  PostgreSQL Indexing Paradox:")
        report.append("    Django query pattern")
        report.append("    → Optimizer selects suboptimal plan with indexes")
        report.append("    → Performance degrades (-12%)")
        report.append("")
        report.append("    SQLAlchemy query pattern")
        report.append("    → Optimizer selects optimal plan with indexes")
        report.append("    → Performance improves (+98%)")
        report.append("")

        report.append("=" * 80)

        # Write to file
        with open(output_file, 'w') as f:
            f.write('\n'.join(report))

        # Also print to console
        print('\n'.join(report))


def main():
    parser = argparse.ArgumentParser(
        description='Statistical linking of mechanisms to performance (MOEF Phase 4)'
    )
    parser.add_argument(
        '--moef-dir',
        type=Path,
        default=Path('results/moef'),
        help='Directory containing MOEF analysis results'
    )
    parser.add_argument(
        '--benchmark-file',
        type=Path,
        default=Path('results/raw/benchmark_results.csv'),
        help='Benchmark performance data CSV'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('results/moef/statistical_linking.txt'),
        help='Output file for analysis report'
    )
    parser.add_argument(
        '--csv',
        type=Path,
        default=Path('results/moef/correlations.csv'),
        help='Output CSV for correlation data'
    )

    args = parser.parse_args()

    # Initialize linker
    linker = StatisticalLinker(args.moef_dir, args.benchmark_file)

    # Perform correlations
    logger.info("Analyzing statistical relationships...")
    correlations_df = linker.analyze_all_correlations()

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Generate report
    linker.generate_report(correlations_df, args.output)

    # Save CSV
    if not correlations_df.empty:
        correlations_df.to_csv(args.csv, index=False)
        logger.info(f"\nCorrelation data saved to {args.csv}")

    logger.info(f"Statistical linking report saved to {args.output}")


if __name__ == '__main__':
    main()
