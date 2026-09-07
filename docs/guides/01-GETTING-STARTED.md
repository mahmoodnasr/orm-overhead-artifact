# Getting Started


> **Current as of the SF10 four-system campaign.** Dataset generation moved
> to DuckDB (`scripts/1-setup/generate_tpch_duckdb.py`) and the loaders now
> stream from it, so any `tpch-dbgen` / `.tbl` / `load_data_*.sh` step below
> has been replaced. `REPRODUCE.md` in the repository root is the path that
> was actually used to produce `results/all_results.csv`.

**Welcome to the ORM Benchmark Reproducibility Package!**

This guide will get you up and running in 10 minutes.

---

## Prerequisites Checklist

Before starting, ensure you have:

- [ ] **Docker Desktop** installed and running
  - Version 20.10 or later
  - Test: `docker --version`
  
- [ ] **Python 3.8+** installed
  - Test: `python3 --version`
  
- [ ] **16GB RAM minimum** available
  - 64GB recommended for full reproduction
  - Test: `free -h` (Linux) or Activity Monitor (macOS)
  
- [ ] **100GB free disk space**
  - 500GB recommended for full reproduction
  - Test: `df -h`

- [ ] **ODBC Driver 17** for SQL Server (macOS/Linux)
  - macOS: `brew install msodbcsql17`
  - Ubuntu: See installation script below

---

## Quick Setup (10 minutes)

###

 Step 1: Install System Dependencies

**macOS:**
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install ODBC driver
brew install msodbcsql17

# Verify
odbcinst -q -d | grep "ODBC Driver 17"
```

**Ubuntu/Debian:**
```bash
# Install ODBC driver for SQL Server
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql17 unixodbc-dev

# Verify
odbcinst -q -d | grep "ODBC Driver 17"
```

### Step 2: Clone and Setup

```bash
# Navigate to project directory
cd orm-benchmark-reproducibility

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Verify installation
python -c "import django; import sqlalchemy; print('✓ Dependencies installed')"
```

### Step 3: Start Databases

```bash
# Start all database containers
docker-compose up -d

# Wait for databases to be ready (~2-3 minutes)
./scripts/1-setup/wait_for_databases.sh

# Verify all databases are running
docker-compose ps
# Should show 4 containers: postgresql, mysql, oracle, sqlserver
```

### Step 4: Generate Test Data

```bash
# Generate TPC-H data at scale factor 1 (~1GB)
python3 scripts/1-setup/generate_tpch_duckdb.py
./dbgen -s 1
./column_split.sh
cd ..

# Expected: tpch10.duckdb in the repository root, lineitem = 59,986,052 rows
# Duration: ~2 minutes
```

### Step 5: Load Data

```bash
# Load data into all databases (runs in parallel)
./scripts/1-setup/load_all_databases.sh --scale 1

# Expected duration: ~15-30 minutes
# Progress will be displayed for each database
```

---

## First Test Run (5 minutes)

Let's verify everything works by running a quick test:

```bash
# Activate virtual environment if not already active
source venv/bin/activate

# Run Query 1 on PostgreSQL with Django ORM
python scripts/2-benchmark/run_benchmark.py \
    --benchmark tpch \
    --orm django \
    --database postgresql \
    --queries 1 \
    --repetitions 3

# Expected output:
# ✓ Query 1 executed 3 times
# ✓ Results saved to: results/raw/tpch/django/indexed/postgresql.csv
# Execution time: ~30 seconds
```

### Verify Results

```bash
# Check the results file
head -5 results/raw/tpch/django/indexed/postgresql.csv

# Should show:
# - Header row with all columns
# - 3 data rows (one per repetition)
# - ORM overhead metrics
```

**Success!** 🎉 If you see results, your setup is working correctly.

---

## Next Steps

Now that your setup is working, choose your path:

### Path 1: Quick Exploration (30 minutes)

Run a subset of benchmarks to explore the system:

```bash
# Run 3 representative queries with both ORMs
python scripts/2-benchmark/run_benchmark.py \
    --mode quick_test \
    --orm both \
    --database postgresql \
    --queries 1,6,14 \
    --repetitions 3

# View results
python scripts/4-analysis/quick_summary.py results/raw/quick_test_results.csv
```

**Learn more**: [docs/03-RUNNING-BENCHMARKS.md](03-RUNNING-BENCHMARKS.md)

### Path 2: Full Reproduction (7 days)

Reproduce all results from the paper:

```bash
# See detailed instructions
cat REPRODUCIBILITY.md

# Or run automated full reproduction
# superseded - see REPRODUCE.md
```

**Learn more**: [REPRODUCIBILITY.md](../REPRODUCIBILITY.md)

### Path 3: Explore MOEF Framework

Understand the mechanistic analysis:

```bash
# Collect execution plans
python scripts/3-moef/collect_execution_plans.py --queries 8,9

# Calculate q-error
python scripts/3-moef/calculate_qerror.py

