#!/usr/bin/env python3
"""
Variance Decomposition Analysis

Four-factor variance decomposition to understand which factors
most strongly influence ORM performance.

Paper Reference: Section 3.8 - "Statistical Analysis", Table 7

Factors analyzed:
1. DBMS choice (PostgreSQL, MySQL, Oracle, SQL Server)
2. ORM framework (Django, SQLAlchemy)
3. Query complexity (Simple, Medium, Complex, Very Complex)
4. Schema configuration (Indexed, Non-indexed)
5. ORM × DBMS interaction

Expected results (from paper):
- DBMS choice: 42%
- ORM framework: 23%
- Query complexity: 18%
- Schema configuration: 9%
- ORM × DBMS interaction: 5%
- Residual: 3%
"""

import pandas as pd
import numpy as np
from scipy import stats
from sklearn.preprocessing import LabelEncoder
from sklearn.linear_model import LinearRegression
from pathlib import Path
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def load_benchmark_results(results_dir: Path) -> pd.DataFrame:
    """
    Load all benchmark results from CSV files.

    Expected columns:
    - database: Database system (postgresql, mysql, oracle, sqlserver)
    - orm: ORM framework (django, sqlalchemy)
    - query: Query identifier (Q1, Q2, etc.)
    - schema: Schema type (indexed, nonindexed)
    - execution_time: Measured execution time (ms or seconds)
    - complexity: Query complexity (Simple, Medium, Complex, Very Complex)
    """
    all_results = []

    # Load from raw results directory
    for csv_file in results_dir.glob('**/*.csv'):
        try:
            df = pd.read_csv(csv_file)
            all_results.append(df)
        except Exception as e:
            logger.warning(f"Failed to load {csv_file}: {e}")

    if not all_results:
        raise ValueError(f"No results found in {results_dir}")

    combined_df = pd.concat(all_results, ignore_index=True)
    logger.info(f"Loaded {len(combined_df)} result records from {len(all_results)} files")

    return combined_df


