# Utility Scripts

Helper scripts for testing, verification, and maintenance.

## Overview

This directory contains utility scripts that support the main benchmark workflow:
1. Test database connections
2. Verify ORM setup and configuration
3. Clean up containers and data
4. Oracle connection management

## Scripts

### `test_connections.py`
Test database connections for all configured databases.

```bash
python scripts/utils/test_connections.py

# Tests:
# - PostgreSQL connection (default)
# - MySQL connection
# - Oracle connection
# - SQL Server connection

# Output:
# ✓ PostgreSQL (default): Connected
# ✓ MySQL (mysql): Connected
# ✓ Oracle (oracle): Connected
# ✓ SQL Server (sqlserver): Connected
```

**Exit Codes**:
- `0`: All connections successful
- `1`: One or more connections failed

### `verify_sqlalchemy_setup.py`
Verify SQLAlchemy ORM setup and query generation.

```bash
python scripts/utils/verify_sqlalchemy_setup.py

# Checks:
# - SQLAlchemy models defined correctly
# - Query generation works
# - SQL syntax is valid for each database
# - ORM can connect and execute queries
```

**Output**: Verification report with pass/fail for each check

### `oracle_connection_manager.py`
Oracle-specific connection utilities (library module).

```python
from scripts.utils.oracle_connection_manager import OracleConnectionManager

# Usage in other scripts:
manager = OracleConnectionManager()
conn = manager.get_connection()
cursor = conn.cursor()
# ... execute queries ...
manager.close_connection(conn)
```

**Features**:
- Connection pooling
- Automatic reconnection
- Cursor management
- Error handling

### `cleanup.sh`
Clean up Docker containers, volumes, and generated data.

```bash
# Clean up everything (WARNING: Destructive!)
./scripts/utils/cleanup.sh --all

# Clean up only containers (keep data)
./scripts/utils/cleanup.sh --containers

# Clean up only generated data (keep containers)
./scripts/utils/cleanup.sh --data

# Clean up results (keep containers and raw data)
./scripts/utils/cleanup.sh --results
```

**Options**:
- `--all`: Remove containers, volumes, and all data
- `--containers`: Stop and remove containers only
- `--data`: Remove generated data files only
- `--results`: Remove results files only
- `--dry-run`: Show what would be removed without removing

## Usage Patterns

### Pattern 1: Pre-Benchmark Checks
```bash
# Before running benchmarks, verify setup
python scripts/utils/test_connections.py
python scripts/utils/verify_sqlalchemy_setup.py

# If all checks pass, proceed to benchmarks
python scripts/2-benchmark/run_benchmark.py --all
```

### Pattern 2: Debugging Connection Issues
```bash
# Test specific database
python scripts/utils/test_connections.py --database default

# Check Docker containers
docker ps | grep orm-benchmark

# Check logs
docker logs orm-benchmark-postgres

# Restart container if needed
docker-compose restart postgres

# Test again
python scripts/utils/test_connections.py --database default
```

### Pattern 3: Clean Slate Reset
```bash
# Complete cleanup and restart
./scripts/utils/cleanup.sh --all

# Restart containers
docker-compose up -d

# Wait for databases
./scripts/1-setup/wait_for_databases.sh

# Regenerate and reload data
./scripts/1-setup/generate_tpch_data.sh 1
./scripts/1-setup/load_data_all.sh

# Verify
python scripts/utils/test_connections.py
```

### Pattern 4: Results Cleanup (Keep Data)
```bash
# Remove old results but keep data
./scripts/utils/cleanup.sh --results

# Run new benchmarks
python scripts/2-benchmark/run_benchmark.py --all
```

## Connection Testing Details

### PostgreSQL
```python
# Connection string:
postgresql://bench:bench@localhost:5432/tpch

# Tests:
# - Connect to database
# - Execute simple query: SELECT 1
# - Verify TPC-H schema exists
# - Check table counts
```

### MySQL
```python
# Connection string:
mysql+pymysql://bench:bench@localhost:3306/tpch

# Tests:
# - Connect to database
# - Execute simple query: SELECT 1
# - Verify character encoding (UTF-8)
# - Check table counts
```

### Oracle
```python
# Connection string:
oracle+cx_oracle://system:oracle@localhost:1521/ORCLPDB1

# Tests:
# - Connect to database
# - Execute simple query: SELECT 1 FROM DUAL
# - Verify tablespace
# - Check table counts
```

### SQL Server
```python
# Connection string:
mssql+pyodbc://sa:YourStrong@Passw0rd@localhost:1433/tpch?driver=ODBC+Driver+17+for+SQL+Server

# Tests:
# - Connect to database
# - Execute simple query: SELECT 1
# - Verify collation
# - Check table counts
```

## SQLAlchemy Verification

