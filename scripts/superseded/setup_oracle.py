#!/usr/bin/env python3
"""
Oracle Database Setup and Data Loading Script

This script:
1. Waits for Oracle to be healthy
2. Creates TPC-H schema
3. Loads data from .tbl.clean files
4. Creates indexes
5. Gathers statistics
"""

import os
import sys
import time
import csv
from pathlib import Path

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Try to import oracledb (the new python-oracledb driver)
try:
    import oracledb
    print("✓ oracledb module loaded successfully")
except ImportError:
    print("✗ Error: oracledb not installed")
    print("  Please install: pip install oracledb")
    sys.exit(1)


def wait_for_oracle(host='localhost', port=1521, service_name='XE', 
                     user='benchmark', password='benchmark_pass', max_attempts=30):
    """Wait for Oracle to be ready"""
    print(f"\nWaiting for Oracle to be ready at {host}:{port}/{service_name}")
    
    for attempt in range(1, max_attempts + 1):
        try:
            conn = oracledb.connect(user=user, password=password, host=host, port=port, service_name=service_name)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM DUAL")
            cursor.close()
            conn.close()
            print(f"✓ Oracle is ready (attempt {attempt}/{max_attempts})")
            return True
        except oracledb.DatabaseError as e:
            if attempt < max_attempts:
                print(f"  Attempt {attempt}/{max_attempts}: {str(e)[:60]}... retrying in 10s")
                time.sleep(10)
            else:
                print(f"✗ Failed to connect to Oracle after {max_attempts} attempts")
                print(f"  Error: {e}")
                return False
    
    return False


def create_schema(conn):
    """Create TPC-H schema in Oracle"""
    print("\nCreating TPC-H schema...")
    
    cursor = conn.cursor()
    
    # Drop tables if they exist
    tables = ['LINEITEM', 'PARTSUPP', 'ORDERS', 'CUSTOMER', 'PART', 'SUPPLIER', 'NATION', 'REGION']
    for table in tables:
        try:
            cursor.execute(f"DROP TABLE {table} CASCADE CONSTRAINTS")
            print(f"  Dropped existing table {table}")
        except oracledb.DatabaseError:
            pass  # Table doesn't exist
    
    conn.commit()
    
    # Create REGION table
    cursor.execute("""
        CREATE TABLE REGION (
            R_REGIONKEY NUMBER PRIMARY KEY,
            R_NAME CHAR(25),
            R_COMMENT VARCHAR2(152)
        )
    """)
    print("  ✓ Created REGION table")
    
    # Create NATION table
    cursor.execute("""
        CREATE TABLE NATION (
            N_NATIONKEY NUMBER PRIMARY KEY,
            N_NAME CHAR(25),
            N_REGIONKEY NUMBER,
            N_COMMENT VARCHAR2(152)
        )
    """)
    print("  ✓ Created NATION table")
    
    # Create CUSTOMER table
    cursor.execute("""
        CREATE TABLE CUSTOMER (
            C_CUSTKEY NUMBER PRIMARY KEY,
            C_NAME VARCHAR2(25),
            C_ADDRESS VARCHAR2(40),
            C_NATIONKEY NUMBER,
            C_PHONE CHAR(15),
            C_ACCTBAL NUMBER(15,2),
            C_MKTSEGMENT CHAR(10),
            C_COMMENT VARCHAR2(117)
        )
    """)
    print("  ✓ Created CUSTOMER table")
    
    # Create SUPPLIER table
    cursor.execute("""
        CREATE TABLE SUPPLIER (
            S_SUPPKEY NUMBER PRIMARY KEY,
            S_NAME CHAR(25),
            S_ADDRESS VARCHAR2(40),
            S_NATIONKEY NUMBER,
            S_PHONE CHAR(15),
            S_ACCTBAL NUMBER(15,2),
            S_COMMENT VARCHAR2(101)
        )
    """)
    print("  ✓ Created SUPPLIER table")
    
    # Create PART table
    cursor.execute("""
        CREATE TABLE PART (
            P_PARTKEY NUMBER PRIMARY KEY,
            P_NAME VARCHAR2(55),
            P_MFGR CHAR(25),
            P_BRAND CHAR(10),
            P_TYPE VARCHAR2(25),
            P_SIZE NUMBER,
            P_CONTAINER CHAR(10),
            P_RETAILPRICE NUMBER(15,2),
            P_COMMENT VARCHAR2(23)
        )
    """)
    print("  ✓ Created PART table")
    
    # Create PARTSUPP table
    cursor.execute("""
        CREATE TABLE PARTSUPP (
            PS_PARTKEY NUMBER,
            PS_SUPPKEY NUMBER,
            PS_AVAILQTY NUMBER,
            PS_SUPPLYCOST NUMBER(15,2),
            PS_COMMENT VARCHAR2(199),
            PRIMARY KEY (PS_PARTKEY, PS_SUPPKEY)
        )
    """)
    print("  ✓ Created PARTSUPP table")
    
    # Create ORDERS table
    cursor.execute("""
        CREATE TABLE ORDERS (
            O_ORDERKEY NUMBER PRIMARY KEY,
            O_CUSTKEY NUMBER,
            O_ORDERSTATUS CHAR(1),
            O_TOTALPRICE NUMBER(15,2),
            O_ORDERDATE DATE,
            O_ORDERPRIORITY CHAR(15),
            O_CLERK CHAR(15),
            O_SHIPPRIORITY NUMBER,
            O_COMMENT VARCHAR2(79)
        )
    """)
    print("  ✓ Created ORDERS table")
    
    # Create LINEITEM table
    cursor.execute("""
        CREATE TABLE LINEITEM (
            L_ORDERKEY NUMBER,
            L_PARTKEY NUMBER,
            L_SUPPKEY NUMBER,
            L_LINENUMBER NUMBER,
            L_QUANTITY NUMBER(15,2),
            L_EXTENDEDPRICE NUMBER(15,2),
            L_DISCOUNT NUMBER(15,2),
            L_TAX NUMBER(15,2),
            L_RETURNFLAG CHAR(1),
            L_LINESTATUS CHAR(1),
            L_SHIPDATE DATE,
            L_COMMITDATE DATE,
            L_RECEIPTDATE DATE,
            L_SHIPINSTRUCT CHAR(25),
            L_SHIPMODE CHAR(10),
            L_COMMENT VARCHAR2(44)
        )
    """)
    print("  ✓ Created LINEITEM table")
    
    conn.commit()
    cursor.close()
    print("✓ Schema creation complete")


