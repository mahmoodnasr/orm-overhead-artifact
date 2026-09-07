# Results Directory

This directory contains all benchmark results, analysis outputs, and generated figures.

## Overview

Results are organized by benchmark type (TPC-H, TPC-C), ORM implementation (Django, SQLAlchemy), and schema configuration (indexed, non-indexed). This structure enables easy analysis and comparison across different configurations.

## Directory Structure

```
results/
├── raw/                              Raw benchmark measurements
│   ├── tpch/                         TPC-H results
│   │   ├── django/
│   │   │   ├── indexed/              With secondary indexes
│   │   │   └── non_indexed/          Base schema only
│   │   └── sqlalchemy/
│   │       ├── indexed/
│   │       └── non_indexed/
│   ├── tpcc/                         TPC-C results
│   │   ├── django/
│   │   │   ├── indexed/
│   │   │   └── non_indexed/
│   │   └── sqlalchemy/
│   │       ├── indexed/
│   │       └── non_indexed/
│   └── legacy_all_results.csv        Historical results (archive)
│
├── processed/                        Aggregated and analyzed results
│   ├── summary_statistics.csv        Statistical summaries
│   ├── overhead_analysis.csv         ORM overhead calculations
│   ├── cross_database_comparison.csv Cross-DBMS comparisons
│   └── paper_results.csv             Paper-aligned outputs
│
├── execution_plans/                  Query execution plans
│   ├── postgres/                     PostgreSQL plans
│   ├── mysql/                        MySQL plans
│   ├── oracle/                       Oracle plans
│   └── sqlserver/                    SQL Server plans
│
├── qerror/                           Q-error calculations
│   ├── cardinality_estimates.csv     Estimated vs actual
│   ├── qerror_by_query.csv           Per-query q-error
│   └── qerror_summary.csv            Aggregated q-error
│
├── figures/                          Generated figures (PDF/PNG)
│   ├── figure_4_overhead_by_query.*
│   ├── figure_5_overhead_distribution.*
│   ├── figure_6_cross_database.*
│   ├── figure_7_index_impact.*
│   ├── figure_8_concurrency.*
│   └── figure_9_moef_mechanisms.*
│
├── metadata/                         Experiment metadata
│   ├── system_info.json              Hardware/software specs
│   ├── database_versions.json        DBMS versions
│   ├── experiment_config.json        Configuration used
│   └── run_metadata.json             Run timestamps and details
│
└── concurrency/                      Concurrency test results
    ├── tpcc_django_indexed/
    ├── tpcc_django_non-indexed/
    ├── tpcc_sqlalchemy_indexed/
    └── tpcc_sqlalchemy_non-indexed/
```

## File Formats

### Raw Benchmark Results

**File**: `results/raw/tpch/django/indexed/benchmark_YYYYMMDD_HHMMSS.csv`

**Columns**:
- `benchmark`: Benchmark type (tpch, tpcc)
- `orm`: ORM implementation (django, sqlalchemy, raw)
- `query_id`: Query identifier (1-22 for TPC-H)
- `dbms`: Database system (postgres, mysql, oracle, sqlserver)
- `schema_config`: Schema configuration (indexed, non_indexed)
- `direct_sql_execution_s`: Raw SQL execution time (seconds)
- `query_construction_s`: ORM query construction time
- `network_roundtrip_s`: Network communication time
- `result_fetching_s`: Result set retrieval time
- `object_materialization_s`: ORM object creation time
- `type_conversion_s`: Data type conversion time
- `total_orm_execution_s`: Total ORM execution time
- `overhead_ratio`: ORM time / SQL time
- `overhead_percentage`: (ORM time - SQL time) / SQL time × 100
- `execution_plan`: Query execution plan (if collected)
- `q_error`: Q-error for cardinality estimation
- `avg_cpu_percent`: Average CPU utilization
- `max_cpu_percent`: Peak CPU utilization
- `avg_memory_percent`: Average memory utilization
- `max_memory_percent`: Peak memory utilization
- `avg_memory_mb`: Average memory usage (MB)
- `max_memory_mb`: Peak memory usage (MB)
- `concurrency_level`: Number of concurrent threads
- `throughput_qpm`: Throughput (queries per minute)

**Example**:
```csv
benchmark,orm,query_id,dbms,schema_config,direct_sql_execution_s,total_orm_execution_s,overhead_ratio
tpch,django,1,postgres,indexed,0.123,0.156,1.27
tpch,sqlalchemy,1,postgres,indexed,0.123,0.145,1.18
tpch,raw,1,postgres,indexed,0.123,0.123,1.00
```

