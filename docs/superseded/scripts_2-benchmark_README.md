# Benchmark Scripts

Scripts for running performance benchmarks, overhead measurements, and concurrency tests.

## Overview

This directory contains scripts for Phase 2 of the benchmark workflow:
1. Execute TPC-H queries through ORMs
2. Measure execution times and overhead
3. Test concurrency performance
4. Compare multiple ORMs and databases

## Main Scripts

### `run_benchmark.py`
Main benchmark runner for single database configurations.

```bash
python scripts/2-benchmark/run_benchmark.py \
    --database default \
    --all \
    --repetitions 5 \
    --output results/raw

# Options:
#   --database: Database alias (default, mysql, oracle, sqlserver)
#   --all: Run all 22 TPC-H queries
#   --queries: Specific queries (e.g., --queries 1,6,8,9)
#   --repetitions: Number of times to run each query (default: 5)
#   --output: Output directory (default: results/raw)
#   --schema-configs: Schema configuration (base, indexed)
#   --orms: ORMs to test (django, sqlalchemy)
```

**Output**: `results/raw/benchmark_TIMESTAMP.csv`

### `run_all_databases_benchmark.py`
Run benchmarks across multiple databases.

```bash
python scripts/2-benchmark/run_all_databases_benchmark.py \
    --databases default,mysql,oracle,sqlserver \
    --all \
    --repetitions 5

# Runs the same benchmark configuration on each database
# Useful for cross-database comparisons
```

### `run_benchmark_multi_orm.py`
Compare multiple ORM implementations.

```bash
python scripts/2-benchmark/run_benchmark_multi_orm.py \
    --orms django,sqlalchemy \
    --database default \
    --all \
    --repetitions 5

# Compares:
# - Django ORM
# - SQLAlchemy Core
# - SQLAlchemy ORM
# - Raw SQL (baseline)
```

**Output**: Includes ORM implementation column for analysis

## Overhead Analysis

### `measure_overhead_breakdown.py`
Detailed overhead measurement for specific queries.

```bash
python scripts/2-benchmark/measure_overhead_breakdown.py \
    --query 8 \
    --database default \
    --repetitions 10

# Measures:
# 1. Raw SQL execution time
# 2. ORM construction time
# 3. Result materialization time
# 4. Python object creation time
# 5. Total overhead
```

**Output**: `results/raw/overhead_breakdown_q{N}.csv`

## Concurrency Testing

### `run_concurrency_benchmark.py`
Test performance under concurrent load.

```bash
python scripts/2-benchmark/run_concurrency_benchmark.py \
    --database default \
    --levels 1,10,25,50,100 \
    --queries 1,6,8 \
    --duration 60

# Options:
#   --levels: Concurrency levels to test (simultaneous threads)
#   --queries: Queries to test under load
#   --duration: Test duration per level (seconds)
```

**Metrics**:
- Throughput (queries/second)
- Average latency
- P50, P95, P99 latency
- Error rate

### `run_per_query_concurrency_benchmark.py`
Per-query concurrency analysis.

```bash
python scripts/2-benchmark/run_per_query_concurrency_benchmark.py \
    --database default \
    --all \
    --concurrency 25

# Runs each query under specified concurrency level
# Useful for identifying queries sensitive to concurrent load
```

## Utility Scripts

### `simple_benchmark.py`
Quick smoke test for basic functionality.

```bash
python scripts/2-benchmark/simple_benchmark.py

# Runs a minimal benchmark to verify:
# - Database connections work
# - ORMs are configured correctly
# - Basic queries execute successfully
```

### `run_benchmark_oracle.py`
Oracle-specific benchmark runner with custom configurations.

```bash
python scripts/2-benchmark/run_benchmark_oracle.py \
    --all \
    --repetitions 5

# Handles Oracle-specific:
# - Connection pooling
# - Cursor management
# - CLOB/BLOB handling
```

### `run_benchmark.sh`
Shell wrapper for common benchmark configurations.

```bash
./scripts/2-benchmark/run_benchmark.sh --db default --queries all --reps 5

# Convenience wrapper that:
# - Activates virtual environment
# - Sets environment variables
# - Runs Python benchmark
# - Validates output
```

## Configuration Options

### Database Aliases

| Alias | Database | Container |
|-------|----------|-----------|
| `default` | PostgreSQL 14 | orm-benchmark-postgres |
| `mysql` | MySQL 8.0 | orm-benchmark-mysql |
| `oracle` | Oracle 19c | orm-benchmark-oracle |
| `sqlserver` | SQL Server 2019 | orm-benchmark-sqlserver |

### Schema Configurations

| Config | Description | Indexes |
|--------|-------------|---------|
| `base` | No secondary indexes | Primary keys only |
| `indexed` | With secondary indexes | All indexes per paper |

### ORM Options

| Option | Description |
|--------|-------------|
| `django` | Django ORM (default ORM in Django framework) |
| `sqlalchemy-core` | SQLAlchemy Core (SQL expression language) |
| `sqlalchemy-orm` | SQLAlchemy ORM (full ORM layer) |
| `raw` | Raw SQL (baseline, no ORM) |

