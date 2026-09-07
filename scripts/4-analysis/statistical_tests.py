"""
Statistical analysis functions following paper methodology.

Includes:
- Bootstrap confidence intervals
- Cohen's d effect size
- ANOVA variance decomposition
- Coefficient of variation
"""

import numpy as np
from scipy import stats
import pandas as pd
from typing import List, Dict, Tuple


def bootstrap_confidence_intervals(data: List[float], n_samples: int = 10000, alpha: float = 0.05) -> Dict:
    """
    Compute bootstrap confidence intervals.
    
    Args:
        data: List of measurements
        n_samples: Number of bootstrap samples (default 10000)
        alpha: Significance level (default 0.05 for 95% CI)
    
    Returns:
        Dictionary with mean, CI lower, CI upper
    """
    data = np.array(data)
    n = len(data)
    
    # Generate bootstrap samples
    bootstrap_means = []
    for _ in range(n_samples):
        sample = np.random.choice(data, size=n, replace=True)
        bootstrap_means.append(np.mean(sample))
    
    bootstrap_means = np.array(bootstrap_means)
    
    # Calculate confidence interval
    lower_percentile = (alpha / 2) * 100
    upper_percentile = (1 - alpha / 2) * 100
    
    ci_lower = np.percentile(bootstrap_means, lower_percentile)
    ci_upper = np.percentile(bootstrap_means, upper_percentile)
    
    return {
        'mean': np.mean(data),
        'ci_lower': ci_lower,
        'ci_upper': ci_upper,
        'ci_width': ci_upper - ci_lower
    }


def compute_cohens_d(group1: List[float], group2: List[float]) -> float:
    """
    Compute Cohen's d effect size.
    
    Args:
        group1: First group of measurements
        group2: Second group of measurements
    
    Returns:
        Cohen's d value
    """
    group1 = np.array(group1)
    group2 = np.array(group2)
    
    n1, n2 = len(group1), len(group2)
    var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
    
    # Pooled standard deviation
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    
    # Cohen's d
    d = (np.mean(group1) - np.mean(group2)) / pooled_std
    
    return d


def coefficient_of_variation(measurements: List[float]) -> float:
    """
    Calculate coefficient of variation (CV = std / mean * 100).
    
    Paper reports CV < 10% for 89% of executions.
    
    Args:
        measurements: List of measurements
    
    Returns:
        CV as percentage
    """
    measurements = np.array(measurements)
    mean = np.mean(measurements)
    std = np.std(measurements, ddof=1)
    
    if mean == 0:
        return float('inf')
    
    cv = (std / mean) * 100
    return cv


def anova_variance_decomposition(df: pd.DataFrame) -> Dict:
    """
    Perform ANOVA to decompose variance.
    
    Paper reports:
    - DBMS explains 42% of variance
    - Query complexity explains 31%
    - Indexing explains 18%
    
    Args:
        df: DataFrame with columns: 'database', 'query', 'schema_config', 'elapsed_seconds'
    
    Returns:
        Dictionary with variance explained by each factor
    """
    from scipy.stats import f_oneway
    
    # Total variance
    total_var = df['elapsed_seconds'].var()
    
    # Variance explained by database
    db_groups = [group['elapsed_seconds'].values for name, group in df.groupby('database')]
    f_stat_db, p_value_db = f_oneway(*db_groups)
    
    # Calculate sum of squares
    grand_mean = df['elapsed_seconds'].mean()
    
    # Between-group sum of squares for database
    ss_between_db = sum([
        len(group) * (group['elapsed_seconds'].mean() - grand_mean) ** 2
        for name, group in df.groupby('database')
    ])
    
    # Total sum of squares
    ss_total = sum((df['elapsed_seconds'] - grand_mean) ** 2)
    
    # Variance explained by database
    var_explained_db = ss_between_db / ss_total
    
    # Repeat for query complexity (if available)
    if 'complexity' in df.columns:
        complexity_groups = [group['elapsed_seconds'].values for name, group in df.groupby('complexity')]
        f_stat_complex, p_value_complex = f_oneway(*complexity_groups)
        
        ss_between_complex = sum([
            len(group) * (group['elapsed_seconds'].mean() - grand_mean) ** 2
            for name, group in df.groupby('complexity')
        ])
        var_explained_complex = ss_between_complex / ss_total
    else:
        var_explained_complex = None
    
    # Variance explained by indexing
    if 'schema_config' in df.columns:
        index_groups = [group['elapsed_seconds'].values for name, group in df.groupby('schema_config')]
        f_stat_index, p_value_index = f_oneway(*index_groups)
        
        ss_between_index = sum([
            len(group) * (group['elapsed_seconds'].mean() - grand_mean) ** 2
            for name, group in df.groupby('schema_config')
        ])
        var_explained_index = ss_between_index / ss_total
    else:
        var_explained_index = None
    
    return {
        'database_variance_explained': var_explained_db,
        'complexity_variance_explained': var_explained_complex,
        'indexing_variance_explained': var_explained_index,
        'database_f_statistic': f_stat_db,
        'database_p_value': p_value_db
    }


