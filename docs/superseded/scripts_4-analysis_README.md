# Analysis Scripts

Scripts for analyzing benchmark results, generating figures, and performing statistical validation.

## Overview

This directory contains scripts for Phase 4 of the benchmark workflow:
1. Validate benchmark results
2. Generate performance figures
3. Perform statistical analysis
4. Create paper-aligned outputs

## Scripts

### `generate_figures.py`
Generate all performance figures from paper.

```bash
python scripts/4-analysis/generate_figures.py \
    --all \
    --results results/raw/summary_statistics.csv \
    --output results/figures/

# Generates:
# - Figure 4: ORM overhead by query
# - Figure 5: Overhead distribution
# - Figure 6: Cross-database comparison
# - Figure 7: Index impact
# - Figure 8: Concurrency scaling
# - Figure 9: MOEF mechanism analysis

# Individual figures:
python scripts/4-analysis/generate_figures.py --figure 4
python scripts/4-analysis/generate_figures.py --figure 5,6
```

**Output**: `results/figures/figure_{N}.pdf` and `.png`

### `generate_paper_aligned_results.py`
Generate results in exact paper format for validation.

```bash
python scripts/4-analysis/generate_paper_aligned_results.py \
    --input results/raw/ \
    --output results/processed/paper_results.csv

# Validates:
# - Table 2: Query execution times
# - Table 3: Overhead statistics
# - Appendix A: Full results table
```

**Paper Reference**: Sections 5.1, 5.2, Appendix A

### `overhead_decomposition.py`
Decompose ORM overhead into components.

```bash
python scripts/4-analysis/overhead_decomposition.py \
    --results results/raw/overhead_breakdown.csv \
    --output results/processed/decomposition.csv

# Components:
# 1. Query construction: 5-15%
# 2. SQL generation: 10-25%
# 3. Database execution: 40-60%
# 4. Result fetching: 5-15%
# 5. Object mapping: 10-30%
```

**Paper Reference**: Section 5.3 - "Overhead Decomposition"

### `statistical_tests.py`
Perform statistical validation of results.

```bash
python scripts/4-analysis/statistical_tests.py \
    --results results/raw/summary_statistics.csv \
    --output results/processed/statistics.csv

# Tests:
# - Wilcoxon signed-rank test (paired comparisons)
# - Mann-Whitney U test (unpaired comparisons)
# - Effect size (Cohen's d)
# - Confidence intervals (95%)
```

**Paper Reference**: Section 4.4 - "Statistical Validation"

### `validate_results.py`
Validate benchmark results for correctness.

```bash
python scripts/4-analysis/validate_results.py \
    --check-data-integrity \
    --scale-factor 1 \
    --results results/raw/

# Validates:
# - Query result correctness (vs TPC-H answers)
# - Data integrity (row counts, checksums)
# - Schema correctness
# - Index presence
```

**TPC-H Answer Validation**: Uses official TPC-H qgen answers

### `collect_query_plans.py`
Collect database query execution plans.

```bash
python scripts/4-analysis/collect_query_plans.py \
    --database default \
    --all \
    --output results/plans/

# Collects:
# - EXPLAIN output
# - Query plans (text format)
# - Execution statistics

# For MOEF analysis, use:
# python scripts/3-moef/collect_execution_plans.py
```

**Note**: For full MOEF analysis, use `scripts/3-moef/` scripts

## Usage Patterns

### Pattern 1: Generate All Figures
```bash
# After running benchmarks
python scripts/4-analysis/generate_figures.py \
    --all \
    --results results/raw/summary_statistics.csv \
    --output results/figures/

# Check output
ls -lh results/figures/
```

### Pattern 2: Validate Results
```bash
# Check data integrity
python scripts/4-analysis/validate_results.py \
    --check-data-integrity \
    --scale-factor 1

# Validate query correctness
python scripts/4-analysis/validate_results.py \
    --check-query-results \
    --queries all
```

### Pattern 3: Statistical Analysis
```bash
# Run statistical tests
python scripts/4-analysis/statistical_tests.py \
    --results results/raw/summary_statistics.csv

# Check significance
# - p < 0.05: Statistically significant
# - Effect size: Small (0.2), Medium (0.5), Large (0.8)
```

### Pattern 4: Overhead Analysis
```bash
# Decompose overhead
python scripts/4-analysis/overhead_decomposition.py \
    --results results/raw/overhead_breakdown.csv

# Generate overhead figures
python scripts/4-analysis/generate_figures.py --figure 5
```

### Pattern 5: Paper Reproduction
```bash
# Generate exact paper results
python scripts/4-analysis/generate_paper_aligned_results.py

# Generate all paper figures
python scripts/4-analysis/generate_figures.py --all --paper-format

# Validate statistical claims
python scripts/4-analysis/statistical_tests.py --paper-claims
```

## Output Files

### Figures
- **Location**: `results/figures/`
- **Formats**: PDF (vector), PNG (raster)
- **Files**:
  - `figure_4_overhead_by_query.pdf`
  - `figure_5_overhead_distribution.pdf`
  - `figure_6_cross_database.pdf`
  - `figure_7_index_impact.pdf`
  - `figure_8_concurrency.pdf`
  - `figure_9_moef_mechanisms.pdf`

### Statistics
- **Location**: `results/processed/statistics.csv`
- **Columns**:
  - `comparison`: ORM vs baseline
  - `test_statistic`: Test value
  - `p_value`: Statistical significance
  - `effect_size`: Cohen's d
  - `ci_lower`, `ci_upper`: 95% confidence interval

### Validation
- **Location**: `results/processed/validation_report.txt`
- **Contents**:
  - Data integrity check results
  - Query correctness validation
  - Schema verification
  - Index validation

