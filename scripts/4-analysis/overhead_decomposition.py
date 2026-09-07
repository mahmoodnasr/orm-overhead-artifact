"""
ORM Overhead Decomposition Analysis

Analyzes the sources of ORM overhead by decomposing execution time into components:
- Query generation time (ORM → SQL translation)
- Result materialization time (rows → objects)
- Network/database execution time
"""

import pandas as pd
import numpy as np
from typing import Dict, List
import json


def decompose_orm_overhead(orm_times: List[float], sql_times: List[float], 
                           result_counts: List[int]) -> Dict:
    """
    Decompose ORM overhead into components.
    
    Args:
        orm_times: List of ORM execution times
        sql_times: List of SQL execution times
        result_counts: Number of rows returned for each execution
    
    Returns:
        Dictionary with overhead breakdown
    """
    orm_times = np.array(orm_times)
    sql_times = np.array(sql_times)
    result_counts = np.array(result_counts)
    
    # Calculate absolute overhead
    absolute_overhead = orm_times - sql_times
    
    # Calculate relative overhead (percentage)
    relative_overhead = (absolute_overhead / sql_times) * 100
    
    # Estimate materialization overhead (linear with row count)
    if len(result_counts) > 1 and np.std(result_counts) > 0:
        # Simple linear regression: overhead = a * rows + b
        from scipy.stats import linregress
        slope, intercept, r_value, p_value, std_err = linregress(result_counts, absolute_overhead)
        
        materialization_per_row = slope if slope > 0 else 0
        base_overhead = intercept if intercept > 0 else np.mean(absolute_overhead) - materialization_per_row * np.mean(result_counts)
    else:
        # If all queries return same row count, estimate 50/50 split
        materialization_per_row = np.mean(absolute_overhead) / (2 * np.mean(result_counts)) if np.mean(result_counts) > 0 else 0
        base_overhead = np.mean(absolute_overhead) / 2
    
    return {
        'mean_orm_time': float(np.mean(orm_times)),
        'mean_sql_time': float(np.mean(sql_times)),
        'mean_absolute_overhead': float(np.mean(absolute_overhead)),
        'mean_relative_overhead_pct': float(np.mean(relative_overhead)),
        'median_relative_overhead_pct': float(np.median(relative_overhead)),
        'base_overhead': float(base_overhead),  # Query generation, connection overhead
        'materialization_per_row': float(materialization_per_row),  # Per-row object creation
        'overhead_breakdown': {
            'query_generation_pct': float((base_overhead / np.mean(absolute_overhead)) * 100) if np.mean(absolute_overhead) > 0 else 0,
            'materialization_pct': float(((materialization_per_row * np.mean(result_counts)) / np.mean(absolute_overhead)) * 100) if np.mean(absolute_overhead) > 0 else 0
        }
    }


def analyze_overhead_by_complexity(results_df: pd.DataFrame) -> Dict:
    """
    Analyze ORM overhead grouped by query complexity.
    
    Args:
        results_df: DataFrame with columns: query, complexity, method, elapsed_seconds, row_count
    
    Returns:
        Dictionary with overhead analysis by complexity
    """
    # Complexity mapping
    complexity_map = {
        'Q01': 'Medium', 'Q02': 'Complex', 'Q03': 'Medium', 'Q04': 'Medium',
        'Q05': 'Complex', 'Q06': 'Simple', 'Q07': 'Complex', 'Q08': 'Very Complex',
        'Q09': 'Very Complex', 'Q10': 'Complex', 'Q11': 'Medium', 'Q12': 'Medium',
        'Q13': 'Complex', 'Q14': 'Simple', 'Q15': 'Complex', 'Q16': 'Medium',
        'Q17': 'Complex', 'Q18': 'Complex', 'Q19': 'Simple', 'Q20': 'Complex',
        'Q21': 'Very Complex', 'Q22': 'Very Complex'
    }
    
    # Add complexity if not present
    if 'complexity' not in results_df.columns:
        results_df['complexity'] = results_df['query'].map(complexity_map)
    
    complexity_analysis = {}
    
    for complexity in ['Simple', 'Medium', 'Complex', 'Very Complex']:
        complexity_data = results_df[results_df['complexity'] == complexity]
        
        if len(complexity_data) == 0:
            continue
        
        orm_data = complexity_data[complexity_data['method'] == 'orm']
        sql_data = complexity_data[complexity_data['method'] == 'sql']
        
        if len(orm_data) > 0 and len(sql_data) > 0:
            # Match by query
            merged = pd.merge(
                orm_data[['query', 'elapsed_seconds', 'row_count']],
                sql_data[['query', 'elapsed_seconds', 'row_count']],
                on='query',
                suffixes=('_orm', '_sql')
            )
            
            if len(merged) > 0:
                overhead_analysis = decompose_orm_overhead(
                    merged['elapsed_seconds_orm'].values,
                    merged['elapsed_seconds_sql'].values,
                    merged['row_count_orm'].values
                )
                complexity_analysis[complexity] = overhead_analysis
    
    return complexity_analysis


