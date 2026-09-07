# Reproducibility Guide


> **Current as of the SF10 four-system campaign.** Dataset generation moved
> to DuckDB (`scripts/1-setup/generate_tpch_duckdb.py`) and the loaders now
> stream from it, so any `tpch-dbgen` / `.tbl` / `load_data_*.sh` step below
> has been replaced. `REPRODUCE.md` in the repository root is the path that
> was actually used to produce `results/all_results.csv`.

**Manuscript**: under review; not published, and deliberately not named here
as a journal article until it is  
**Authors**: Mahmoud Nasr, Mohammed El-Ramly, Desoky Abdelqawy  
**Institution**: Cairo University

This guide enables reproduction of all experiments from the paper.

---

## Quick Navigation

- [Quick Start (Minimal)](#quick-start-minimal-reproduction) - Test setup in 30 minutes
- [Full Reproduction](#full-reproduction) - Reproduce all paper results (7 days)
- [Hardware Requirements](#hardware-requirements)
- [Expected Outputs](#expected-outputs)
- [Validation](#validation-procedures)
- [Troubleshooting](#troubleshooting)

---

## Overview

This reproducibility package provides:

✅ **432 Experimental Configurations**: 2 ORMs × 4 DBMSs × 2 schemas × 27 queries  
✅ **Complete Implementation**: TPC-H (22 queries) + TPC-C (5 transactions)  
✅ **MOEF Framework**: Mechanistic analysis tools for understanding performance  
✅ **Docker Containers**: Pre-configured PostgreSQL, MySQL, Oracle, SQL Server  
✅ **Analysis Scripts**: Generate all paper figures and tables  

---

## Quick Start (Minimal Reproduction)

**Purpose**: Verify setup and generate subset of results  
**Duration**: ~30 minutes  
**Data Scale**: 1GB (SF1)  
**Hardware**: 4 CPUs, 16GB RAM, 100GB storage

### Step 1: Prerequisites

```bash
# Verify prerequisites
docker --version      # Should show Docker 20+
python3 --version     # Should show Python 3.8+
free -h              # Should show 16GB+ RAM available

# macOS: Install ODBC driver for SQL Server
brew install msodbcsql17

# Ubuntu/Debian: Install ODBC driver
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql17
```

### Step 2: One-Command Setup

```bash
# Clone and enter directory
cd orm-benchmark-reproducibility

# Run automated setup (handles everything)
./setup_quick_test.sh
```

This script automatically:
- Creates Python virtual environment
- Installs all dependencies
- Generates TPC-H data (SF1, ~1GB)
- Starts all 4 database containers
- Waits for databases to be ready
- Creates schemas and loads data
- Runs quick validation test

**Expected output**:
```
✓ Virtual environment created
✓ Dependencies installed
✓ TPC-H data generated (1GB)
✓ Docker containers started
✓ Databases ready (PostgreSQL, MySQL, Oracle, SQL Server)
✓ Schemas created and data loaded
✓ Quick test passed

Ready to run benchmarks!
Time: ~20 minutes
```

### Step 3: Run Quick Test

```bash
# Run 3 representative queries on PostgreSQL with both ORMs
source venv/bin/activate
python scripts/2-benchmark/run_benchmark.py \
    --mode quick_test \
    --orm both \
    --database postgresql \
    --queries 1,6,14 \
    --repetitions 3

# Expected duration: ~5 minutes
# Output: results/raw/quick_test_results.csv
```

### Step 4: Verify Results

```bash
# Check results
python scripts/utils/validate_results.py results/raw/quick_test_results.csv

# Expected output:
# ✓ All 18 measurements recorded (3 queries × 2 ORMs × 3 runs)
# ✓ Schema validation passed
# ✓ Overhead values reasonable (0.5x - 10x range)
# ✓ No missing data
```

**Success Criteria**: All validation checks pass ✓

---

## Full Reproduction

**Purpose**: Reproduce all paper results exactly  
**Duration**: ~7 days (168 hours)  
**Data Scale**: 100GB (SF100)  
**Hardware**: 8+ CPUs, 64GB RAM, 500GB SSD

### Time Breakdown

| Phase | Duration | Description |
|-------|----------|-------------|
| Setup | 4-6 hours | Generate SF100 data, load into databases |
| TPC-H Indexed | 48 hours | All queries, indexed schema |
| TPC-H Non-Indexed | 48 hours | All queries, non-indexed schema |
| TPC-C | 48 hours | All transactions, both schemas |
| MOEF Analysis | 12 hours | Execution plans, q-error, mechanisms |
| Figure Generation | 4 hours | All paper figures and tables |
| **Total** | **164 hours** | **~7 days** |

### Full Reproduction Steps

#### 1. Hardware Setup

```bash
# Verify hardware meets requirements
./scripts/utils/check_hardware.py

# Expected output:
# ✓ CPUs: 8 cores detected (minimum 8)
# ✓ RAM: 64.0 GB available (minimum 64)
# ✓ Storage: 523 GB free (minimum 500)
# ✓ Storage type: NVMe SSD (recommended)
# ✓ Network: localhost (databases local)
```

#### 2. Generate SF100 Data

```bash
# Generate 100GB TPC-H dataset
python3 scripts/1-setup/generate_tpch_duckdb.py
./dbgen -s 100
./column_split.sh
cd ..

# Expected: 
# - 8 .tbl files totaling ~100GB
# - Duration: 30-60 minutes
```

#### 3. Setup All Databases

```bash
# Start Docker containers
docker-compose up -d

# Wait for databases (2-3 minutes)
./scripts/1-setup/wait_for_databases.sh

# Load data into all databases (parallel)
./scripts/1-setup/load_all_databases.sh --scale 100

# Expected duration: 3-5 hours (parallel loading)
```

#### 4. Run Complete Benchmark Suite

```bash
# Run all 432 configurations
# superseded - see REPRODUCE.md

# This runs:
# - TPC-H: 22 queries × 2 ORMs × 4 DBMSs × 2 schemas × 9 runs = 3,168 executions
# - TPC-C: 5 transactions × 2 ORMs × 4 DBMSs × 2 schemas × 100 runs = 8,000 executions

# Results saved to:
# - results/raw/tpch/django/indexed/*.csv
# - results/raw/tpch/django/non_indexed/*.csv
# - results/raw/tpch/sqlalchemy/indexed/*.csv
# - results/raw/tpch/sqlalchemy/non_indexed/*.csv
# - results/raw/tpcc/django/indexed/*.csv
# - results/raw/tpcc/django/non_indexed/*.csv
# - results/raw/tpcc/sqlalchemy/indexed/*.csv
# - results/raw/tpcc/sqlalchemy/non_indexed/*.csv
```

#### 5. Run MOEF Analysis

```bash
# Execute complete MOEF framework
./scripts/3-moef/run_moef_pipeline.sh

# This performs:
# Phase 1: Workload Generation (already complete)
# Phase 2: Collect execution plans (2 hours)
# Phase 2: Calculate q-error values (2 hours)
# Phase 3: Join enumeration analysis (2 hours)
# Phase 3: Join method analysis (2 hours)
# Phase 3: Index usage analysis (2 hours)
# Phase 3: Predicate pushdown analysis (2 hours)
# Phase 4: Causal linking (statistical analysis) (2 hours)

# Output:
# - results/execution_plans/**/*.json
# - results/qerror/*.csv
# - results/processed/*.csv
```

#### 6. Generate Paper Figures

```bash
# Generate all figures from paper
python scripts/4-analysis/generate_figures.py --all

# Generates:
# - Figure 2: fig2_complexity_comprehensive.png
# - Figure 3: fig3_overhead_comprehensive.png
# - Figure 6: fig6_q8_q9_comprehensive.png
# - Figure 7: fig7_total_runtime_comprehensive.png
# - Figure (MOEF): fig_moef_framework.pdf
# - Figure (Resources): fig_resource_utilization.png
# - Figure (Benchmark): fig_benchmark_comparison.png
# - Figure (Schema): fig_schema_impact.png

# Output: results/figures/
```

#### 7. Run Statistical Tests

```bash
# Reproduce statistical analysis from paper
python scripts/4-analysis/statistical_tests.py

# Generates:
# - ANOVA results (Table 3.7 variance decomposition)
# - Effect sizes (Cohen's d)
# - Confidence intervals (95% bootstrap)
# - Post-hoc tests (Tukey's HSD)

# Output: results/processed/statistical_analysis.csv
```

---

## Hardware Requirements

### Minimal Reproduction (Quick Test)

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 4 cores | 8 cores |
| **RAM** | 16 GB | 32 GB |
| **Storage** | 100 GB | 200 GB SSD |
| **OS** | Ubuntu 22.04 | Ubuntu 22.04 LTS |
| **Docker** | 20.10+ | Latest |

### Full Reproduction

| Component | Minimum | Recommended | Paper Setup |
|-----------|---------|-------------|-------------|
| **CPU** | 8 cores | 16 cores | Intel Xeon E5-2680 v4 (28 cores) |
| **RAM** | 64 GB | 128 GB | 64 GB |
| **Storage** | 500 GB SSD | 1 TB NVMe | NVMe SSD |
| **OS** | Ubuntu 22.04 | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| **Docker** | 20.10+ | Latest | 24.0.5 |

**Note**: Using less than minimum hardware will increase execution time but should still produce valid results.

---

## Software Dependencies

### System Dependencies

```bash
# Ubuntu/Debian
apt-get update
apt-get install -y \
    build-essential \
    docker.io \
    docker-compose \
    python3.10 \
    python3-pip \
    git \
    curl \
    unixodbc-dev

# macOS
brew install \
    docker \
    python@3.10 \
    git \
    msodbcsql17
```

### Python Dependencies

All Python dependencies are in `requirements.txt`:

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Key packages:
# - Django 4.2
# - SQLAlchemy 2.0
# - psycopg2-binary (PostgreSQL)
# - PyMySQL (MySQL, for BOTH frameworks: Django reaches it through
#   pymysql.install_as_MySQLdb() in django_app/__init__.py, SQLAlchemy
#   through the mysql+pymysql:// DSN. mysqlclient is installed but the
#   shim makes it inert. This guide previously named mysqlclient here,
#   which is not the driver any measurement was taken with — C31.)
# - oracledb (Oracle)
# - pyodbc (SQL Server)
# - pandas, numpy, matplotlib, seaborn (analysis)
# - pyyaml (configuration)
# - pytest (testing)
```

### Database Versions

The Docker containers use these exact versions (per paper Section 3.2):

- **PostgreSQL**: 14.9
- **MySQL**: 8.0.34
- **Oracle Database**: 21c Express Edition
- **SQL Server**: 2019 (CU21)

---

## Expected Outputs

### File Structure

After full reproduction, you should have:

```
results/
├── raw/                          # 432 CSV files (one per configuration)
│   ├── tpch/
│   │   ├── django/
│   │   │   ├── indexed/
│   │   │   │   ├── postgresql.csv    (22 queries × 9 runs = 198 rows)
│   │   │   │   ├── mysql.csv
│   │   │   │   ├── oracle.csv
│   │   │   │   └── sqlserver.csv
│   │   │   └── non_indexed/          (same structure)
│   │   └── sqlalchemy/               (same structure)
│   └── tpcc/                          (same structure)
│
├── execution_plans/               # 432 JSON files
│   ├── django/
│   │   ├── postgresql/
│   │   │   ├── q01_plan.json
│   │   │   └── ... (q02-q22)
│   │   └── ... (mysql, oracle, sqlserver)
│   └── sqlalchemy/                (same structure)
│
├── qerror/
│   ├── qerror_analysis_detailed.csv
│   └── qerror_analysis_by_query.csv
│
├── processed/
│   ├── overhead_summary.csv
│   ├── indexing_impact.csv
│   ├── complexity_analysis.csv
│   ├── variance_decomposition.csv
│   ├── join_enumeration_analysis.csv
│   └── statistical_tests.csv
│
├── figures/
│   ├── fig2_complexity_comprehensive.png
│   ├── fig3_overhead_comprehensive.png
│   ├── fig6_q8_q9_comprehensive.png
│   ├── fig7_total_runtime_comprehensive.png
│   └── ... (8+ figures total)
│
└── metadata/
    ├── system_info.json
    ├── database_versions.json
    └── experiment_config.json
```

### Expected Result Values

Based on paper Section 4 (Results), you should observe:

**TPC-H Overhead (Indexed, Median)**:
| ORM | PostgreSQL | MySQL | Oracle | SQL Server |
|-----|------------|-------|--------|------------|
| Django | 13% | 571% | 726% | 52% |
| SQLAlchemy | 3% | 41% | -1% | 0% |

**TPC-C Throughput (Indexed, QPM)**:
| ORM | PostgreSQL | MySQL | Oracle | SQL Server |
|-----|------------|-------|--------|------------|
| Django | 3,780 | 3,280 | 37 | 2,881 |
| SQLAlchemy | 1,012 | 456 | 305 | 331 |

**Indexing Impact (Total Runtime Change)**:
| ORM | PostgreSQL | MySQL | Oracle | SQL Server |
|-----|------------|-------|--------|------------|
| Django | -12% | +44% | 0% | +12% |
| SQLAlchemy | +98% | +37% | -7% | -24% |

**Acceptable Variance**: ±10% due to hardware differences

---

## Validation Procedures

### Automated Validation

```bash
# Run complete validation suite
python scripts/utils/validate_reproducibility.py

# Checks:
# ✓ All 432 configurations executed
# ✓ 9 runs per configuration
# ✓ Median values calculated correctly
# ✓ Output format matches schema
# ✓ No missing data
# ✓ Values within reasonable ranges
# ✓ Statistical tests pass (p < 0.001)
# ✓ Figures match paper
```

### Manual Validation

#### 1. Check Configuration Count

```bash
find results/raw -name "*.csv" | wc -l
# Expected: 16 files (2 ORMs × 4 DBMSs × 2 benchmarks)
```

#### 2. Verify Run Counts

```bash
# Each CSV should have: 22 queries × 9 runs = 198 rows (+ header)
wc -l results/raw/tpch/django/indexed/postgresql.csv
# Expected: 199 lines
```

#### 3. Compare with Paper

```bash
# Generate comparison report
python scripts/4-analysis/compare_with_paper.py

# Output: Deviation from paper results
# - Mean absolute error: <10%
# - Correlation coefficient: >0.95
# - Key findings preserved: YES/NO
```

---

## Troubleshooting

### Common Issues

#### 1. Docker Container Fails to Start

```bash
# Check Docker service
systemctl status docker

# Check port conflicts
netstat -tulpn | grep -E '5432|3306|1521|1433'

# Restart Docker
docker-compose down
docker-compose up -d
```

#### 2. Database Connection Timeout

```bash
# Check database health
docker-compose ps

# Wait longer (Oracle takes 2-3 minutes)
./scripts/1-setup/wait_for_databases.sh --timeout 300

# Check logs
docker-compose logs postgresql
```

#### 3. Out of Memory During Data Load

```bash
# Increase Docker memory limit
# Edit docker-compose.yml:
services:
  postgresql:
    mem_limit: 16g

# Or reduce scale factor
./scripts/1-setup/load_all_databases.sh --scale 10
```

#### 4. Slow Query Execution

```bash
# Check if indexes are created
python scripts/1-setup/manage_indexes.py --database postgresql --action list

# Verify database is using indexes
# Check explain plans in results/execution_plans/
```

#### 5. Missing ODBC Driver (SQL Server)

```bash
# macOS
brew install msodbcsql17

# Ubuntu/Debian
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql17

# Verify
odbcinst -q -d | grep "ODBC Driver 17"
```

### Getting Help

If you encounter issues not covered here:

1. Check detailed logs: `logs/*.log`
2. Review troubleshooting guide: `docs/06-TROUBLESHOOTING.md`
3. Validate setup: `./scripts/utils/diagnose_setup.sh`
4. Contact authors: See paper for email addresses

---

## Reproducibility Checklist

Before claiming reproduction:

- [ ] All 432 configurations executed successfully
- [ ] Median overhead values within ±10% of paper
- [ ] Statistical tests produce p < 0.001
- [ ] All paper figures generated successfully
- [ ] MOEF analysis completes without errors
- [ ] Q-error values calculated for all queries
- [ ] Variance decomposition matches paper Table 3.7
- [ ] Key findings preserved (e.g., Django vs SQLAlchemy differences)

---

## Citation

If you use this reproducibility package, please cite:

```bibtex
@software{nasr_orm_overhead_artifact,
  title  = {ORM overhead on four database systems: harness, results and
            correction register},
  author = {Nasr, Mahmoud and El-Ramly, Mohammed and Abdelqawy, Desoky},
  year   = {2026},
  url    = {https://github.com/mahmoodnasr/orm-overhead-artifact}
}
```

---

## Additional Resources

- **Paper PDF**: [Link to paper]
- **Dataset DOI**: [Zenodo DOI]
- **Docker Images**: [Docker Hub links]
- **Issue Tracker**: [GitHub issues]
- **Documentation**: See `docs/` directory

---

**Last Updated**: 2024-12-13  
**Package Version**: 1.0.0  
**Contact**: {mahmoud.nasr, mohammed.elramly, desoky.abdelqawy}@cu.edu.eg