# Analyze join strategies
python scripts/3-moef/analyze_join_enumeration.py
```

**Learn more**: [docs/04-MOEF-FRAMEWORK.md](04-MOEF-FRAMEWORK.md)

### Path 4: Extend the Benchmarks

Add your own queries or ORMs:

**Learn more**: [docs/07-EXTENDING.md](07-EXTENDING.md)

---

## Common Issues

### Issue: Docker containers not starting

```bash
# Check if Docker is running
docker info

# Check for port conflicts
netstat -tulpn | grep -E '5432|3306|1521|1433'

# Restart Docker Desktop (macOS)
# Or: sudo systemctl restart docker (Linux)
```

### Issue: Database connection failed

```bash
# Test connections
python scripts/1-setup/test_connections.py

# Should show:
# ✓ PostgreSQL: Connected
# ✓ MySQL: Connected
# ✓ Oracle: Connected
# ✓ SQL Server: Connected
```

If any fail, check:
- Container is running: `docker-compose ps`
- Logs: `docker-compose logs [service]`
- Wait longer for Oracle (takes 2-3 minutes to start)

### Issue: ODBC driver not found

```bash
# Verify ODBC driver installation
odbcinst -q -d

# Should list: ODBC Driver 17 for SQL Server

# Reinstall if missing
# macOS: brew reinstall msodbcsql17
# Ubuntu: apt-get install --reinstall msodbcsql17
```

### Issue: Data generation fails

```bash
# Check if dbgen compiled
ls tpch10.duckdb

# If missing, recompile
# superseded: python3 scripts/1-setup/generate_tpch_duckdb.py
make clean
make
cd ..
```

**More help**: [docs/06-TROUBLESHOOTING.md](06-TROUBLESHOOTING.md)

---

## Quick Reference

### Start/Stop Databases

```bash
# Start all databases
docker-compose up -d

# Stop all databases
docker-compose down

# Restart a specific database
docker-compose restart postgresql
```

### Manage Indexes

```bash
# Create indexes (for "Indexed" schema)
python scripts/1-setup/manage_indexes.py --all --action create

# Drop indexes (for "Non-Indexed" schema)
python scripts/1-setup/manage_indexes.py --all --action drop

# Check index status
python scripts/1-setup/manage_indexes.py --database postgresql --action list
```

### Run Benchmarks

```bash
# Single query
python scripts/2-benchmark/run_benchmark.py \
    --benchmark tpch \
    --orm django \
    --database postgresql \
    --queries 1

# Multiple queries
python scripts/2-benchmark/run_benchmark.py \
    --benchmark tpch \
    --orm both \
    --database all \
    --queries 1,3,5,6 \
    --repetitions 5

# All queries (full benchmark)
python scripts/2-benchmark/run_benchmark.py \
    --benchmark tpch \
    --orm both \
    --database all \
    --all \
    --repetitions 9
```

### View Results

```bash
# List all results
ls results/raw/tpch/django/indexed/

# View CSV
head results/raw/tpch/django/indexed/postgresql.csv

# Generate summary
python scripts/4-analysis/generate_summary.py
```

---

## Documentation Index

- **[02-INSTALLATION.md](02-INSTALLATION.md)** - Detailed installation guide
- **[03-RUNNING-BENCHMARKS.md](03-RUNNING-BENCHMARKS.md)** - Complete benchmark guide
- **[04-MOEF-FRAMEWORK.md](04-MOEF-FRAMEWORK.md)** - MOEF methodology
- **[05-ANALYSIS.md](05-ANALYSIS.md)** - Result analysis guide
- **[06-TROUBLESHOOTING.md](06-TROUBLESHOOTING.md)** - Common problems and solutions
- **[07-EXTENDING.md](07-EXTENDING.md)** - Adding new queries/ORMs
- **[API-REFERENCE.md](API-REFERENCE.md)** - Code documentation
- **[PAPER-ALIGNMENT.md](PAPER-ALIGNMENT.md)** - Paper to code mapping

---

## Getting Help

If you're stuck:

1. **Check troubleshooting guide**: [docs/06-TROUBLESHOOTING.md](06-TROUBLESHOOTING.md)
2. **Run diagnostics**: `./scripts/utils/diagnose_setup.sh`
3. **Check logs**: `logs/*.log` and `docker-compose logs [service]`
4. **Review documentation**: See index above
5. **Contact authors**: See paper for contact information

---

## Success Checklist

Before moving forward, verify:

- [  ] All 4 Docker containers running and healthy
- [ ] Virtual environment activated
- [ ] All Python dependencies installed
- [ ] TPC-H data generated
- [ ] Data loaded into at least one database
- [ ] Test query executed successfully
- [ ] Results file created

Once all items are checked, you're ready to run the full benchmarks! 🚀

---

**Next**: Choose your path above, or read [REPRODUCIBILITY.md](../REPRODUCIBILITY.md) for full reproduction.

**Time to get started**: ~15 minutes (setup) + ~30 minutes (first test)

**Questions?** See [docs/06-TROUBLESHOOTING.md](06-TROUBLESHOOTING.md)