def add_query_complexity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add query complexity categorization.

    Paper categorization (Table 2):
    - Simple: Q6, Q14, Q19 (1-2 joins)
    - Medium: Q1, Q3, Q4, Q11, Q12, Q16 (3-4 joins)
    - Complex: Q2, Q5, Q7, Q10, Q13, Q15, Q17, Q18, Q20 (5-7 joins)
    - Very Complex: Q8, Q9, Q21, Q22 (8+ joins)
    """
    complexity_map = {
        'Q6': 'Simple', 'Q14': 'Simple', 'Q19': 'Simple',
        'Q1': 'Medium', 'Q3': 'Medium', 'Q4': 'Medium',
        'Q11': 'Medium', 'Q12': 'Medium', 'Q16': 'Medium',
        'Q2': 'Complex', 'Q5': 'Complex', 'Q7': 'Complex',
        'Q10': 'Complex', 'Q13': 'Complex', 'Q15': 'Complex',
        'Q17': 'Complex', 'Q18': 'Complex', 'Q20': 'Complex',
        'Q8': 'Very Complex', 'Q9': 'Very Complex',
        'Q21': 'Very Complex', 'Q22': 'Very Complex'
    }

    if 'complexity' not in df.columns:
        df['complexity'] = df['query'].map(complexity_map)

    return df


def calculate_variance_decomposition(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate variance decomposition using nested ANOVA / hierarchical regression.

    Method:
    1. Fit models with different factor combinations
    2. Calculate R² for each model
    3. Attribute variance explained to each factor
    4. Handle interaction terms

    Returns:
        DataFrame with variance explained by each factor
    """
    # Ensure we have required columns
    required_cols = ['database', 'orm', 'complexity', 'schema', 'execution_time']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"Missing required columns. Need: {required_cols}")

    # Remove missing values
    df_clean = df[required_cols].dropna()

    # Log-transform execution time to handle skewness
    # (Execution times are often log-normally distributed)
    df_clean['log_execution_time'] = np.log1p(df_clean['execution_time'])

    # Encode categorical variables
    le_database = LabelEncoder()
    le_orm = LabelEncoder()
    le_complexity = LabelEncoder()
    le_schema = LabelEncoder()

    df_clean['database_encoded'] = le_database.fit_transform(df_clean['database'])
    df_clean['orm_encoded'] = le_orm.fit_transform(df_clean['orm'])
    df_clean['complexity_encoded'] = le_complexity.fit_transform(df_clean['complexity'])
    df_clean['schema_encoded'] = le_schema.fit_transform(df_clean['schema'])

    # Calculate interaction term
    df_clean['orm_db_interaction'] = df_clean['orm_encoded'] * df_clean['database_encoded']

    # Target variable
    y = df_clean['log_execution_time'].values

    # Build models with increasing complexity
    models = {
        'null': np.array([]),  # Null model (intercept only)
        'dbms': df_clean[['database_encoded']].values,
        'dbms+orm': df_clean[['database_encoded', 'orm_encoded']].values,
        'dbms+orm+complexity': df_clean[['database_encoded', 'orm_encoded', 'complexity_encoded']].values,
        'dbms+orm+complexity+schema': df_clean[['database_encoded', 'orm_encoded', 'complexity_encoded', 'schema_encoded']].values,
        'full': df_clean[['database_encoded', 'orm_encoded', 'complexity_encoded', 'schema_encoded', 'orm_db_interaction']].values
    }

    # Calculate R² for each model
    r_squared = {}
    for model_name, X in models.items():
        if X.size == 0:
            # Null model: variance explained = 0
            r_squared[model_name] = 0.0
        else:
            reg = LinearRegression()
            reg.fit(X, y)
            r_squared[model_name] = reg.score(X, y)

    # Calculate variance explained by each factor
    # (Incremental R² when adding each factor)
    variance_explained = {
        'DBMS choice': r_squared['dbms'] - r_squared['null'],
        'ORM framework': r_squared['dbms+orm'] - r_squared['dbms'],
        'Query complexity': r_squared['dbms+orm+complexity'] - r_squared['dbms+orm'],
        'Schema configuration': r_squared['dbms+orm+complexity+schema'] - r_squared['dbms+orm+complexity'],
        'ORM × DBMS interaction': r_squared['full'] - r_squared['dbms+orm+complexity+schema'],
        'Residual': 1.0 - r_squared['full']
    }

    # Convert to DataFrame
    result_df = pd.DataFrame({
        'Factor': list(variance_explained.keys()),
        'Variance Explained': list(variance_explained.values()),
        'Percentage': [v * 100 for v in variance_explained.values()]
    })

    # Sort by variance explained (descending)
    result_df = result_df.sort_values('Variance Explained', ascending=False)

    return result_df


def perform_anova(df: pd.DataFrame) -> pd.DataFrame:
    """
    Perform multi-way ANOVA to test factor significance.

    Tests null hypothesis that factor has no effect on execution time.
    """
    from scipy.stats import f_oneway

    results = []

    # ANOVA for each factor
    factors = ['database', 'orm', 'complexity', 'schema']

    for factor in factors:
        groups = df.groupby(factor)['execution_time'].apply(list)

        # Perform one-way ANOVA
        f_stat, p_value = f_oneway(*groups)

        results.append({
            'Factor': factor,
            'F-statistic': f_stat,
            'p-value': p_value,
            'Significant (p<0.001)': p_value < 0.001
        })

    return pd.DataFrame(results)