### Model Verification
```python
# Checks all SQLAlchemy models:
# - LINEITEM
# - ORDERS
# - CUSTOMER
# - PART
# - SUPPLIER
# - PARTSUPP
# - NATION
# - REGION

# Verifies:
# - Table name mapping
# - Column definitions
# - Primary keys
# - Foreign keys (if declared)
```

### Query Generation Verification
```python
# Tests query generation for TPC-H queries:
for query_num in range(1, 23):
    # Generate SQLAlchemy query
    # Convert to SQL string
    # Validate SQL syntax
    # Compare to raw SQL template
```

## Cleanup Script Details

### Cleanup Targets

#### Containers (`--containers`)
```bash
# Stops and removes:
docker stop orm-benchmark-postgres orm-benchmark-mysql orm-benchmark-oracle orm-benchmark-sqlserver
docker rm orm-benchmark-postgres orm-benchmark-mysql orm-benchmark-oracle orm-benchmark-sqlserver

# Also removes networks:
docker network rm orm-benchmark-network
```

#### Data (`--data`)
```bash
# Removes:
data/tpch-raw/*.tbl
data/tpch-raw/*.tbl.clean
tpch-dbgen/dbgen
tpch-dbgen/qgen
tpch-dbgen/*.o
tpch-dbgen/*.tbl
```

#### Results (`--results`)
```bash
# Removes:
results/raw/*.csv
results/processed/*.csv
results/figures/*.png
results/figures/*.pdf
results/moef/
logs/*.log
```

#### All (`--all`)
```bash
# Combines all of the above, plus:
docker volume prune -f
docker system prune -f
```

### Safety Features
```bash
# Dry run (safe preview)
./scripts/utils/cleanup.sh --all --dry-run

# Confirmation prompt
./scripts/utils/cleanup.sh --all
# Are you sure? This will remove all containers, volumes, and data. [y/N]:

# Force (skip confirmation)
./scripts/utils/cleanup.sh --all --force
```

## Oracle Connection Manager

### Features

#### Connection Pooling
```python
manager = OracleConnectionManager(pool_size=5)
conn = manager.get_connection()  # From pool
manager.release_connection(conn)  # Back to pool
```

#### Auto-Reconnect
```python
@retry_on_connection_error
def query_with_retry():
    conn = manager.get_connection()
    # ... if connection fails, automatically retry ...
```

#### Cursor Management
```python
with manager.get_cursor() as cursor:
    cursor.execute("SELECT * FROM lineitem")
    # Automatically closed
```

### Usage in Scripts
```python
# In benchmark scripts:
from scripts.utils.oracle_connection_manager import OracleConnectionManager

oracle_mgr = OracleConnectionManager()

def run_oracle_query(query):
    with oracle_mgr.get_cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchall()
```

## Troubleshooting

### Connection Test Failures

#### PostgreSQL
```bash
# Check container
docker ps | grep postgres

# Check logs
docker logs orm-benchmark-postgres

# Check port
netstat -an | grep 5432

# Test manually
psql -h localhost -U bench -d tpch
```

#### MySQL
```bash
# Check container
docker ps | grep mysql

# Check logs
docker logs orm-benchmark-mysql

# Test manually
mysql -h 127.0.0.1 -u bench -pbench tpch
```

#### Oracle
```bash
# Check container
docker ps | grep oracle

# Check logs (verbose)
docker logs orm-benchmark-oracle | tail -100

# Check listener
docker exec orm-benchmark-oracle lsnrctl status

# Test manually
sqlplus system/oracle@//localhost:1521/ORCLPDB1
```

#### SQL Server
```bash
# Check container
docker ps | grep sqlserver

# Check logs
docker logs orm-benchmark-sqlserver

# Test manually
sqlcmd -S localhost,1433 -U sa -P 'YourStrong@Passw0rd'
```

### SQLAlchemy Verification Failures
```bash
# Check models are defined
python -c "from django_app.models import *; print(dir())"

# Check SQLAlchemy version
pip show sqlalchemy

# Reinstall if needed
pip install --upgrade sqlalchemy

# Test individual model
python scripts/utils/verify_sqlalchemy_setup.py --model LINEITEM
```

### Cleanup Issues
```bash
# Check what's running
docker ps -a

# Force remove containers
docker rm -f $(docker ps -aq)

# Remove volumes
docker volume ls
docker volume rm orm-benchmark-postgres-data

# Nuclear option (removes everything)
docker system prune -a --volumes -f
```

## Performance Notes

- **Connection testing**: < 5 seconds
- **SQLAlchemy verification**: ~10 seconds
- **Cleanup (containers)**: ~30 seconds
- **Cleanup (all)**: ~1-2 minutes

## See Also

- [Installation Guide](../../docs/02-INSTALLATION.md)
- [Troubleshooting](../../docs/06-TROUBLESHOOTING.md)
- [Getting Started](../../docs/01-GETTING-STARTED.md)
- [Scripts Overview](../README.md)

