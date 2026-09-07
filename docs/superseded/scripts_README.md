# Scripts Directory

This directory contains all executable scripts for the ORM benchmark project, organized by workflow phase.

## Directory Structure

```
scripts/
├── 1-setup/        Initial setup and data preparation
├── 2-benchmark/    Benchmark execution and measurement
├── 3-moef/         MOEF framework implementation
├── 4-analysis/     Results analysis and visualization
└── utils/          Utility and helper scripts
```

**Design Philosophy**: Scripts are organized numerically (1-4) to reflect the typical workflow sequence, making it clear for new users which scripts to run in what order.

---

## Quick Start

### Complete Workflow
```bash
# Phase 1: Setup
./scripts/1-setup/generate_tpch_data.sh 1
./scripts/1-setup/wait_for_databases.sh
./scripts/1-setup/load_data_postgres.sh

# Phase 2: Benchmark
python scripts/2-benchmark/run_benchmark.py --database default --all --repetitions 5

# Phase 3: MOEF Analysis (optional)
python scripts/3-moef/collect_execution_plans.py --database default --all

# Phase 4: Analysis
python scripts/4-analysis/generate_figures.py --all
```

---

## 1. Setup Scripts (`1-setup/`)

Scripts for initial environment setup, data generation, and loading.

### Key Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `generate_tpch_data.sh` | Generate TPC-H benchmark data | `./scripts/1-setup/generate_tpch_data.sh [SCALE_FACTOR]` |
| `generate_tpcc_data.py` | Generate TPC-C benchmark data | `python scripts/1-setup/generate_tpcc_data.py` |
| `load_data_all.sh` | Load data into all databases | `./scripts/1-setup/load_data_all.sh` |
| `load_data_postgres.sh` | Load data into PostgreSQL | `./scripts/1-setup/load_data_postgres.sh` |
| `load_data_mysql.sh` | Load data into MySQL | `./scripts/1-setup/load_data_mysql.sh` |
| `load_data_oracle.sh` | Load data into Oracle | `./scripts/1-setup/load_data_oracle.sh` |
| `load_data_sqlserver.sh` | Load data into SQL Server | `./scripts/1-setup/load_data_sqlserver.sh` |
| `manage_indexes.py` | Create/drop secondary indexes | `python scripts/1-setup/manage_indexes.py --action [create\|drop]` |
| `wait_for_databases.sh` | Wait for databases to be ready | `./scripts/1-setup/wait_for_databases.sh` |
| `setup_oracle.py` | Oracle-specific setup | `python scripts/1-setup/setup_oracle.py` |
| `setup_oracle_fast.sh` | Fast Oracle setup | `./scripts/1-setup/setup_oracle_fast.sh` |

### Examples

```bash
# Generate 1GB TPC-H data
./scripts/1-setup/generate_tpch_data.sh 1

# Wait for all databases to be ready
./scripts/1-setup/wait_for_databases.sh

# Load data into PostgreSQL
./scripts/1-setup/load_data_postgres.sh

# Create secondary indexes
python scripts/1-setup/manage_indexes.py --action create --database default
```

---

## 2. Benchmark Scripts (`2-benchmark/`)

Scripts for running performance benchmarks and overhead measurements.

### Key Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `run_benchmark.py` | Main benchmark runner (single DB) | `python scripts/2-benchmark/run_benchmark.py --database <DB> [OPTIONS]` |
| `run_all_databases_benchmark.py` | Run on multiple databases | `python scripts/2-benchmark/run_all_databases_benchmark.py --databases <DB1>,<DB2>` |
| `run_benchmark_multi_orm.py` | Compare multiple ORMs | `python scripts/2-benchmark/run_benchmark_multi_orm.py --orms django,sqlalchemy` |
| `measure_overhead_breakdown.py` | Detailed overhead analysis | `python scripts/2-benchmark/measure_overhead_breakdown.py --query <NUM>` |
| `run_concurrency_benchmark.py` | Concurrency testing | `python scripts/2-benchmark/run_concurrency_benchmark.py --database <DB>` |
| `run_per_query_concurrency_benchmark.py` | Per-query concurrency | `python scripts/2-benchmark/run_per_query_concurrency_benchmark.py` |
| `simple_benchmark.py` | Quick smoke test | `python scripts/2-benchmark/simple_benchmark.py` |

### Examples

```bash
# Run all queries on PostgreSQL
python scripts/2-benchmark/run_benchmark.py --database default --all --repetitions 5

# Compare Django vs SQLAlchemy
python scripts/2-benchmark/run_benchmark_multi_orm.py --orms django,sqlalchemy --database default --all

# Measure overhead for query 8
python scripts/2-benchmark/measure_overhead_breakdown.py --query 8 --database default

# Run concurrency test with 1, 10, 25, 50 threads
python scripts/2-benchmark/run_concurrency_benchmark.py --database default --levels 1,10,25,50
```

