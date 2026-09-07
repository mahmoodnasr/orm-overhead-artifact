#!/usr/bin/env python3
"""
Oracle TPC-C Data Loader

This script creates tables and loads TPC-C data into Oracle database.
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


def get_oracle_connection():
    """Get direct Oracle connection (not through Django)."""
    # Try to get password from Oracle container's environment
    # This is the most reliable source for the actual password used
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
        pass  # If docker command fails, fall back to other methods
    
    # Prioritize environment variables (from docker-compose) over Django settings
    # Environment variables are more reliable for setup scripts
    user = os.getenv('ORACLE_USER') or os.getenv('APP_USER', 'benchmark')
    password = container_password or os.getenv('ORACLE_PASSWORD') or os.getenv('APP_USER_PASSWORD', 'benchmark_pass')
    host = os.getenv('ORACLE_HOST', 'localhost')
    port = os.getenv('ORACLE_PORT', '1521')
    service = os.getenv('ORACLE_SERVICE', 'XE')  # Default to XE for Oracle XE
    
    # If environment variables not set, try Django settings as fallback
    if not password or password == 'benchmark_pass':
        try:
            import django
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')
            django.setup()
            from django.conf import settings
            oracle_db = settings.DATABASES.get('oracle', {})
            if oracle_db:
                # Parse NAME which is in format "host:port/service"
                name = oracle_db.get('NAME', '')
                if ':' in name and '/' in name:
                    parts = name.split('/')
                    host_port = parts[0]
                    service_from_django = parts[1] if len(parts) > 1 else 'XEPDB1'
                    if ':' in host_port:
                        host_from_django, port_from_django = host_port.split(':')
                    else:
                        host_from_django = host_port
                        port_from_django = '1521'
                else:
                    host_from_django = os.getenv('ORACLE_HOST', 'localhost')
                    port_from_django = os.getenv('ORACLE_PORT', '1521')
                    service_from_django = os.getenv('ORACLE_SERVICE', 'XEPDB1')
                
                # Only use Django values if environment variables weren't set
                if not os.getenv('ORACLE_USER'):
                    user = oracle_db.get('USER', user)
                if not os.getenv('ORACLE_PASSWORD') and not os.getenv('APP_USER_PASSWORD'):
                    password = oracle_db.get('PASSWORD', password)
                if not os.getenv('ORACLE_HOST'):
                    host = host_from_django
                if not os.getenv('ORACLE_PORT'):
                    port = port_from_django
                if not os.getenv('ORACLE_SERVICE'):
                    service = service_from_django
        except Exception:
            # If Django setup fails, use defaults
            pass
    
    # Try different connection formats
    # Format 1: host:port/service_name
    # Format 2: host:port/?service_name=service_name (for pluggable databases)
    services_to_try = [service, 'XE', 'XEPDB1']
    connection_formats = [
        lambda svc: f"{host}:{port}/{svc}",  # Standard format
        lambda svc: f"{host}:{port}/?service_name={svc}",  # Service name parameter format
    ]
    
    last_error = None
    for svc in services_to_try:
        for fmt in connection_formats:
            dsn = fmt(svc)
            try:
                # Connect using thin mode (no Oracle client needed)
                conn = oracledb.connect(user=user, password=password, dsn=dsn)
                print(f"✓ Connected using DSN: {dsn}")
                return conn
            except Exception as e:
                last_error = e
                continue
    
    # If all connection attempts failed, provide helpful error message
    error_msg = f"Failed to connect to Oracle with user '{user}'"
    if last_error:
        error_msg += f": {last_error}"
    print(f"\n✗ Connection failed. Tried:")
    print(f"  User: {user}")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Services tried: {', '.join(services_to_try)}")
    raise ConnectionError(error_msg)


def create_tables(cursor):
    """Create TPC-C tables in Oracle."""
    print("Creating TPC-C tables...")
    
    # First, purge recycle bin to remove any dropped tables
    print("  Purging recycle bin...")
    try:
        cursor.execute("PURGE RECYCLEBIN")
    except:
        pass
    
    # Query data dictionary to find and drop all objects with TPC-C table names
    print("  Finding and dropping existing TPC-C objects...")
    tables = ['HISTORY', 'ORDER_LINE', 'NEW_ORDER', 'ORDER', 'CUSTOMER', 'STOCK', 'ITEM', 'DISTRICT', 'WAREHOUSE']
    
    # Drop all indexes that reference these tables
    for table in tables:
        try:
            # Find all indexes on this table (Oracle stores unquoted names in uppercase)
            table_upper = table.upper()
            cursor.execute(f"""
                SELECT index_name FROM user_indexes 
                WHERE table_name = '{table_upper}'
            """)
            for row in cursor.fetchall():
                idx_name = row[0]
                try:
                    cursor.execute(f"DROP INDEX {idx_name}")
                except:
                    pass
        except:
            pass
    
    # Drop existing indexes by name
    indexes = [
        'IDX_DISTRICT_W_ID', 'IDX_CUSTOMER_WD', 'IDX_CUSTOMER_WDL', 
        'IDX_HISTORY_CUSTOMER', 'IDX_STOCK_W_ID', 'IDX_STOCK_I_ID',
        'IDX_ORDER_CUSTOMER', 'IDX_NEWORDER_WD', 'IDX_ORDERLINE_ORDER'
    ]
    for idx in indexes:
        try:
            cursor.execute(f"DROP INDEX {idx}")
        except:
            pass
    
    # Drop existing tables (in reverse dependency order to avoid constraint issues)
    # Use CASCADE CONSTRAINTS to drop foreign keys, and PURGE to remove from recycle bin
    for table in tables:
        try:
            # Use quoted table name for ORDER since it's a reserved word
            table_name = f'"{table}"' if table == 'ORDER' else table
            cursor.execute(f"DROP TABLE {table_name} CASCADE CONSTRAINTS PURGE")
            print(f"  Dropped existing {table}")
        except Exception as e:
            # Table doesn't exist or already dropped - this is fine
            pass
    
    # Drop any views with these names
    for table in tables:
        try:
            table_name = f'"{table}"' if table == 'ORDER' else table
            cursor.execute(f"DROP VIEW {table_name} CASCADE CONSTRAINTS")
        except:
            pass
    
    # Drop any sequences that might have been created
    sequences = ['WAREHOUSE_SEQ', 'DISTRICT_SEQ', 'CUSTOMER_SEQ', 'ITEM_SEQ', 
                 'STOCK_SEQ', 'ORDER_SEQ', 'NEW_ORDER_SEQ', 'ORDER_LINE_SEQ', 'HISTORY_SEQ']
    for seq in sequences:
        try:
            cursor.execute(f"DROP SEQUENCE {seq}")
        except:
            pass
    
    # Commit the drops
    cursor.connection.commit()
    
    # Final purge of recycle bin
    try:
        cursor.execute("PURGE RECYCLEBIN")
    except:
        pass
    
    # Small delay to ensure Oracle has processed all drops
    import time
    time.sleep(0.5)
    
    # Create WAREHOUSE table
    cursor.execute("""
        CREATE TABLE WAREHOUSE (
            W_ID NUMBER(10) PRIMARY KEY,
            W_NAME CHAR(10),
            W_STREET_1 VARCHAR2(20),
            W_STREET_2 VARCHAR2(20),
            W_CITY VARCHAR2(20),
            W_STATE CHAR(2),
            W_ZIP CHAR(9),
            W_TAX NUMBER(4,4),
            W_YTD NUMBER(12,2)
        )
    """)
    print("  ✓ Created WAREHOUSE")
    
    # Create DISTRICT table
    cursor.execute("""
        CREATE TABLE DISTRICT (
            D_ID NUMBER(10),
            D_W_ID NUMBER(10),
            D_NAME CHAR(10),
            D_STREET_1 VARCHAR2(20),
            D_STREET_2 VARCHAR2(20),
            D_CITY VARCHAR2(20),
            D_STATE CHAR(2),
            D_ZIP CHAR(9),
            D_TAX NUMBER(4,4),
            D_YTD NUMBER(12,2),
            D_NEXT_O_ID NUMBER(10),
            PRIMARY KEY (D_W_ID, D_ID),
            FOREIGN KEY (D_W_ID) REFERENCES WAREHOUSE(W_ID)
        )
    """)
    print("  ✓ Created DISTRICT")
    
    # Create CUSTOMER table
    cursor.execute("""
        CREATE TABLE CUSTOMER (
            C_ID NUMBER(10),
            C_D_ID NUMBER(10),
            C_W_ID NUMBER(10),
            C_FIRST VARCHAR2(16),
            C_MIDDLE CHAR(2),
            C_LAST VARCHAR2(16),
            C_STREET_1 VARCHAR2(20),
            C_STREET_2 VARCHAR2(20),
            C_CITY VARCHAR2(20),
            C_STATE CHAR(2),
            C_ZIP CHAR(9),
            C_PHONE CHAR(16),
            C_SINCE TIMESTAMP,
            C_CREDIT CHAR(2),
            C_CREDIT_LIM NUMBER(12,2),
            C_DISCOUNT NUMBER(4,4),
            C_BALANCE NUMBER(12,2),
            C_YTD_PAYMENT NUMBER(12,2),
            C_PAYMENT_CNT NUMBER(10),
            C_DELIVERY_CNT NUMBER(10),
            C_DATA VARCHAR2(500),
            PRIMARY KEY (C_W_ID, C_D_ID, C_ID),
            FOREIGN KEY (C_W_ID) REFERENCES WAREHOUSE(W_ID)
        )
    """)
    print("  ✓ Created CUSTOMER")
    
    # Create HISTORY table
    cursor.execute("""
        CREATE TABLE HISTORY (
            H_C_ID NUMBER(10),
            H_C_D_ID NUMBER(10),
            H_C_W_ID NUMBER(10),
            H_D_ID NUMBER(10),
            H_W_ID NUMBER(10),
            H_DATE TIMESTAMP,
            H_AMOUNT NUMBER(6,2),
            H_DATA VARCHAR2(24)
        )
    """)
    print("  ✓ Created HISTORY")
    
    # Create ITEM table
    cursor.execute("""
        CREATE TABLE ITEM (
            I_ID NUMBER(10) PRIMARY KEY,
            I_IM_ID NUMBER(10),
            I_NAME VARCHAR2(24),
            I_PRICE NUMBER(5,2),
            I_DATA VARCHAR2(50)
        )
    """)
    print("  ✓ Created ITEM")
    
    # Create STOCK table
    cursor.execute("""
        CREATE TABLE STOCK (
            S_I_ID NUMBER(10),
            S_W_ID NUMBER(10),
            S_QUANTITY NUMBER(10),
            S_DIST_01 CHAR(24),
            S_DIST_02 CHAR(24),
            S_DIST_03 CHAR(24),
            S_DIST_04 CHAR(24),
            S_DIST_05 CHAR(24),
            S_DIST_06 CHAR(24),
            S_DIST_07 CHAR(24),
            S_DIST_08 CHAR(24),
            S_DIST_09 CHAR(24),
            S_DIST_10 CHAR(24),
            S_YTD NUMBER(10),
            S_ORDER_CNT NUMBER(10),
            S_REMOTE_CNT NUMBER(10),
            S_DATA VARCHAR2(50),
            PRIMARY KEY (S_W_ID, S_I_ID),
            FOREIGN KEY (S_W_ID) REFERENCES WAREHOUSE(W_ID),
            FOREIGN KEY (S_I_ID) REFERENCES ITEM(I_ID)
        )
    """)
    print("  ✓ Created STOCK")
    
    # Create ORDER table (ORDER is a reserved word in Oracle, so we quote it)
    cursor.execute("""
        CREATE TABLE "ORDER" (
            O_ID NUMBER(10),
            O_D_ID NUMBER(10),
            O_W_ID NUMBER(10),
            O_C_ID NUMBER(10),
            O_ENTRY_D TIMESTAMP,
            O_CARRIER_ID NUMBER(10),
            O_OL_CNT NUMBER(10),
            O_ALL_LOCAL NUMBER(10),
            PRIMARY KEY (O_W_ID, O_D_ID, O_ID),
            FOREIGN KEY (O_W_ID) REFERENCES WAREHOUSE(W_ID)
        )
    """)
    print("  ✓ Created ORDER")
    
    # Create NEW_ORDER table
    cursor.execute("""
        CREATE TABLE NEW_ORDER (
            NO_O_ID NUMBER(10),
            NO_D_ID NUMBER(10),
            NO_W_ID NUMBER(10),
            PRIMARY KEY (NO_W_ID, NO_D_ID, NO_O_ID),
            FOREIGN KEY (NO_W_ID) REFERENCES WAREHOUSE(W_ID)
        )
    """)
    print("  ✓ Created NEW_ORDER")
    
    # Create ORDER_LINE table
    cursor.execute("""
        CREATE TABLE ORDER_LINE (
            OL_O_ID NUMBER(10),
            OL_D_ID NUMBER(10),
            OL_W_ID NUMBER(10),
            OL_NUMBER NUMBER(10),
            OL_I_ID NUMBER(10),
            OL_SUPPLY_W_ID NUMBER(10),
            OL_DELIVERY_D TIMESTAMP,
            OL_QUANTITY NUMBER(10),
            OL_AMOUNT NUMBER(6,2),
            OL_DIST_INFO CHAR(24),
            PRIMARY KEY (OL_W_ID, OL_D_ID, OL_O_ID, OL_NUMBER),
            FOREIGN KEY (OL_W_ID) REFERENCES WAREHOUSE(W_ID)
        )
    """)
    print("  ✓ Created ORDER_LINE")
    
    # Create indexes
    print("\nCreating indexes...")
    cursor.execute("CREATE INDEX IDX_DISTRICT_W_ID ON DISTRICT(D_W_ID)")
    cursor.execute("CREATE INDEX IDX_CUSTOMER_WD ON CUSTOMER(C_W_ID, C_D_ID)")
    cursor.execute("CREATE INDEX IDX_CUSTOMER_WDL ON CUSTOMER(C_W_ID, C_D_ID, C_LAST)")
    cursor.execute("CREATE INDEX IDX_HISTORY_CUSTOMER ON HISTORY(H_C_W_ID, H_C_D_ID, H_C_ID)")
    cursor.execute("CREATE INDEX IDX_STOCK_W_ID ON STOCK(S_W_ID)")
    cursor.execute("CREATE INDEX IDX_STOCK_I_ID ON STOCK(S_I_ID)")
    cursor.execute("CREATE INDEX IDX_ORDER_CUSTOMER ON \"ORDER\"(O_W_ID, O_D_ID, O_C_ID)")
    cursor.execute("CREATE INDEX IDX_NEWORDER_WD ON NEW_ORDER(NO_W_ID, NO_D_ID)")
    cursor.execute("CREATE INDEX IDX_ORDERLINE_ORDER ON ORDER_LINE(OL_W_ID, OL_D_ID, OL_O_ID)")
    print("  ✓ Created all indexes")
    
    cursor.connection.commit()
    print("✓ All tables created successfully")


def load_table_data(cursor, table_name, data_file, num_cols, date_columns=None, timestamp_columns=None):
    """Load data from .tbl file into Oracle table using direct oracledb."""
    print(f"Loading {table_name}...")
    
    if not data_file.exists():
        print(f"  ⚠ Data file not found: {data_file}")
        return 0
    
    # Quote table name if it's a reserved word (ORDER)
    quoted_table_name = f'"{table_name}"' if table_name == 'ORDER' else table_name
    
    # Build INSERT with TO_DATE/TO_TIMESTAMP for date/timestamp columns
    placeholders = []
    for i in range(num_cols):
        if timestamp_columns and i in timestamp_columns:
            placeholders.append(f"TO_TIMESTAMP(:{i+1}, 'YYYY-MM-DD HH24:MI:SS')")
        elif date_columns and i in date_columns:
            placeholders.append(f"TO_DATE(:{i+1}, 'YYYY-MM-DD')")
        else:
            placeholders.append(f':{i+1}')
    insert_sql = f"INSERT INTO {quoted_table_name} VALUES ({', '.join(placeholders)})"
    
    rows_loaded = 0
    batch_size = 1000
    batch = []
    
    with open(data_file, 'r', encoding='latin-1') as f:
        reader = csv.reader(f, delimiter='|')
        for row in reader:
            # Remove empty trailing field (TPC-C files end with |)
            if row and row[-1] == '':
                row = row[:-1]
            
            if len(row) != num_cols:
                continue
            
            # Convert empty strings and "None" strings to None, handle timestamp columns
            processed_row = []
            for i, val in enumerate(row):
                val = val.strip()
                # Convert empty strings or "None" (case-insensitive) to None
                if not val or val.lower() == 'none':
                    processed_row.append(None)
                elif timestamp_columns and i in timestamp_columns:
                    # Timestamp column - keep as string, Oracle will convert
                    processed_row.append(val)
                elif date_columns and i in date_columns:
                    # Date column - keep as string, Oracle will convert
                    processed_row.append(val)
                else:
                    processed_row.append(val)
            
            batch.append(tuple(processed_row))
            
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
    print("Oracle TPC-C Data Loader")
    print("=" * 70)
    
    # Get data directory
    data_dir = project_root / 'data' / 'tpcc-raw'
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        print("Please run scripts/setup/generate_tpcc_data.py first")
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
        # Format: (table_name, data_file, num_cols, date_columns, timestamp_columns)
        tables_to_load = [
            ('WAREHOUSE', data_dir / 'warehouse.tbl.clean', 9, None, None),
            ('DISTRICT', data_dir / 'district.tbl.clean', 11, None, None),
            ('ITEM', data_dir / 'item.tbl.clean', 5, None, None),
            ('STOCK', data_dir / 'stock.tbl.clean', 17, None, None),
            ('CUSTOMER', data_dir / 'customer.tbl.clean', 21, None, [12]),  # Column 12 is C_SINCE (timestamp)
            ('HISTORY', data_dir / 'history.tbl.clean', 8, None, [5]),  # Column 5 is H_DATE (timestamp)
            ('ORDER', data_dir / 'order.tbl.clean', 8, None, [4]),  # Column 4 is O_ENTRY_D (timestamp)
            ('NEW_ORDER', data_dir / 'new_order.tbl.clean', 3, None, None),
            ('ORDER_LINE', data_dir / 'order_line.tbl.clean', 10, None, [6]),  # Column 6 is OL_DELIVERY_D (timestamp, can be NULL)
        ]
        
        total_rows = 0
        for table_info in tables_to_load:
            table_name = table_info[0]
            data_file = table_info[1]
            num_cols = table_info[2]
            date_cols = table_info[3] if len(table_info) > 3 else None
            timestamp_cols = table_info[4] if len(table_info) > 4 else None
            rows = load_table_data(cursor, table_name, data_file, num_cols, date_cols, timestamp_cols)
            total_rows += rows
        
        # Verify data
        print("\nVerifying data...")
        cursor.execute("SELECT COUNT(*) FROM WAREHOUSE")
        print(f"  WAREHOUSE: {cursor.fetchone()[0]:,} rows")
        
        cursor.execute("SELECT COUNT(*) FROM DISTRICT")
        print(f"  DISTRICT: {cursor.fetchone()[0]:,} rows")
        
        cursor.execute("SELECT COUNT(*) FROM CUSTOMER")
        print(f"  CUSTOMER: {cursor.fetchone()[0]:,} rows")
        
        cursor.execute('SELECT COUNT(*) FROM "ORDER"')
        print(f"  ORDER: {cursor.fetchone()[0]:,} rows")
        
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