def analyze_overhead_by_database(results_df: pd.DataFrame) -> Dict:
    """
    Analyze ORM overhead grouped by database system.
    
    Args:
        results_df: DataFrame with benchmark results
    
    Returns:
        Dictionary with overhead analysis by database
    """
    database_analysis = {}
    
    for database in results_df['database'].unique():
        db_data = results_df[results_df['database'] == database]
        
        orm_data = db_data[db_data['method'] == 'orm']
        sql_data = db_data[db_data['method'] == 'sql']
        
        if len(orm_data) > 0 and len(sql_data) > 0:
            # Match by query
            merged = pd.merge(
                orm_data[['query', 'elapsed_seconds', 'row_count']],
                sql_data[['query', 'elapsed_seconds', 'row_count']],
                on='query',
                suffixes=('_orm', '_sql')
            )
            
            if len(merged) > 0:
                overhead_analysis = decompose_orm_overhead(
                    merged['elapsed_seconds_orm'].values,
                    merged['elapsed_seconds_sql'].values,
                    merged['row_count_orm'].values
                )
                database_analysis[database] = overhead_analysis
    
    return database_analysis


def generate_overhead_report(results_csv: str, output_file: str = None) -> Dict:
    """
    Generate complete overhead analysis report.
    
    Args:
        results_csv: Path to results CSV file
        output_file: Optional path to save JSON report
    
    Returns:
        Complete overhead analysis dictionary
    """
    # Load results
    df = pd.read_csv(results_csv)
    
    # Overall overhead
    orm_all = df[df['method'] == 'orm']
    sql_all = df[df['method'] == 'sql']
    
    merged_all = pd.merge(
        orm_all[['query', 'database', 'elapsed_seconds', 'row_count']],
        sql_all[['query', 'database', 'elapsed_seconds', 'row_count']],
        on=['query', 'database'],
        suffixes=('_orm', '_sql')
    )
    
    report = {
        'overall': decompose_orm_overhead(
            merged_all['elapsed_seconds_orm'].values,
            merged_all['elapsed_seconds_sql'].values,
            merged_all['row_count_orm'].values
        ),
        'by_complexity': analyze_overhead_by_complexity(df),
        'by_database': analyze_overhead_by_database(df)
    }
    
    # Save report
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Overhead report saved to: {output_file}")
    
    return report


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze ORM overhead decomposition')
    parser.add_argument('--results', '-r', type=str, required=True,
                        help='Path to results CSV file')
    parser.add_argument('--output', '-o', type=str,
                        help='Output JSON file for report')
    
    args = parser.parse_args()
    
    print("="*60)
    print("ORM Overhead Decomposition Analysis")
    print("="*60)
    
    report = generate_overhead_report(args.results, args.output)
    
    # Print summary
    print("\nOverall Overhead:")
    print(f"  Mean ORM time: {report['overall']['mean_orm_time']:.6f}s")
    print(f"  Mean SQL time: {report['overall']['mean_sql_time']:.6f}s")
    print(f"  Mean overhead: {report['overall']['mean_relative_overhead_pct']:.2f}%")
    print(f"\nOverhead Breakdown:")
    print(f"  Query generation: {report['overall']['overhead_breakdown']['query_generation_pct']:.1f}%")
    print(f"  Materialization: {report['overall']['overhead_breakdown']['materialization_pct']:.1f}%")
    
    print("\n" + "="*60)
    print("Analysis complete!")