def load_table_data(conn, table_name, file_path, column_names):
    """Load data from .tbl.clean file into table"""
    print(f"\nLoading {table_name}...")
    
    if not os.path.exists(file_path):
        print(f"  ✗ File not found: {file_path}")
        return 0
    
    cursor = conn.cursor()
    
    # Prepare INSERT statement
    placeholders = ', '.join([f':{i+1}' for i in range(len(column_names))])
    insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
    
    # Prepare batch insert
    batch_size = 1000
    batch = []
    row_count = 0
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            # Split by pipe and remove trailing pipe
            parts = line.rstrip('\n|').split('|')
            
            if len(parts) != len(column_names):
                continue  # Skip malformed lines
            
            # Convert empty strings to None
            values = [part.strip() if part.strip() else None for part in parts]
            
            batch.append(values)
            row_count += 1
            
            # Execute batch
            if len(batch) >= batch_size:
                cursor.executemany(insert_sql, batch)
                batch = []
                if row_count % 10000 == 0:
                    print(f"  Loaded {row_count:,} rows...")
    
    # Insert remaining rows
    if batch:
        cursor.executemany(insert_sql, batch)
    
    conn.commit()
    cursor.close()
    
    print(f"  ✓ Loaded {row_count:,} rows into {table_name}")
    return row_count