### Summary Statistics

**File**: `results/processed/summary_statistics.csv`

**Columns**:
- `query_id`: Query number
- `orm`: ORM implementation
- `dbms`: Database system
- `schema_config`: Schema configuration
- `mean_execution_time`: Average execution time
- `median_execution_time`: Median execution time
- `std_deviation`: Standard deviation
- `min_execution_time`: Minimum time
- `max_execution_time`: Maximum time
- `p95_execution_time`: 95th percentile
- `p99_execution_time`: 99th percentile
- `coefficient_of_variation`: CV (std/mean)
- `mean_overhead_ratio`: Average overhead
- `median_overhead_ratio`: Median overhead

### Execution Plans

**File**: `results/execution_plans/{dbms}/query_{N}_{orm}_plan.json`

**Format**: JSON (DBMS-specific structure)

**PostgreSQL Example**:
```json
{
  "query_id": 8,
  "orm": "django",
  "dbms": "postgres",
  "plan": {
    "Plan": {
      "Node Type": "Hash Join",
      "Startup Cost": 123.45,
      "Total Cost": 678.90,
      "Plan Rows": 1000,
      "Actual Rows": 1050,
      "Actual Time": 45.67
    }
  },
  "q_error": 1.05
}
```

### Q-error Results

**File**: `results/qerror/qerror_by_query.csv`

**Columns**:
- `query_id`: Query number
- `orm`: ORM implementation
- `dbms`: Database system
- `operator`: Plan node type (Join, Scan, etc.)
- `estimated_rows`: Optimizer estimate
- `actual_rows`: Actual row count
- `q_error`: max(estimated/actual, actual/estimated)
- `underestimate`: Boolean (estimated < actual)

### Metadata

**File**: `results/metadata/system_info.json`

```json
{
  "timestamp": "2024-12-13T10:00:00Z",
  "hostname": "benchmark-server",
  "os": "Ubuntu 22.04 LTS",
  "kernel": "5.15.0",
  "cpu": {
    "model": "Intel Xeon E5-2680 v4",
    "cores": 28,
    "threads": 56,
    "frequency_ghz": 2.4
  },
  "memory": {
    "total_gb": 256,
    "available_gb": 200
  },
  "disk": {
    "type": "NVMe SSD",
    "size_gb": 2000,
    "mount": "/data"
  },
  "python_version": "3.10.12",
  "django_version": "4.2.7",
  "sqlalchemy_version": "2.0.23"
}
```

## Naming Conventions

### Benchmark Results Files

**Pattern**: `benchmark_YYYYMMDD_HHMMSS.csv`

**Examples**:
- `benchmark_20241213_100530.csv` - Run on Dec 13, 2024 at 10:05:30
- `benchmark_20241213_153045.csv` - Run on Dec 13, 2024 at 15:30:45

### Execution Plan Files

**Pattern**: `query_{N}_{orm}_plan.json`

**Examples**:
- `query_1_django_plan.json` - Query 1, Django ORM
- `query_8_sqlalchemy_plan.json` - Query 8, SQLAlchemy
- `query_15_raw_plan.json` - Query 15, Raw SQL

### Figure Files

**Pattern**: `figure_{N}_{description}.{ext}`

**Examples**:
- `figure_4_overhead_by_query.pdf` - Figure 4 (vector)
- `figure_4_overhead_by_query.png` - Figure 4 (raster)
- `figure_5_overhead_distribution.pdf` - Figure 5

## Result Validation

### Data Integrity Checks

```bash
# Validate row counts in results
python scripts/4-analysis/validate_results.py --check-counts

# Validate query correctness
python scripts/4-analysis/validate_results.py --check-query-results

# Validate schema
python scripts/4-analysis/validate_results.py --check-schema
```

### Expected File Sizes

| File Type | Typical Size | Notes |
|-----------|--------------|-------|
| Raw benchmark CSV | 10-50 KB | Per run, 22 queries |
| Summary statistics | 5-10 KB | Aggregated |
| Execution plan JSON | 1-10 KB | Per query |
| Figure PDF | 20-100 KB | Vector graphics |
| Figure PNG | 100-500 KB | Raster graphics |

## Analysis Workflows

### Workflow 1: Generate Summary Statistics