def calculate_cv_statistics(df: pd.DataFrame) -> Dict:
    """
    Calculate CV statistics across all measurements.
    
    Args:
        df: DataFrame with grouped measurements
    
    Returns:
        Dictionary with CV statistics
    """
    cvs = []
    
    for (db, query, method, config), group in df.groupby(['database', 'query', 'method', 'schema_config']):
        if len(group) > 1:
            cv = coefficient_of_variation(group['elapsed_seconds'].values)
            cvs.append(cv)
    
    cvs = np.array(cvs)
    
    # Filter out infinite values
    cvs = cvs[np.isfinite(cvs)]
    
    # Calculate percentage with CV < 10%
    pct_below_10 = (np.sum(cvs < 10) / len(cvs) * 100) if len(cvs) > 0 else 0
    
    return {
        'mean_cv': np.mean(cvs) if len(cvs) > 0 else None,
        'median_cv': np.median(cvs) if len(cvs) > 0 else None,
        'pct_cv_below_10': pct_below_10,
        'min_cv': np.min(cvs) if len(cvs) > 0 else None,
        'max_cv': np.max(cvs) if len(cvs) > 0 else None
    }


def paired_t_test(orm_times: List[float], sql_times: List[float]) -> Dict:
    """
    Perform paired t-test comparing ORM vs SQL times.
    
    Args:
        orm_times: ORM execution times
        sql_times: SQL execution times
    
    Returns:
        Dictionary with test results
    """
    t_stat, p_value = stats.ttest_rel(orm_times, sql_times)
    
    # Calculate mean difference
    differences = np.array(orm_times) - np.array(sql_times)
    mean_diff = np.mean(differences)
    
    # Cohen's d
    d = compute_cohens_d(orm_times, sql_times)
    
    return {
        't_statistic': t_stat,
        'p_value': p_value,
        'mean_difference': mean_diff,
        'cohens_d': d,
        'significant': p_value < 0.05
    }


if __name__ == '__main__':
    # Example usage
    print("Statistical Analysis Module")
    print("="*50)
    
    # Example data
    data1 = [1.2, 1.3, 1.1, 1.4, 1.2]
    data2 = [2.1, 2.3, 2.0, 2.4, 2.2]
    
    print("\nBootstrap CI:")
    ci = bootstrap_confidence_intervals(data1)
    print(f"  Mean: {ci['mean']:.3f}")
    print(f"  95% CI: [{ci['ci_lower']:.3f}, {ci['ci_upper']:.3f}]")
    
    print("\nCohen's d:")
    d = compute_cohens_d(data1, data2)
    print(f"  d = {d:.3f}")
    
    print("\nCoefficient of Variation:")
    cv = coefficient_of_variation(data1)
    print(f"  CV = {cv:.2f}%")