def load_all_data(conn, data_dir):
    """Load all TPC-H tables"""
    print("\n" + "="*60)
    print("Loading TPC-H Data")
    print("="*60)
    
    tables = [
        ('REGION', 'region.tbl.clean', ['R_REGIONKEY', 'R_NAME', 'R_COMMENT']),
        ('NATION', 'nation.tbl.clean', ['N_NATIONKEY', 'N_NAME', 'N_REGIONKEY', 'N_COMMENT']),
        ('CUSTOMER', 'customer.tbl.clean', ['C_CUSTKEY', 'C_NAME', 'C_ADDRESS', 'C_NATIONKEY', 
                                              'C_PHONE', 'C_ACCTBAL', 'C_MKTSEGMENT', 'C_COMMENT']),
        ('SUPPLIER', 'supplier.tbl.clean', ['S_SUPPKEY', 'S_NAME', 'S_ADDRESS', 'S_NATIONKEY',
                                              'S_PHONE', 'S_ACCTBAL', 'S_COMMENT']),
        ('PART', 'part.tbl.clean', ['P_PARTKEY', 'P_NAME', 'P_MFGR', 'P_BRAND', 'P_TYPE',
                                      'P_SIZE', 'P_CONTAINER', 'P_RETAILPRICE', 'P_COMMENT']),
        ('PARTSUPP', 'partsupp.tbl.clean', ['PS_PARTKEY', 'PS_SUPPKEY', 'PS_AVAILQTY',
                                              'PS_SUPPLYCOST', 'PS_COMMENT']),
        ('ORDERS', 'orders.tbl.clean', ['O_ORDERKEY', 'O_CUSTKEY', 'O_ORDERSTATUS', 'O_TOTALPRICE',
                                          'O_ORDERDATE', 'O_ORDERPRIORITY', 'O_CLERK',
                                          'O_SHIPPRIORITY', 'O_COMMENT']),
        ('LINEITEM', 'lineitem.tbl.clean', ['L_ORDERKEY', 'L_PARTKEY', 'L_SUPPKEY', 'L_LINENUMBER',
                                              'L_QUANTITY', 'L_EXTENDEDPRICE', 'L_DISCOUNT', 'L_TAX',
                                              'L_RETURNFLAG', 'L_LINESTATUS', 'L_SHIPDATE',
                                              'L_COMMITDATE', 'L_RECEIPTDATE', 'L_SHIPINSTRUCT',
                                              'L_SHIPMODE', 'L_COMMENT']),
    ]
    
    total_rows = 0
    for table_name, filename, columns in tables:
        file_path = os.path.join(data_dir, filename)
        rows = load_table_data(conn, table_name, file_path, columns)
        total_rows += rows
    
    print(f"\n✓ Total rows loaded: {total_rows:,}")


def create_indexes(conn):
    """Create indexes on TPC-H tables"""
    print("\n" + "="*60)
    print("Creating Indexes")
    print("="*60)
    
    cursor = conn.cursor()
    
    indexes = [
        # LINEITEM indexes
        ("idx_lineitem_orderkey", "LINEITEM", "L_ORDERKEY"),
        ("idx_lineitem_partkey", "LINEITEM", "L_PARTKEY"),
        ("idx_lineitem_suppkey", "LINEITEM", "L_SUPPKEY"),
        ("idx_lineitem_shipdate", "LINEITEM", "L_SHIPDATE"),
        ("idx_lineitem_commitdate", "LINEITEM", "L_COMMITDATE"),
        ("idx_lineitem_receiptdate", "LINEITEM", "L_RECEIPTDATE"),
        
        # ORDERS indexes
        ("idx_orders_custkey", "ORDERS", "O_CUSTKEY"),
        ("idx_orders_orderdate", "ORDERS", "O_ORDERDATE"),
        ("idx_orders_orderpriority", "ORDERS", "O_ORDERPRIORITY"),
        
        # PARTSUPP indexes
        ("idx_partsupp_partkey", "PARTSUPP", "PS_PARTKEY"),
        ("idx_partsupp_suppkey", "PARTSUPP", "PS_SUPPKEY"),
        
        # CUSTOMER indexes
        ("idx_customer_nationkey", "CUSTOMER", "C_NATIONKEY"),
        ("idx_customer_mktsegment", "CUSTOMER", "C_MKTSEGMENT"),
        
        # SUPPLIER indexes
        ("idx_supplier_nationkey", "SUPPLIER", "S_NATIONKEY"),
        
        # PART indexes
        ("idx_part_type", "PART", "P_TYPE"),
        ("idx_part_size", "PART", "P_SIZE"),
        ("idx_part_container", "PART", "P_CONTAINER"),
        
        # NATION indexes
        ("idx_nation_regionkey", "NATION", "N_REGIONKEY"),
    ]
    
    for idx_name, table, column in indexes:
        try:
            cursor.execute(f"CREATE INDEX {idx_name} ON {table}({column})")
            print(f"  ✓ Created index {idx_name}")
        except oracledb.DatabaseError as e:
            print(f"  ✗ Failed to create {idx_name}: {e}")
    
    conn.commit()
    cursor.close()
    print("✓ Index creation complete")