### Common Options

| Option | Description | Example |
|--------|-------------|---------|
| `--database <alias>` | Database to benchmark | `--database default` |
| `--databases <list>` | Multiple databases | `--databases default,mysql` |
| `--all` | Run all 22 queries | `--all` |
| `--queries <list>` | Specific queries | `--queries 1,6,8,9` |
| `--repetitions <num>` | Repetitions per query | `--repetitions 5` |
| `--orms <list>` | ORMs to compare | `--orms django,sqlalchemy` |
| `--schema-configs <config>` | Schema configuration | `--schema-configs indexed` |
| `--output <dir>` | Output directory | `--output results/raw` |

---

## 3. MOEF Framework Scripts (`3-moef/`)

Scripts implementing the Mechanistic ORM Evaluation Framework (MOEF) for analyzing performance differences through query execution plan analysis.

**Status**: This directory is prepared for MOEF implementation. See [docs/04-MOEF-FRAMEWORK.md](../docs/04-MOEF-FRAMEWORK.md) for methodology.

### Planned Scripts

- `collect_execution_plans.py` - Phase 2: Collect execution plans with runtime statistics
- `calculate_qerror.py` - Phase 2: Calculate q-error for cardinality estimation
- `analyze_mechanisms.py` - Phase 3: Characterize optimizer behavior
- `statistical_linking.py` - Phase 4: Link performance to mechanisms
- `generate_moef_report.py` - Generate comprehensive MOEF analysis report

---

## 4. Analysis Scripts (`4-analysis/`)

Scripts for analyzing benchmark results, generating figures, and validating data.

### Key Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `generate_figures.py` | Generate performance figures | `python scripts/4-analysis/generate_figures.py --all` |
| `generate_paper_aligned_results.py` | Generate paper-aligned results | `python scripts/4-analysis/generate_paper_aligned_results.py` |
| `overhead_decomposition.py` | ORM overhead decomposition | `python scripts/4-analysis/overhead_decomposition.py` |
| `statistical_tests.py` | Statistical analysis | `python scripts/4-analysis/statistical_tests.py` |
| `validate_results.py` | Validate benchmark results | `python scripts/4-analysis/validate_results.py --check-data-integrity` |
| `collect_query_plans.py` | Collect database query plans | `python scripts/4-analysis/collect_query_plans.py --database <DB>` |

### Examples

```bash
# Generate all figures (paper reproduction)
python scripts/4-analysis/generate_figures.py --all --results results/raw/summary_statistics.csv

# Generate paper-aligned results
python scripts/4-analysis/generate_paper_aligned_results.py

# Validate data integrity
python scripts/4-analysis/validate_results.py --check-data-integrity --scale-factor 1

# Collect query plans for analysis
python scripts/4-analysis/collect_query_plans.py --database default --all

# Statistical tests
python scripts/4-analysis/statistical_tests.py --results results/raw/summary_statistics.csv
```

---

## Utility Scripts (`utils/`)

Helper scripts for testing, verification, and maintenance.

### Key Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `test_connections.py` | Test database connections | `python scripts/utils/test_connections.py` |
| `verify_sqlalchemy_setup.py` | Verify SQLAlchemy setup | `python scripts/utils/verify_sqlalchemy_setup.py` |
| `oracle_connection_manager.py` | Oracle connection utilities | (Library) |
| `cleanup.sh` | Clean up containers and data | `./scripts/utils/cleanup.sh` |

### Examples

```bash
# Test all database connections
python scripts/utils/test_connections.py

# Verify SQLAlchemy setup
python scripts/utils/verify_sqlalchemy_setup.py

# Clean up everything
./scripts/utils/cleanup.sh
```

---

## Database Aliases

| Alias | Database System |
|-------|----------------|
| `default` | PostgreSQL 14 |
| `mysql` | MySQL 8.0 |
| `oracle` | Oracle Database 19c |
| `sqlserver` | Microsoft SQL Server 2019 |

---

## Workflow Patterns

### Pattern 1: Quick Test (Single Database)
```bash
# 1. Setup
./scripts/1-setup/generate_tpch_data.sh 1
./scripts/1-setup/wait_for_databases.sh
./scripts/1-setup/load_data_postgres.sh

# 2. Test connections
python scripts/utils/test_connections.py

# 3. Quick benchmark (few queries)
python scripts/2-benchmark/run_benchmark.py --database default --queries 1,6 --repetitions 3

# 4. Validate
python scripts/4-analysis/validate_results.py
```

