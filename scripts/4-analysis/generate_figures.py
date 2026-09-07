#!/usr/bin/env python3
"""
Generate figures from benchmark results.

Creates all figures from the paper:
- Figure 1: Performance comparison by complexity
- Figure 3: Concurrency throughput
- Figure 6: Indexing impact
- Figure 7: Total runtime
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
import argparse

# Set style
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)
plt.rcParams['font.size'] = 10


def load_results(results_file):
    """Load benchmark results from CSV."""
    return pd.read_csv(results_file)


def generate_fig1_performance_comparison(df, output_dir):
    """
    Figure 1: Execution times by complexity level.
    
    Bar chart showing mean execution times for ORM vs SQL
    across different complexity levels.
    """
    # Add complexity mapping (would need to be in data or metadata)
    complexity_map = {
        'Q6': 'Simple', 'Q14': 'Simple', 'Q19': 'Simple',
        'Q1': 'Medium', 'Q3': 'Medium', 'Q4': 'Medium', 'Q11': 'Medium', 'Q12': 'Medium', 'Q16': 'Medium',
        'Q2': 'Complex', 'Q5': 'Complex', 'Q7': 'Complex', 'Q10': 'Complex', 'Q13': 'Complex',
        'Q15': 'Complex', 'Q17': 'Complex', 'Q18': 'Complex', 'Q20': 'Complex',
        'Q8': 'Very Complex', 'Q9': 'Very Complex', 'Q21': 'Very Complex', 'Q22': 'Very Complex'
    }
    
    df['complexity'] = df['query'].map(complexity_map)
    
    # Group by complexity and method
    grouped = df.groupby(['complexity', 'method', 'database'])['mean_ms'].mean().reset_index()
    
    # Create figure
    fig, axes = plt.subplots(1, 4, figsize=(16, 4), sharey=True)
    
    databases = ['default', 'mysql', 'oracle', 'sqlserver']
    db_names = ['PostgreSQL', 'MySQL', 'Oracle', 'SQL Server']
    
    for idx, (db, db_name) in enumerate(zip(databases, db_names)):
        ax = axes[idx]
        db_data = grouped[grouped['database'] == db]
        
        # Pivot for plotting
        pivot = db_data.pivot(index='complexity', columns='method', values='mean_ms')
        
        pivot.plot(kind='bar', ax=ax)
        ax.set_title(db_name)
        ax.set_xlabel('Complexity')
        if idx == 0:
            ax.set_ylabel('Execution Time (ms)')
        ax.legend(['ORM', 'SQL'])
        ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'fig1_performance_comparison.png', dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Saved fig1_performance_comparison.png")


def generate_fig3_concurrency_throughput(concurrency_file, output_dir):
    """
    Figure 3: Queries per second vs concurrency level.
    
    Line plot showing throughput under different concurrency levels.
    """
    # This would load from concurrency test results
    # For now, create placeholder
    
    concurrency_levels = [1, 10, 25, 50, 100, 150, 200]
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Placeholder data (would load from actual results)
    databases = ['PostgreSQL', 'MySQL', 'Oracle', 'SQL Server']
    
    for db in databases:
        # Generate example data (replace with actual data)
        qps = [100 * (1 - np.exp(-c / 50)) for c in concurrency_levels]
        ax.plot(concurrency_levels, qps, marker='o', label=db)
    
    ax.set_xlabel('Concurrency Level (users)')
    ax.set_ylabel('Queries Per Second (QPS)')
    ax.set_title('Throughput vs Concurrency Level')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'fig3_concurrency_throughput.png', dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Saved fig3_concurrency_throughput.png")


def generate_fig6_indexing_impact(df, output_dir):
    """
    Figure 6: Impact of indexing on Q8 and Q9.
    
    Bar chart comparing indexed vs non-indexed performance.
    """
    # Filter for Q8 and Q9
    q8_q9 = df[df['query'].isin(['Q08', 'Q09'])]
    
    if len(q8_q9) == 0:
        print("⚠ No data for Q8/Q9, skipping fig6")
        return
    
    # Group by query, schema_config, database
    grouped = q8_q9.groupby(['query', 'schema_config', 'database'])['mean_ms'].mean().reset_index()
    
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    
    for idx, query in enumerate(['Q08', 'Q09']):
        ax = axes[idx]
        query_data = grouped[grouped['query'] == query]
        
        # Pivot for plotting
        pivot = query_data.pivot(index='database', columns='schema_config', values='mean_ms')
        
        pivot.plot(kind='bar', ax=ax)
        ax.set_title(f'{query} Performance')
        ax.set_xlabel('Database')
        ax.set_ylabel('Execution Time (ms)')
        ax.legend(['Indexed', 'Non-Indexed'])
        ax.set_xticklabels(['PostgreSQL', 'MySQL', 'Oracle', 'SQL Server'], rotation=45)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'fig6_indexing_impact.png', dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Saved fig6_indexing_impact.png")


def generate_fig7_total_runtime(df, output_dir):
    """
    Figure 7: Total runtime for all queries.
    
    Stacked bar chart showing total runtime split by indexed/non-indexed.
    """
    # Sum total time for each database and schema config
    grouped = df.groupby(['database', 'schema_config', 'method'])['mean_ms'].sum().reset_index()
    
    # Convert to seconds
    grouped['total_seconds'] = grouped['mean_ms'] / 1000
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    databases = ['default', 'mysql', 'oracle', 'sqlserver']
    db_names = ['PostgreSQL', 'MySQL', 'Oracle', 'SQL Server']
    
    # Prepare data for stacking
    indexed_orm = []
    indexed_sql = []
    non_indexed_orm = []
    non_indexed_sql = []
    
    for db in databases:
        db_data = grouped[grouped['database'] == db]
        
        indexed_orm.append(db_data[(db_data['schema_config'] == 'indexed') & (db_data['method'] == 'orm')]['total_seconds'].sum())
        indexed_sql.append(db_data[(db_data['schema_config'] == 'indexed') & (db_data['method'] == 'sql')]['total_seconds'].sum())
        non_indexed_orm.append(db_data[(db_data['schema_config'] == 'non-indexed') & (db_data['method'] == 'orm')]['total_seconds'].sum())
        non_indexed_sql.append(db_data[(db_data['schema_config'] == 'non-indexed') & (db_data['method'] == 'sql')]['total_seconds'].sum())
    
    x = np.arange(len(db_names))
    width = 0.35
    
    p1 = ax.bar(x - width/2, indexed_orm, width, label='Indexed ORM')
    p2 = ax.bar(x - width/2, indexed_sql, width, bottom=indexed_orm, label='Indexed SQL')
    p3 = ax.bar(x + width/2, non_indexed_orm, width, label='Non-Indexed ORM')
    p4 = ax.bar(x + width/2, non_indexed_sql, width, bottom=non_indexed_orm, label='Non-Indexed SQL')
    
    ax.set_xlabel('Database')
    ax.set_ylabel('Total Runtime (seconds)')
    ax.set_title('Total Runtime for All Queries')
    ax.set_xticks(x)
    ax.set_xticklabels(db_names)
    ax.legend()
    
    plt.tight_layout()
    plt.savefig(output_dir / 'fig7_total_runtime.png', dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Saved fig7_total_runtime.png")


def main():
    parser = argparse.ArgumentParser(description='Generate benchmark figures')
    parser.add_argument('--results', '-r', type=str, default='results/raw/summary_statistics.csv',
                        help='Path to summary statistics CSV')
    parser.add_argument('--concurrency', type=str,
                        help='Path to concurrency results CSV')
    parser.add_argument('--output', '-o', type=str, default='results/figures',
                        help='Output directory for figures')
    parser.add_argument('--all', action='store_true',
                        help='Generate all figures')
    parser.add_argument('--fig1', action='store_true', help='Generate figure 1')
    parser.add_argument('--fig3', action='store_true', help='Generate figure 3')
    parser.add_argument('--fig6', action='store_true', help='Generate figure 6')
    parser.add_argument('--fig7', action='store_true', help='Generate figure 7')
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("="*60)
    print("Generating Benchmark Figures")
    print("="*60)
    
    # Load results
    try:
        df = load_results(args.results)
        print(f"✓ Loaded results from {args.results}")
        print(f"  {len(df)} measurements")
    except Exception as e:
        print(f"✗ Error loading results: {e}")
        return 1
    
    # Generate figures
    try:
        if args.all or args.fig1:
            print("\nGenerating Figure 1...")
            generate_fig1_performance_comparison(df, output_dir)
        
        if args.all or args.fig3:
            print("\nGenerating Figure 3...")
            if args.concurrency:
                generate_fig3_concurrency_throughput(args.concurrency, output_dir)
            else:
                print("⚠ No concurrency file specified, skipping fig3")
        
        if args.all or args.fig6:
            print("\nGenerating Figure 6...")
            generate_fig6_indexing_impact(df, output_dir)
        
        if args.all or args.fig7:
            print("\nGenerating Figure 7...")
            generate_fig7_total_runtime(df, output_dir)
        
        print("\n" + "="*60)
        print("✓ Figure generation complete!")
        print(f"Figures saved to: {output_dir}")
        print("="*60)
    
    except Exception as e:
        print(f"\n✗ Error generating figures: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())


