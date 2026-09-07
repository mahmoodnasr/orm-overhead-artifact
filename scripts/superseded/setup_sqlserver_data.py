#!/usr/bin/env python3
"""
SQL Server TPC-H Data Loader

This script loads TPC-H data into SQL Server database.
Uses pyodbc directly for better performance.
"""

import os
import sys
from pathlib import Path
import csv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import pyodbc directly
try:
    import pyodbc
except ImportError:
    print("Error: pyodbc package not installed")
    print("Install it with: pip install pyodbc")
    sys.exit(1)


def get_sqlserver_connection():
    """Get direct SQL Server connection (not through Django)."""
    # Use environment variables or defaults
    user = os.getenv('SQLSERVER_USER', 'sa')
    password = os.getenv('SQLSERVER_PASSWORD', 'YourStrong!Passw0rd')
    host = os.getenv('SQLSERVER_HOST', 'localhost')
    port = os.getenv('SQLSERVER_PORT', '1433')
    database = os.getenv('SQLSERVER_DB', 'tpch')
    
    # SQL Server connection string
    conn_str = (
        f'DRIVER={{ODBC Driver 18 for SQL Server}};'
        f'SERVER={host},{port};'
        f'DATABASE={database};'
        f'UID={user};'
        f'PWD={password};'
        f'TrustServerCertificate=yes;'
    )
    
    conn = pyodbc.connect(conn_str, autocommit=False)
    return conn


def load_table_data(cursor, table_name, data_file, num_cols):
    """Load data from .tbl file into SQL Server table."""
    print(f"Loading {table_name}...")
    
    if not data_file.exists():
        print(f"  ⚠ Data file not found: {data_file}")
        return 0
    
    # Use ? placeholders for SQL Server
    placeholders = ', '.join(['?' for _ in range(num_cols)])
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
            
            # Convert empty strings to None, strip whitespace
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
    print("SQL Server TPC-H Data Loader")
    print("=" * 70)
    
    # Get data directory
    data_dir = project_root / 'data' / 'tpch-raw'
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        print("Please run scripts/setup/generate_tpch_data.sh first")
        sys.exit(1)
    
    try:
        # Connect to SQL Server directly (not through Django)
        print("\nConnecting to SQL Server...")
        conn = get_sqlserver_connection()
        cursor = conn.cursor()
        user = os.getenv('SQLSERVER_USER', 'sa')
        print(f"✓ Connected as {user}")
        
        # Check if tables are already populated
        cursor.execute("SELECT COUNT(*) FROM LINEITEM")
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"\n⚠ LINEITEM already has {count:,} rows")
            response = input("Clear all tables and reload? (yes/no): ")
            if response.lower() != 'yes':
                print("Aborted.")
                return
            
            # Clear all tables
            print("\nClearing existing data...")
            tables = ['LINEITEM', 'ORDERS', 'PARTSUPP', 'CUSTOMER', 'SUPPLIER', 'PART', 'NATION', 'REGION']
            for table in tables:
                try:
                    cursor.execute(f"DELETE FROM {table}")
                    conn.commit()
                    print(f"  ✓ Cleared {table}")
                except Exception as e:
                    print(f"  ⚠ Could not clear {table}: {e}")
        
        # Load data (in order of dependencies)
        print("\nLoading data...")
        tables_to_load = [
            ('REGION', data_dir / 'region.tbl.clean', 3),
            ('NATION', data_dir / 'nation.tbl.clean', 4),
            ('SUPPLIER', data_dir / 'supplier.tbl.clean', 7),
            ('CUSTOMER', data_dir / 'customer.tbl.clean', 8),
            ('PART', data_dir / 'part.tbl.clean', 9),
            ('PARTSUPP', data_dir / 'partsupp.tbl.clean', 5),
            ('ORDERS', data_dir / 'orders.tbl.clean', 9),
            ('LINEITEM', data_dir / 'lineitem.tbl.clean', 16),
        ]
        
        total_rows = 0
        for table_name, data_file, num_cols in tables_to_load:
            rows = load_table_data(cursor, table_name, data_file, num_cols)
            total_rows += rows
        
        # Verify data
        print("\nVerifying data...")
        cursor.execute("SELECT COUNT(*) FROM REGION")
        print(f"  REGION: {cursor.fetchone()[0]:,} rows")
        
        cursor.execute("SELECT COUNT(*) FROM NATION")
        print(f"  NATION: {cursor.fetchone()[0]:,} rows")
        
        cursor.execute("SELECT COUNT(*) FROM LINEITEM")
        print(f"  LINEITEM: {cursor.fetchone()[0]:,} rows")
        
        print(f"\n✓ Successfully loaded {total_rows:,} total rows into SQL Server")
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