## Usage Patterns

### Pattern 1: Quick Test
```bash
# Test a few queries on PostgreSQL
python scripts/2-benchmark/run_benchmark.py \
    --database default \
    --queries 1,6,8 \
    --repetitions 3
```

### Pattern 2: Full Single-Database Benchmark
```bash
# All queries, multiple repetitions
python scripts/2-benchmark/run_benchmark.py \
    --database default \
    --all \
    --repetitions 5 \
    --schema-configs base,indexed
```

### Pattern 3: Multi-Database Comparison
```bash
# Same queries across all databases
python scripts/2-benchmark/run_all_databases_benchmark.py \
    --databases default,mysql,oracle,sqlserver \
    --all \
    --repetitions 5
```

### Pattern 4: ORM Comparison
```bash
# Compare Django vs SQLAlchemy
python scripts/2-benchmark/run_benchmark_multi_orm.py \
    --orms django,sqlalchemy \
    --database default \
    --all \
    --repetitions 5
```

### Pattern 5: Paper Reproduction (432 Configurations)
```bash
# 4 DBMSs × 2 Schema Configs × 2 ORMs × 22 Queries × 5 Reps
for db in default mysql oracle sqlserver; do
    for schema in base indexed; do
        for orm in django sqlalchemy; do
            python scripts/2-benchmark/run_benchmark.py \
                --database $db \
                --schema-configs $schema \
                --orms $orm \
                --all \
                --repetitions 5
        done
    done
done
```

### Pattern 6: Overhead Analysis
```bash
# Detailed overhead for query 8
python scripts/2-benchmark/measure_overhead_breakdown.py \
    --query 8 \
    --database default \
    --repetitions 10

# Analyze results
python scripts/4-analysis/overhead_decomposition.py --query 8
```

### Pattern 7: Concurrency Testing
```bash
# Test concurrency scaling
python scripts/2-benchmark/run_concurrency_benchmark.py \
    --database default \
    --levels 1,10,25,50,100 \
    --queries 6,8,9 \
    --duration 60
```

## Output Files

### Benchmark Results
- **Location**: `results/raw/benchmark_TIMESTAMP.csv`
- **Columns**:
  - `timestamp`: When query was executed
  - `database`: Database alias
  - `query_num`: TPC-H query number (1-22)
  - `orm`: ORM implementation
  - `execution_time`: Time in seconds
  - `schema_config`: base or indexed
  - `repetition`: Repetition number

### Overhead Breakdown
- **Location**: `results/raw/overhead_breakdown_q{N}.csv`
- **Columns**:
  - `component`: Overhead component
  - `time_ms`: Time in milliseconds
  - `percentage`: Percentage of total

### Concurrency Results
- **Location**: `results/raw/concurrency_TIMESTAMP.csv`
- **Columns**:
  - `query_num`: Query number
  - `concurrency_level`: Number of threads
  - `throughput`: Queries/second
  - `avg_latency`: Average latency (ms)
  - `p50_latency`: Median latency (ms)
  - `p95_latency`: 95th percentile latency (ms)
  - `p99_latency`: 99th percentile latency (ms)

## Troubleshooting

### Benchmark Hangs
```bash
# Check for database locks
# PostgreSQL:
docker exec orm-benchmark-postgres psql -U bench -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"

# Reduce concurrency or timeout
python scripts/2-benchmark/run_benchmark.py --queries 1 --timeout 300
```

### Out of Memory
```bash
# Reduce repetitions
python scripts/2-benchmark/run_benchmark.py --all --repetitions 1

# Run queries individually
for q in {1..22}; do
    python scripts/2-benchmark/run_benchmark.py --queries $q --repetitions 5
done
```

### Connection Errors
```bash
# Test connections first
python scripts/utils/test_connections.py

# Increase connection timeout
export DB_CONNECTION_TIMEOUT=60

# Check container status
docker ps | grep orm-benchmark
```

### Inconsistent Results
```bash
# Increase warm-up runs
python scripts/2-benchmark/run_benchmark.py --warmup 3 --repetitions 5

# Check system load
top
iostat 1

# Run during off-peak hours
```

## Performance Notes

### Execution Times (SF=1, PostgreSQL)
- **Simple queries (1, 6)**: 0.1-1 second
- **Medium queries (3, 5, 10)**: 1-5 seconds
- **Complex queries (9, 17, 18)**: 5-30 seconds

### Overhead Ranges
- **Django ORM**: 1.2x - 15x baseline
- **SQLAlchemy**: 1.1x - 8x baseline

### Concurrency Limits
- **PostgreSQL**: Up to 100 connections
- **MySQL**: Up to 150 connections
- **Oracle**: Up to 100 connections
- **SQL Server**: Up to 100 connections

## See Also

- [Running Benchmarks Guide](../../docs/03-RUNNING-BENCHMARKS.md)
- [Analysis Guide](../../docs/05-ANALYSIS.md)
- [MOEF Framework](../../docs/04-MOEF-FRAMEWORK.md)
- [Paper Alignment](../../docs/PAPER-ALIGNMENT.md)
- [Reproducibility Guide](../../REPRODUCIBILITY.md)