def gather_statistics(conn):
    """Gather table statistics for query optimization"""
    print("\n" + "="*60)
    print("Gathering Statistics")
    print("="*60)
    
    cursor = conn.cursor()
    
    tables = ['REGION', 'NATION', 'CUSTOMER', 'SUPPLIER', 'PART', 'PARTSUPP', 'ORDERS', 'LINEITEM']
    
    for table in tables:
        try:
            cursor.execute(f"BEGIN DBMS_STATS.GATHER_TABLE_STATS(USER, '{table}'); END;")
            print(f"  ✓ Gathered statistics for {table}")
        except oracledb.DatabaseError as e:
            print(f"  ✗ Failed to gather statistics for {table}: {e}")
    
    conn.commit()
    cursor.close()
    print("✓ Statistics gathering complete")


def verify_data(conn):
    """Verify that data was loaded correctly"""
    print("\n" + "="*60)
    print("Verifying Data")
    print("="*60)
    
    cursor = conn.cursor()
    
    tables = ['REGION', 'NATION', 'CUSTOMER', 'SUPPLIER', 'PART', 'PARTSUPP', 'ORDERS', 'LINEITEM']
    
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table:12} {count:>10,} rows")
    
    cursor.close()
    print("✓ Data verification complete")


def main():
    """Main execution"""
    print("="*60)
    print("Oracle TPC-H Setup Script")
    print("="*60)
    
    # Configuration
    host = os.getenv('ORACLE_HOST', 'localhost')
    port = int(os.getenv('ORACLE_PORT', '1521'))
    service_name = os.getenv('ORACLE_SERVICE', 'XE')
    user = os.getenv('ORACLE_USER', 'benchmark')
    password = os.getenv('ORACLE_PASSWORD', 'benchmark_pass')
    data_dir = os.getenv('DATA_DIR', 'data/tpch-raw')
    
    # Make data_dir absolute
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(project_root, data_dir)
    
    print(f"\nConfiguration:")
    print(f"  Host: {host}:{port}")
    print(f"  Service: {service_name}")
    print(f"  User: {user}")
    print(f"  Data Directory: {data_dir}")
    
    # Wait for Oracle to be ready
    if not wait_for_oracle(host, port, service_name, user, password):
        print("\n✗ Failed to connect to Oracle. Please check:")
        print("  1. Oracle container is running: docker ps | grep oracle")
        print("  2. Container logs: docker logs orm-bench-oracle")
        sys.exit(1)
    
    # Connect to Oracle
    try:
        conn = oracledb.connect(user=user, password=password, host=host, port=port, service_name=service_name)
        print(f"\n✓ Connected to Oracle as {user}")
    except oracledb.DatabaseError as e:
        print(f"\n✗ Connection failed: {e}")
        sys.exit(1)
    
    try:
        # Create schema
        create_schema(conn)
        
        # Load data
        load_all_data(conn, data_dir)
        
        # Create indexes
        create_indexes(conn)
        
        # Gather statistics
        gather_statistics(conn)
        
        # Verify data
        verify_data(conn)
        
        print("\n" + "="*60)
        print("✓ Oracle Setup Complete!")
        print("="*60)
        print("\nOracle is now ready for benchmarking.")
        print("You can run the benchmark with:")
        print("  python scripts/benchmark/run_benchmark.py --database oracle --all --repetitions 5")
        
    finally:
        conn.close()


if __name__ == '__main__':
    main()

