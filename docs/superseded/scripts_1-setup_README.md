# Setup Scripts

Scripts for initial environment setup, data generation, and database loading.

## Overview

This directory contains scripts for Phase 1 of the benchmark workflow:
1. Generate TPC-H and TPC-C data
2. Wait for database containers to be ready
3. Load data into databases
4. Manage secondary indexes

## Scripts

### Data Generation

#### `generate_tpch_data.sh`
Generate TPC-H benchmark data at specified scale factor.

```bash
./scripts/1-setup/generate_tpch_data.sh [SCALE_FACTOR]

# Examples:
./scripts/1-setup/generate_tpch_data.sh 1    # 1GB dataset
./scripts/1-setup/generate_tpch_data.sh 10   # 10GB dataset
```

**Output**: `data/tpch-raw/*.tbl` files

#### `generate_tpcc_data.py`
Generate TPC-C benchmark data.

```bash
python scripts/1-setup/generate_tpcc_data.py [OPTIONS]

# Examples:
python scripts/1-setup/generate_tpcc_data.py --warehouses 10
```

### Database Readiness

#### `wait_for_databases.sh`
Wait for all database containers to be ready before proceeding.

```bash
./scripts/1-setup/wait_for_databases.sh

# Waits for:
# - PostgreSQL (port 5432)
# - MySQL (port 3306)
# - Oracle (port 1521)
# - SQL Server (port 1433)
```

**Timeout**: 300 seconds (5 minutes)

### Data Loading

#### `load_data_all.sh`
Load data into all databases sequentially.

```bash
./scripts/1-setup/load_data_all.sh
```

#### `load_data_postgres.sh`
Load TPC-H data into PostgreSQL.

```bash
./scripts/1-setup/load_data_postgres.sh
```

**Time**: ~2-5 minutes for SF=1

#### `load_data_mysql.sh`
Load TPC-H data into MySQL.

```bash
./scripts/1-setup/load_data_mysql.sh
```

#### `load_data_oracle.sh`
Load TPC-H data into Oracle Database.

```bash
./scripts/1-setup/load_data_oracle.sh
```

**Note**: Requires Oracle SQL*Loader

#### `load_data_sqlserver.sh`
Load TPC-H data into Microsoft SQL Server.

```bash
./scripts/1-setup/load_data_sqlserver.sh
```

### Index Management

#### `manage_indexes.py`
Create or drop secondary indexes for testing different schema configurations.

```bash
# Create indexes
python scripts/1-setup/manage_indexes.py --action create --database default

# Drop indexes
python scripts/1-setup/manage_indexes.py --action drop --database default

# Check index status
python scripts/1-setup/manage_indexes.py --action status --database default
```

**Indexes Created** (per paper Section 4.2):
- `LINEITEM`: l_orderkey, l_partkey, l_suppkey
- `ORDERS`: o_custkey
- `PARTSUPP`: ps_partkey, ps_suppkey
- Additional DBMS-specific indexes

### Oracle-Specific Setup

#### `setup_oracle.py`
Configure Oracle Database for benchmark.

```bash
python scripts/1-setup/setup_oracle.py
```

#### `setup_oracle_fast.sh`
Fast Oracle setup using parallelization.

```bash
./scripts/1-setup/setup_oracle_fast.sh
```

#### `setup_tpcc_oracle_data.py`
Load TPC-C data into Oracle.

```bash
python scripts/1-setup/setup_tpcc_oracle_data.py
```

### SQL Server-Specific Setup

#### `setup_sqlserver_data.py`
Load data into SQL Server using Python.

```bash
python scripts/1-setup/setup_sqlserver_data.py
```

#### `setup_sqlserver_data.sh`
Shell script wrapper for SQL Server data loading.

```bash
./scripts/1-setup/setup_sqlserver_data.sh
```

### TPC-C Setup

#### `setup_tpcc_postgres.sh`
Load TPC-C schema and data into PostgreSQL.

```bash
./scripts/1-setup/setup_tpcc_postgres.sh
```

## SQL Files

### Schema Creation

- `create_tpcc_schema_postgres.sql` - TPC-C schema for PostgreSQL
- `create_tpcc_schema_mysql.sql` - TPC-C schema for MySQL
- `create_tpcc_schema_sqlserver.sql` - TPC-C schema for SQL Server

### Data Loading

- `load_oracle_data.sql` - Oracle SQL*Loader control
- `load_sqlserver_data.sql` - SQL Server bulk insert

## Typical Workflow

### First-Time Setup
```bash
# 1. Generate data (do this once)
./scripts/1-setup/generate_tpch_data.sh 1

# 2. Start Docker containers
docker-compose up -d

# 3. Wait for databases to be ready
./scripts/1-setup/wait_for_databases.sh

# 4. Load data into databases
./scripts/1-setup/load_data_postgres.sh
./scripts/1-setup/load_data_mysql.sh
# (Oracle and SQL Server as needed)

# 5. Create indexes (optional)
python scripts/1-setup/manage_indexes.py --action create --database default
```

### Schema Configuration Testing
```bash
# Test without indexes
python scripts/1-setup/manage_indexes.py --action drop --database default
# Run benchmarks...

# Test with indexes
python scripts/1-setup/manage_indexes.py --action create --database default
# Run benchmarks...
```

## Troubleshooting

### Data Generation Issues
```bash
# Check TPC-H dbgen is compiled
ls -la tpch-dbgen/dbgen

# Recompile if needed
cd tpch-dbgen && make && cd ..

# Verify data generated
ls -lh data/tpch-raw/*.tbl
```

### Database Not Ready
```bash
# Check Docker containers
docker ps | grep -E 'postgres|mysql|oracle|sqlserver'

# Check logs
docker logs orm-benchmark-postgres

# Restart container if needed
docker-compose restart postgres
```

### Loading Failures
```bash
# Check database connection
python scripts/utils/test_connections.py

# Check data files exist
ls -la data/tpch-raw/

# Check disk space
df -h

# Try loading with verbose output
./scripts/1-setup/load_data_postgres.sh 2>&1 | tee load.log
```

### Index Issues
```bash
# Check current indexes
python scripts/1-setup/manage_indexes.py --action status --database default

# Drop all indexes and recreate
python scripts/1-setup/manage_indexes.py --action drop --database default
python scripts/1-setup/manage_indexes.py --action create --database default
```

## Performance Notes

### Data Generation
- **SF=1**: ~1-2 minutes, ~1GB data
- **SF=10**: ~10-15 minutes, ~10GB data

### Data Loading
- **PostgreSQL**: ~2-5 minutes (SF=1)
- **MySQL**: ~3-6 minutes (SF=1)
- **Oracle**: ~5-10 minutes (SF=1)
- **SQL Server**: ~5-10 minutes (SF=1)

### Index Creation
- **PostgreSQL**: ~1-2 minutes (SF=1)
- **MySQL**: ~2-3 minutes (SF=1)
- **Oracle**: ~2-4 minutes (SF=1)
- **SQL Server**: ~2-4 minutes (SF=1)

## See Also

- [Getting Started Guide](../../docs/01-GETTING-STARTED.md)
- [Installation Guide](../../docs/02-INSTALLATION.md)
- [Troubleshooting](../../docs/06-TROUBLESHOOTING.md)
- [Scripts Overview](../README.md)