```bash
# Aggregate raw results
python scripts/4-analysis/generate_paper_aligned_results.py \
    --input results/raw/ \
    --output results/processed/summary_statistics.csv

# Generate figures
python scripts/4-analysis/generate_figures.py \
    --all \
    --results results/processed/summary_statistics.csv \
    --output results/figures/
```

### Workflow 2: Q-error Analysis

```bash
# Collect execution plans
python scripts/3-moef/collect_execution_plans.py \
    --database default \
    --all \
    --output results/execution_plans/

# Calculate q-error
python scripts/3-moef/calculate_qerror.py \
    --plans results/execution_plans/ \
    --output results/qerror/
```

### Workflow 3: Cross-Database Comparison

```bash
# Generate comparison
python scripts/4-analysis/generate_figures.py \
    --figure 6 \
    --results results/processed/summary_statistics.csv \
    --output results/figures/
```

## Reproducibility

### Paper Results

The following files contain results that reproduce paper figures and tables:

| Paper Element | Result File | Generation Command |
|---------------|-------------|-------------------|
| Table 2 | `processed/paper_results.csv` | `generate_paper_aligned_results.py` |
| Figure 4 | `figures/figure_4_*.pdf` | `generate_figures.py --figure 4` |
| Figure 5 | `figures/figure_5_*.pdf` | `generate_figures.py --figure 5` |
| Figure 6 | `figures/figure_6_*.pdf` | `generate_figures.py --figure 6` |
| Figure 7 | `figures/figure_7_*.pdf` | `generate_figures.py --figure 7` |

### Verification

```bash
# Compare generated results with paper results
python scripts/4-analysis/validate_results.py \
    --compare-to-paper \
    --results results/processed/paper_results.csv \
    --tolerance 0.05  # 5% tolerance for timing variations
```

## Git Tracking

### Tracked Files
- `README.md` - This file
- `*.template.csv` - CSV templates
- Small metadata files

### Ignored Files (`.gitignore`)
- `raw/*.csv` - Raw benchmark results (too large)
- `processed/*.csv` - Processed results (regenerable)
- `figures/*.png` - PNG figures (regenerable)
- `figures/*.pdf` - PDF figures (regenerable)
- `execution_plans/` - Execution plans (large)

**Rationale**: Results are regenerable from code, so they don't need version control.

## Disk Space

### Typical Space Usage

| Directory | Size (SF=1) | Size (SF=10) |
|-----------|-------------|--------------|
| `raw/` | ~50 MB | ~500 MB |
| `execution_plans/` | ~10 MB | ~100 MB |
| `processed/` | ~1 MB | ~10 MB |
| `figures/` | ~5 MB | ~5 MB |
| `qerror/` | ~1 MB | ~10 MB |
| **Total** | **~70 MB** | **~625 MB** |

### Cleanup

```bash
# Remove all results (WARNING: Irreversible!)
./scripts/utils/cleanup.sh --results

# Remove only figures (keep raw data)
rm -rf results/figures/*.png results/figures/*.pdf

# Remove only processed (keep raw data)
rm -rf results/processed/*.csv
```

## Troubleshooting

### Missing Results

```bash
# Check if benchmarks were run
ls -la results/raw/tpch/django/indexed/

# If empty, run benchmarks
python scripts/2-benchmark/run_benchmark.py --database default --all
```

### Corrupted CSV Files

```bash
# Validate CSV format
python -c "import pandas as pd; df = pd.read_csv('results/raw/tpch/django/indexed/benchmark_20241213_100530.csv'); print(df.info())"

# If corrupted, regenerate
python scripts/2-benchmark/run_benchmark.py --database default --all --force
```

### Figure Generation Fails

```bash
# Check if processed results exist
ls -la results/processed/summary_statistics.csv

# If missing, generate
python scripts/4-analysis/generate_paper_aligned_results.py

# Then regenerate figures
python scripts/4-analysis/generate_figures.py --all
```

## See Also

- **Analysis Guide**: [docs/05-ANALYSIS.md](../docs/05-ANALYSIS.md)
- **MOEF Framework**: [docs/04-MOEF-FRAMEWORK.md](../docs/04-MOEF-FRAMEWORK.md)
- **Paper Alignment**: [docs/PAPER-ALIGNMENT.md](../docs/PAPER-ALIGNMENT.md)
- **Reproducibility**: [REPRODUCIBILITY.md](../REPRODUCIBILITY.md)

---

**Last Updated**: December 2024  
**Structure Status**: Standardized and documented