### Pattern 2: Full Paper Reproduction
```bash
# 1. Setup all databases
./scripts/1-setup/generate_tpch_data.sh 1
./scripts/1-setup/wait_for_databases.sh
./scripts/1-setup/load_data_all.sh

# 2. Run full benchmark (432 configurations)
# See REPRODUCIBILITY.md for complete commands

# 3. Generate figures
python scripts/4-analysis/generate_figures.py --all
```

### Pattern 3: MOEF Analysis
```bash
# 1. Run benchmark with plan collection
python scripts/2-benchmark/run_benchmark.py --database default --all --collect-plans

# 2. Analyze mechanisms (when implemented)
# python scripts/3-moef/analyze_mechanisms.py --database default

# 3. Generate MOEF report
# python scripts/3-moef/generate_moef_report.py
```

### Pattern 4: Overhead Analysis
```bash
# 1. Run overhead breakdown for specific query
python scripts/2-benchmark/measure_overhead_breakdown.py --query 8 --database default

# 2. Analyze overhead decomposition
python scripts/4-analysis/overhead_decomposition.py --query 8

# 3. Statistical tests
python scripts/4-analysis/statistical_tests.py --query 8
```

---

## Migration Guide

Scripts have been reorganized from flat structure to phase-based structure.

### Path Updates

| Old Path | New Path |
|----------|----------|
| `scripts/run_benchmark.py` | `scripts/2-benchmark/run_benchmark.py` |
| `scripts/run_all_databases_benchmark.py` | `scripts/2-benchmark/run_all_databases_benchmark.py` |
| `scripts/measure_overhead_breakdown.py` | `scripts/2-benchmark/measure_overhead_breakdown.py` |
| `scripts/generate_tpch_data.sh` | `scripts/1-setup/generate_tpch_data.sh` |
| `scripts/test_connections.py` | `scripts/utils/test_connections.py` |
| `scripts/setup/*` | `scripts/1-setup/*` |
| `scripts/benchmark/*` | `scripts/2-benchmark/*` |
| `scripts/analysis/*` | `scripts/4-analysis/*` |
| `scripts/utilities/*` | `scripts/utils/*` |

**Backward Compatibility**: Update your commands or create symbolic links if needed.

---

## Deprecated Scripts

The following scripts have been archived to `docs/archive/deprecated_scripts/`:

- `fix_*.py` - One-time migration scripts (Oracle syntax, MySQL compatibility, etc.)
- `convert_queries_to_sqlalchemy.py` - One-time conversion script
- `add_generate_sql_for_vendor.py` - One-time addition script

These scripts are no longer needed for normal operations and are kept for historical reference only.

---

## Troubleshooting

### Script Not Found
```bash
# Verify you're in project root
pwd  # Should end with orm-benchmark-reproducibility

# Check script exists
ls -la scripts/2-benchmark/run_benchmark.py

# Use absolute path if needed
python /full/path/to/scripts/2-benchmark/run_benchmark.py
```

### Permission Denied
```bash
# Make script executable
chmod +x scripts/1-setup/generate_tpch_data.sh

# Or run with bash/python explicitly
bash scripts/1-setup/generate_tpch_data.sh
python scripts/2-benchmark/run_benchmark.py
```

### Python Import Errors
```bash
# Activate virtual environment
source venv/bin/activate

# Verify Python path
which python  # Should show venv/bin/python

# Reinstall dependencies
pip install -r requirements.txt

# Add project root to PYTHONPATH if needed
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Database Connection Errors
```bash
# Test connections
python scripts/utils/test_connections.py

# Wait for databases to be ready
./scripts/1-setup/wait_for_databases.sh

# Check Docker containers
docker ps | grep -E 'postgres|mysql|oracle|sqlserver'

# Check logs
docker logs orm-benchmark-postgres
```

---

## Additional Resources

- **Getting Started**: [docs/01-GETTING-STARTED.md](../docs/01-GETTING-STARTED.md)
- **Running Benchmarks**: [docs/03-RUNNING-BENCHMARKS.md](../docs/03-RUNNING-BENCHMARKS.md)
- **MOEF Framework**: [docs/04-MOEF-FRAMEWORK.md](../docs/04-MOEF-FRAMEWORK.md)
- **Analysis Guide**: [docs/05-ANALYSIS.md](../docs/05-ANALYSIS.md)
- **Troubleshooting**: [docs/06-TROUBLESHOOTING.md](../docs/06-TROUBLESHOOTING.md)
- **Paper Alignment**: [docs/PAPER-ALIGNMENT.md](../docs/PAPER-ALIGNMENT.md)
- **Full Reproduction**: [REPRODUCIBILITY.md](../REPRODUCIBILITY.md)

---

**Last Updated**: December 2024  
**Status**: Reorganization complete, MOEF scripts pending implementation
