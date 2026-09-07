#!/usr/bin/env python3
"""
Oracle TPC-H Data Loader

This script creates tables and loads TPC-H data into Oracle database.
Uses direct oracledb connection to avoid Django's query rewriting.
"""

import os
import sys
from pathlib import Path
import csv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import oracledb directly
try:
    import oracledb
except ImportError:
    print("Error: oracledb package not installed")
    sys.exit(1)


def ensure_benchmark_user_exists(host, port, service, default_password):
    """Ensure benchmark user exists, create if it doesn't."""
    # Try to get actual password from container environment (most reliable)
    import subprocess
    container_password = None
    try:
        result = subprocess.run(
            ['docker', 'exec', 'orm-bench-oracle', 'env'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('APP_USER_PASSWORD='):
                    container_password = line.split('=', 1)[1]
                    break
                elif line.startswith('ORACLE_PASSWORD='):
                    container_password = line.split('=', 1)[1]
                    break
    except Exception:
        pass  # If docker command fails, use default
    
    # Use container password if available, otherwise use default
    system_password = container_password or default_password
    user_password = container_password or os.getenv('ORACLE_PASSWORD', 'benchmark_pass')
    
    dsn = f"{host}:{port}/{service}"
    
    # First, try using OS authentication via docker exec (most reliable)
    try:
        print("  Checking if benchmark user exists...")
        check_user_cmd = f"sqlplus -s / as sysdba <<'EOF'\nALTER SESSION SET CONTAINER = {service};\nSELECT COUNT(*) FROM dba_users WHERE username = 'BENCHMARK';\nEXIT;\nEOF"
        result = subprocess.run(
            ['docker', 'exec', 'orm-bench-oracle', 'bash', '-c', check_user_cmd],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        user_exists = False
        if result.returncode == 0:
            # Parse output - should have a number
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.isdigit():
                    user_exists = int(line) > 0
                    break
        
        if not user_exists:
            print("  Creating benchmark user using OS authentication...")
            create_user_cmd = f"""sqlplus -s / as sysdba <<'EOF'
ALTER SESSION SET CONTAINER = {service};
CREATE USER benchmark IDENTIFIED BY {user_password};
GRANT CONNECT, RESOURCE, CREATE VIEW TO benchmark;
GRANT SELECT ANY TABLE TO benchmark;
GRANT CREATE SESSION TO benchmark;
GRANT UNLIMITED TABLESPACE TO benchmark;
EXIT;
EOF"""
            result = subprocess.run(
                ['docker', 'exec', 'orm-bench-oracle', 'bash', '-c', create_user_cmd],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                print("  ✓ Benchmark user created")
                return True
            else:
                print(f"  ⚠ Failed to create user via OS auth: {result.stderr}")
        else:
            print("  ✓ Benchmark user already exists")
            return True
    except Exception as e:
        print(f"  ⚠ OS authentication failed: {e}")
    
    # Fallback: Try to connect as SYSTEM
    try:
        sys_conn = oracledb.connect(user='SYSTEM', password=system_password, dsn=dsn)
        cursor = sys_conn.cursor()
        
        # Switch to PDB if needed (for container databases)
        try:
            cursor.execute(f"ALTER SESSION SET CONTAINER = {service}")
        except:
            pass  # Not a container database or already in PDB
        
        # Check if user exists in current container/PDB
        cursor.execute("SELECT COUNT(*) FROM dba_users WHERE username = 'BENCHMARK'")
        user_exists = cursor.fetchone()[0] > 0
        
        if not user_exists:
            print("  Creating benchmark user...")
            cursor.execute(f"CREATE USER benchmark IDENTIFIED BY :pwd", {'pwd': user_password})
            cursor.execute("GRANT CONNECT, RESOURCE, CREATE VIEW TO benchmark")
            cursor.execute("GRANT SELECT ANY TABLE TO benchmark")
            cursor.execute("GRANT CREATE SESSION TO benchmark")
            cursor.execute("GRANT UNLIMITED TABLESPACE TO benchmark")
            sys_conn.commit()
            print("  ✓ Benchmark user created")
        else:
            print("  ✓ Benchmark user already exists")
        
        cursor.close()
        sys_conn.close()
        return True
    except Exception as e:
        error_str = str(e)
        # If authentication fails, the password might be wrong - that's okay, we'll try anyway
        if 'ORA-01017' in error_str or 'invalid username/password' in error_str.lower():
            print(f"  ⚠ Could not connect as SYSTEM to create user (password may differ)")
            print(f"     Will attempt connection as benchmark user anyway")
        else:
            print(f"  ⚠ Could not ensure benchmark user exists: {e}")
        return False


def get_oracle_password_from_container():
    """
    Get Oracle password from container environment.
    This ensures we use the same password that the container was initialized with.
    Returns the password if found, None otherwise.
    """
    import subprocess
    try:
        result = subprocess.run(
            ['docker', 'exec', 'orm-bench-oracle', 'env'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('APP_USER_PASSWORD='):
                    return line.split('=', 1)[1]
                elif line.startswith('ORACLE_PASSWORD='):
                    return line.split('=', 1)[1]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        # Docker command failed or container not running - use environment variable or default
        pass
    return None


def get_oracle_connection():
    """Get direct Oracle connection (not through Django)."""
    # First, try to get password from container
    container_password = get_oracle_password_from_container()
    if container_password:
        # Set environment variable so subsequent calls use the correct password
        if not os.getenv('ORACLE_PASSWORD'):
            os.environ['ORACLE_PASSWORD'] = container_password
    
    # Use environment variables or defaults
    user = os.getenv('ORACLE_USER', 'benchmark')
    password = os.getenv('ORACLE_PASSWORD') or container_password or 'benchmark_pass'
    host = os.getenv('ORACLE_HOST', 'localhost')
    port = os.getenv('ORACLE_PORT', '1521')
    service = os.getenv('ORACLE_SERVICE', 'XEPDB1')
    
    print(f"Connecting to Oracle...")
    print(f"  User: {user}")
    print(f"  Host: {host}:{port}")
    print(f"  Service: {service}")
    
    # Try to ensure benchmark user exists (only if connecting as benchmark)
    if user.lower() == 'benchmark':
        try:
            sys_password = os.getenv('ORACLE_PASSWORD') or container_password or 'benchmark_pass'
            ensure_benchmark_user_exists(host, port, service, sys_password)
        except Exception as e:
            print(f"  ⚠ Could not ensure benchmark user exists: {e}")
            # Continue anyway - user might already exist or connection might work
    
    # Try different DSN formats
    dsn = f"{host}:{port}/{service}"
    
    try:
        # Connect using thin mode (no Oracle client needed)
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        print(f"✓ Connected successfully")
        return conn
    except Exception as e:
        error_msg = str(e)
        print(f"✗ Connection failed: {error_msg}")
        
        # If it's an authentication error and we're trying benchmark user,
        # try to create the user first
        if 'ORA-01017' in error_msg or 'invalid username/password' in error_msg.lower():
            if user.lower() == 'benchmark':
                print(f"  Attempting to create benchmark user...")
                try:
                    sys_password = os.getenv('ORACLE_PASSWORD') or container_password or 'benchmark_pass'
                    ensure_benchmark_user_exists(host, port, service, sys_password)
                    # Try connecting again
                    conn = oracledb.connect(user=user, password=password, dsn=dsn)
                    print(f"✓ Connected successfully after creating user")
                    return conn
                except Exception as e2:
                    print(f"✗ Still failed after user creation attempt: {e2}")
        
        raise Exception(f"Failed to connect to Oracle: {error_msg}")


def create_tables(cursor):
    """Create TPC-H tables in Oracle."""
    print("Creating TPC-H tables...")
    
    # Drop existing tables
    tables = ['LINEITEM', 'ORDERS', 'PARTSUPP', 'CUSTOMER', 'SUPPLIER', 'PART', 'NATION', 'REGION']
    for table in tables:
        try:
            cursor.execute(f"DROP TABLE {table} CASCADE CONSTRAINTS")
            print(f"  Dropped existing {table}")
        except:
            pass  # Table doesn't exist
    
    # Create REGION table
    cursor.execute("""
        CREATE TABLE REGION (
            R_REGIONKEY NUMBER(10) PRIMARY KEY,
            R_NAME VARCHAR2(25),
            R_COMMENT VARCHAR2(152)
        )
    """)
    print("  ✓ Created REGION")
    
    # Create NATION table
    cursor.execute("""
        CREATE TABLE NATION (
            N_NATIONKEY NUMBER(10) PRIMARY KEY,
            N_NAME VARCHAR2(25),
            N_REGIONKEY NUMBER(10),
            N_COMMENT VARCHAR2(152),
            FOREIGN KEY (N_REGIONKEY) REFERENCES REGION(R_REGIONKEY)
        )
    """)
    print("  ✓ Created NATION")
    
    # Create SUPPLIER table
    cursor.execute("""
        CREATE TABLE SUPPLIER (
            S_SUPPKEY NUMBER(10) PRIMARY KEY,
            S_NAME VARCHAR2(25),
            S_ADDRESS VARCHAR2(40),
            S_NATIONKEY NUMBER(10),
            S_PHONE VARCHAR2(15),
            S_ACCTBAL NUMBER(12,2),
            S_COMMENT VARCHAR2(101),
            FOREIGN KEY (S_NATIONKEY) REFERENCES NATION(N_NATIONKEY)
        )
    """)
    print("  ✓ Created SUPPLIER")
    
    # Create CUSTOMER table
    cursor.execute("""
        CREATE TABLE CUSTOMER (
            C_CUSTKEY NUMBER(10) PRIMARY KEY,
            C_NAME VARCHAR2(25),
            C_ADDRESS VARCHAR2(40),
            C_NATIONKEY NUMBER(10),
            C_PHONE VARCHAR2(15),
            C_ACCTBAL NUMBER(12,2),
            C_MKTSEGMENT VARCHAR2(10),
            C_COMMENT VARCHAR2(117),
            FOREIGN KEY (C_NATIONKEY) REFERENCES NATION(N_NATIONKEY)
        )
    """)
    print("  ✓ Created CUSTOMER")
    
    # Create PART table
    cursor.execute("""
        CREATE TABLE PART (
            P_PARTKEY NUMBER(10) PRIMARY KEY,
            P_NAME VARCHAR2(55),
            P_MFGR VARCHAR2(25),
            P_BRAND VARCHAR2(10),
            P_TYPE VARCHAR2(25),
            P_SIZE NUMBER(10),
            P_CONTAINER VARCHAR2(10),
            P_RETAILPRICE NUMBER(12,2),
            P_COMMENT VARCHAR2(23)
        )
    """)
    print("  ✓ Created PART")
    
    # Create PARTSUPP table
    cursor.execute("""
        CREATE TABLE PARTSUPP (
            PS_PARTKEY NUMBER(10),
            PS_SUPPKEY NUMBER(10),
            PS_AVAILQTY NUMBER(10),
            PS_SUPPLYCOST NUMBER(12,2),
            PS_COMMENT VARCHAR2(199),
            PRIMARY KEY (PS_PARTKEY, PS_SUPPKEY),
            FOREIGN KEY (PS_PARTKEY) REFERENCES PART(P_PARTKEY),
            FOREIGN KEY (PS_SUPPKEY) REFERENCES SUPPLIER(S_SUPPKEY)
        )
    """)
    print("  ✓ Created PARTSUPP")
    
    # Create ORDERS table
    cursor.execute("""
        CREATE TABLE ORDERS (
            O_ORDERKEY NUMBER(10) PRIMARY KEY,
            O_CUSTKEY NUMBER(10),
            O_ORDERSTATUS VARCHAR2(1),
            O_TOTALPRICE NUMBER(12,2),
            O_ORDERDATE DATE,
            O_ORDERPRIORITY VARCHAR2(15),
            O_CLERK VARCHAR2(15),
            O_SHIPPRIORITY NUMBER(10),
            O_COMMENT VARCHAR2(79),
            FOREIGN KEY (O_CUSTKEY) REFERENCES CUSTOMER(C_CUSTKEY)
        )
    """)
    print("  ✓ Created ORDERS")
    
    # Create LINEITEM table
    cursor.execute("""
        CREATE TABLE LINEITEM (
            L_ORDERKEY NUMBER(10),
            L_PARTKEY NUMBER(10),
            L_SUPPKEY NUMBER(10),
            L_LINENUMBER NUMBER(10),
            L_QUANTITY NUMBER(12,2),
            L_EXTENDEDPRICE NUMBER(12,2),
            L_DISCOUNT NUMBER(12,2),
            L_TAX NUMBER(12,2),
            L_RETURNFLAG VARCHAR2(1),
            L_LINESTATUS VARCHAR2(1),
            L_SHIPDATE DATE,
            L_COMMITDATE DATE,
            L_RECEIPTDATE DATE,
            L_SHIPINSTRUCT VARCHAR2(25),
            L_SHIPMODE VARCHAR2(10),
            L_COMMENT VARCHAR2(44),
            PRIMARY KEY (L_ORDERKEY, L_LINENUMBER),
            FOREIGN KEY (L_ORDERKEY) REFERENCES ORDERS(O_ORDERKEY),
            FOREIGN KEY (L_PARTKEY, L_SUPPKEY) REFERENCES PARTSUPP(PS_PARTKEY, PS_SUPPKEY)
        )
    """)
    print("  ✓ Created LINEITEM")
    
    cursor.connection.commit()
    print("✓ All tables created successfully")


def load_table_data(cursor, table_name, data_file, num_cols, date_columns=None):
    """Load data from .tbl file into Oracle table using direct oracledb."""
    print(f"Loading {table_name}...")
    
    if not data_file.exists():
        print(f"  ⚠ Data file not found: {data_file}")
        return 0
    
    # Build INSERT with TO_DATE for date columns
    if date_columns:
        placeholders = []
        for i in range(num_cols):
            if i in date_columns:
                placeholders.append(f"TO_DATE(:{i+1}, 'YYYY-MM-DD')")
            else:
                placeholders.append(f':{i+1}')
        insert_sql = f"INSERT INTO {table_name} VALUES ({', '.join(placeholders)})"
    else:
        placeholders = ', '.join([f':{i+1}' for i in range(num_cols)])
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
    
    rows_loaded = 0
    batch_size = 1000
    batch = []
    
    with open(data_file, 'r', encoding='latin-1') as f:
        reader = csv.reader(f, delimiter='|')
        for row in reader:
            # Remove empty trailing field (TPC-H files end with |)
            if row and row[-1] == '':
                row = row[:-1]
            
            if len(row) != num_cols:
                continue
            
            # Convert empty strings to None
            processed_row = tuple(val.strip() if val.strip() else None for val in row)
            batch.append(processed_row)
            
            if len(batch) >= batch_size:
                try:
                    cursor.executemany(insert_sql, batch)
                    cursor.connection.commit()
                    rows_loaded += len(batch)
                    if rows_loaded % 10000 == 0:
                        print(f"  Loaded {rows_loaded:,} rows...")
                    batch = []
                except Exception as e:
                    print(f"  Error loading batch at row {rows_loaded}: {e}")
                    cursor.connection.rollback()
                    batch = []
        
        # Load remaining rows
        if batch:
            try:
                cursor.executemany(insert_sql, batch)
                cursor.connection.commit()
                rows_loaded += len(batch)
            except Exception as e:
                print(f"  Error loading final batch: {e}")
                cursor.connection.rollback()
    
    print(f"  ✓ Loaded {rows_loaded:,} rows into {table_name}")
    return rows_loaded


def main():
    """Main execution function."""
    print("=" * 70)
    print("Oracle TPC-H Data Loader")
    print("=" * 70)
    
    # Get data directory
    data_dir = project_root / 'data' / 'tpch-raw'
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        print("Please run scripts/setup/generate_tpch_data.sh first")
        sys.exit(1)
    
    try:
        # Connect to Oracle directly (not through Django)
        print("\nConnecting to Oracle...")
        conn = get_oracle_connection()
        cursor = conn.cursor()
        user = os.getenv('ORACLE_USER', 'benchmark')
        print(f"✓ Connected as {user}")
        
        # Create tables
        print()
        create_tables(cursor)
        
        # Load data (in order of dependencies)
        print("\nLoading data...")
        tables_to_load = [
            ('REGION', data_dir / 'region.tbl.clean', 3, None),
            ('NATION', data_dir / 'nation.tbl.clean', 4, None),
            ('SUPPLIER', data_dir / 'supplier.tbl.clean', 7, None),
            ('CUSTOMER', data_dir / 'customer.tbl.clean', 8, None),
            ('PART', data_dir / 'part.tbl.clean', 9, None),
            ('PARTSUPP', data_dir / 'partsupp.tbl.clean', 5, None),
            ('ORDERS', data_dir / 'orders.tbl.clean', 9, [4]),  # Column 4 is O_ORDERDATE
            ('LINEITEM', data_dir / 'lineitem.tbl.clean', 16, [10, 11, 12]),  # Columns 10, 11, 12 are dates
        ]
        
        total_rows = 0
        for table_info in tables_to_load:
            table_name = table_info[0]
            data_file = table_info[1]
            num_cols = table_info[2]
            date_cols = table_info[3] if len(table_info) > 3 else None
            rows = load_table_data(cursor, table_name, data_file, num_cols, date_cols)
            total_rows += rows
        
        # Verify data
        print("\nVerifying data...")
        cursor.execute("SELECT COUNT(*) FROM REGION")
        print(f"  REGION: {cursor.fetchone()[0]:,} rows")
        
        cursor.execute("SELECT COUNT(*) FROM NATION")
        print(f"  NATION: {cursor.fetchone()[0]:,} rows")
        
        cursor.execute("SELECT COUNT(*) FROM LINEITEM")
        print(f"  LINEITEM: {cursor.fetchone()[0]:,} rows")
        
        print(f"\n✓ Successfully loaded {total_rows:,} total rows into Oracle")
        print("=" * 70)
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