def generate_report(variance_df: pd.DataFrame, anova_df: pd.DataFrame, output_file: Path):
    """
    Generate comprehensive variance decomposition report.
    """
    report = []
    report.append("=" * 70)
    report.append("VARIANCE DECOMPOSITION ANALYSIS")
    report.append("Paper Reference: Section 3.8, Table 7")
    report.append("=" * 70)
    report.append("")

    report.append("Variance Explained by Each Factor:")
    report.append("-" * 70)
    for _, row in variance_df.iterrows():
        report.append(f"  {row['Factor']:<30} {row['Percentage']:>6.1f}%  "
                     f"({'*' * int(row['Percentage'] / 5)})")
    report.append("")

    report.append("Paper-Reported Values (for comparison):")
    report.append("-" * 70)
    paper_values = {
        'DBMS choice': 42.0,
        'ORM framework': 23.0,
        'Query complexity': 18.0,
        'Schema configuration': 9.0,
        'ORM × DBMS interaction': 5.0,
        'Residual': 3.0
    }

    for factor, paper_val in paper_values.items():
        actual_val = variance_df[variance_df['Factor'] == factor]['Percentage'].values[0]
        diff = actual_val - paper_val
        status = "✓" if abs(diff) < 10 else "⚠"
        report.append(f"  {status} {factor:<30} Paper: {paper_val:>5.1f}%  Actual: {actual_val:>5.1f}%  "
                     f"Δ: {diff:>+5.1f}%")
    report.append("")

    report.append("ANOVA Significance Tests:")
    report.append("-" * 70)
    for _, row in anova_df.iterrows():
        sig_marker = "***" if row['p-value'] < 0.001 else ("**" if row['p-value'] < 0.01 else ("*" if row['p-value'] < 0.05 else "ns"))
        report.append(f"  {row['Factor']:<20} F={row['F-statistic']:>10.2f}  "
                     f"p={row['p-value']:.2e}  {sig_marker}")
    report.append("")

    report.append("Key Findings:")
    report.append("-" * 70)
    report.append(f"  • Most important factor: {variance_df.iloc[0]['Factor']} "
                 f"({variance_df.iloc[0]['Percentage']:.1f}%)")
    report.append(f"  • Combined ORM effects: {variance_df[variance_df['Factor'].isin(['ORM framework', 'ORM × DBMS interaction'])]['Percentage'].sum():.1f}%")
    report.append(f"  • Model fit (R²): {(1 - variance_df[variance_df['Factor'] == 'Residual']['Percentage'].values[0] / 100):.3f}")
    report.append("")

    report.append("=" * 70)

    # Write to file
    with open(output_file, 'w') as f:
        f.write('\n'.join(report))

    # Also print to console
    print('\n'.join(report))


def main():
    parser = argparse.ArgumentParser(
        description='Variance decomposition analysis for ORM benchmark results'
    )
    parser.add_argument(
        '--results-dir',
        type=Path,
        default=Path('results/raw'),
        help='Directory containing benchmark results CSV files'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('results/processed/variance_decomposition.txt'),
        help='Output file for variance decomposition report'
    )
    parser.add_argument(
        '--csv',
        type=Path,
        default=Path('results/processed/variance_decomposition.csv'),
        help='Output CSV file for variance data'
    )

    args = parser.parse_args()

    # Load results
    logger.info(f"Loading results from {args.results_dir}")
    df = load_benchmark_results(args.results_dir)

    # Add complexity categorization
    df = add_query_complexity(df)

    # Calculate variance decomposition
    logger.info("Calculating variance decomposition...")
    variance_df = calculate_variance_decomposition(df)

    # Perform ANOVA
    logger.info("Performing ANOVA tests...")
    anova_df = perform_anova(df)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.csv.parent.mkdir(parents=True, exist_ok=True)

    # Generate report
    generate_report(variance_df, anova_df, args.output)

    # Save CSV
    variance_df.to_csv(args.csv, index=False)
    logger.info(f"Variance decomposition saved to {args.csv}")

    anova_df.to_csv(args.csv.parent / 'anova_results.csv', index=False)
    logger.info(f"ANOVA results saved to {args.csv.parent / 'anova_results.csv'}")


if __name__ == '__main__':
    main()