## Figure Descriptions

### Figure 4: ORM Overhead by Query
- **Type**: Bar chart
- **X-axis**: TPC-H query number (1-22)
- **Y-axis**: Execution time (seconds)
- **Series**: Raw SQL, Django ORM, SQLAlchemy
- **Purpose**: Show per-query overhead

### Figure 5: Overhead Distribution
- **Type**: Box plot
- **X-axis**: ORM implementation
- **Y-axis**: Overhead ratio (ORM time / raw SQL time)
- **Purpose**: Show overhead distribution across all queries

### Figure 6: Cross-Database Comparison
- **Type**: Grouped bar chart
- **X-axis**: Database system
- **Y-axis**: Geometric mean overhead
- **Groups**: Django ORM, SQLAlchemy
- **Purpose**: Compare overhead across databases

### Figure 7: Index Impact
- **Type**: Grouped bar chart
- **X-axis**: Query category (simple, medium, complex)
- **Y-axis**: Overhead ratio
- **Groups**: Base schema, Indexed schema
- **Purpose**: Show impact of indexing on overhead

### Figure 8: Concurrency Scaling
- **Type**: Line chart
- **X-axis**: Concurrency level (1, 10, 25, 50, 100)
- **Y-axis**: Throughput (queries/sec)
- **Series**: Raw SQL, Django ORM, SQLAlchemy
- **Purpose**: Show throughput under concurrent load

### Figure 9: MOEF Mechanism Analysis
- **Type**: Stacked bar chart
- **X-axis**: Query number
- **Y-axis**: Overhead percentage
- **Stacks**: Join enumeration, Join method, Index usage, Predicate handling
- **Purpose**: Attribute overhead to specific mechanisms

## Statistical Methods

### Wilcoxon Signed-Rank Test
- **Use**: Paired comparisons (ORM vs baseline, same queries)
- **Null hypothesis**: Median difference = 0
- **Alternative**: Median difference ≠ 0
- **Significance**: α = 0.05

### Mann-Whitney U Test
- **Use**: Unpaired comparisons (different query sets)
- **Null hypothesis**: Distributions are equal
- **Alternative**: Distributions differ
- **Significance**: α = 0.05

### Effect Size (Cohen's d)
- **Formula**: `d = (mean1 - mean2) / pooled_std`
- **Interpretation**:
  - Small: |d| = 0.2
  - Medium: |d| = 0.5
  - Large: |d| = 0.8

## Validation Checks

### Data Integrity
```bash
# Check table row counts
python scripts/4-analysis/validate_results.py --check-counts

# Expected (SF=1):
# LINEITEM: 6,001,215 rows
# ORDERS: 1,500,000 rows
# CUSTOMER: 150,000 rows
# PART: 200,000 rows
# SUPPLIER: 10,000 rows
# PARTSUPP: 800,000 rows
# NATION: 25 rows
# REGION: 5 rows
```

### Query Correctness
```bash
# Validate query results against TPC-H answers
python scripts/4-analysis/validate_results.py --check-query-results

# Uses:
# - tpch-dbgen/queries/answers/*.out
# - Compares aggregates, counts, sums
```

### Schema Validation
```bash
# Check schema matches specification
python scripts/4-analysis/validate_results.py --check-schema

# Validates:
# - Table existence
# - Column types
# - Primary keys
# - Foreign keys (if applicable)
```

## Troubleshooting

### Figure Generation Fails
```bash
# Check matplotlib installed
pip list | grep matplotlib

# Check results file exists
ls -la results/raw/summary_statistics.csv

# Try individual figure
python scripts/4-analysis/generate_figures.py --figure 4 --debug
```

### Statistical Test Errors
```bash
# Check data format
head results/raw/summary_statistics.csv

# Check for missing values
python -c "import pandas as pd; df = pd.read_csv('results/raw/summary_statistics.csv'); print(df.isnull().sum())"

# Run with verbose output
python scripts/4-analysis/statistical_tests.py --verbose
```

### Validation Failures
```bash
# Check data loaded correctly
python scripts/utils/test_connections.py

# Verify row counts
python scripts/4-analysis/validate_results.py --check-counts --verbose

# Regenerate data if needed
./scripts/1-setup/generate_tpch_data.sh 1
./scripts/1-setup/load_data_postgres.sh
```

## Performance Notes

### Figure Generation
- **Time**: 10-30 seconds for all figures
- **Memory**: ~500MB

### Statistical Tests
- **Time**: 5-10 seconds for full analysis
- **Memory**: ~200MB

### Validation
- **Time**: 1-2 minutes for full validation
- **Memory**: ~100MB per database

## Paper Alignment

### Section 5.1: Performance Results
- **Generated by**: `generate_paper_aligned_results.py`
- **Validates**: Table 2, Figure 4

### Section 5.2: Overhead Analysis
- **Generated by**: `overhead_decomposition.py`
- **Validates**: Figure 5, Table 3

### Section 5.3: Cross-Database Comparison
- **Generated by**: `generate_figures.py --figure 6`
- **Validates**: Figure 6

### Section 5.4: Schema Impact
- **Generated by**: `generate_figures.py --figure 7`
- **Validates**: Figure 7

## See Also

- [Analysis Guide](../../docs/05-ANALYSIS.md)
- [MOEF Framework](../../docs/04-MOEF-FRAMEWORK.md)
- [Paper Alignment](../../docs/PAPER-ALIGNMENT.md)
- [Reproducibility Guide](../../REPRODUCIBILITY.md)
- [Running Benchmarks](../../docs/03-RUNNING-BENCHMARKS.md)

