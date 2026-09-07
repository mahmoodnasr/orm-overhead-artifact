#!/usr/bin/env python3
"""
Schema Configuration Manager for TPC-H Benchmark

This script manages database indexes to switch between:
- Indexed schema (with secondary indexes)
- Non-Indexed schema (primary keys only)

Usage:
    python manage_indexes.py --database postgres --action drop
    python manage_indexes.py --database mysql --action create
    python manage_indexes.py --all --action drop    # Drop indexes on all databases
"""

import argparse
import sys
import os
from pathlib import Path

# Initialize oracledb and make it compatible with cx_Oracle for Django
try:
    import oracledb
    
    # Make oracledb.Binary a proper type instead of a function for Django compatibility
    # In oracledb, Binary is a function that returns bytes, but Django's isinstance checks expect a type
    if not isinstance(oracledb.Binary, type):
        # Store the original function
        _original_binary = oracledb.Binary
        # Replace it with bytes type (which is what Binary() returns anyway)
        oracledb.Binary = bytes
    
    # Also fix Timestamp - Django expects it to be a type
    if not isinstance(getattr(oracledb, 'Timestamp', None), type):
        import datetime
        oracledb.Timestamp = datetime.datetime
    
    # Make oracledb available as cx_Oracle for Django Oracle backend compatibility
    sys.modules['cx_Oracle'] = oracledb
    
    # Also set up exception aliases for Django's error handling
    if not hasattr(oracledb, 'Error'):
        oracledb.Error = oracledb.DatabaseError
    if not hasattr(oracledb, 'IntegrityError'):
        oracledb.IntegrityError = oracledb.IntegrityError if hasattr(oracledb, 'IntegrityError') else oracledb.DatabaseError
    
    try:
        oracledb.init_oracle_client()  # Try thick mode first
    except:
        pass  # Thin mode will work fine
except ImportError:
    pass  # Oracle not available

# Add django_app directory to path
django_app_dir = Path(__file__).parent.parent / 'django_app'
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Change to project root for Django to find settings
original_dir = os.getcwd()
os.chdir(str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')

import django
django.setup()

from django.db import connections, connection

# Index definitions by table
# OPTIMIZED INDEX DESIGN based on actual TPC-H query patterns
# Focus: Composite indexes for common filter combinations, essential foreign keys
INDEXES = {
    'lineitem': [
        'idx_lineitem_shipdate',  # Primary filter (Q1, Q3, Q6, Q12, Q14, Q19)
        'idx_lineitem_orderkey',  # Foreign key for joins
        'idx_lineitem_partkey',    # Foreign key for joins
        'idx_lineitem_suppkey',    # Foreign key for joins
        'idx_lineitem_shipdate_discount_qty',  # Composite for Q6
        'idx_lineitem_shipmode_receiptdate',   # Composite for Q12
    ],
    'orders': [
        'idx_orders_custkey',      # Foreign key for joins
        'idx_orders_orderdate',    # Date filter (Q3)
        'idx_orders_orderdate_custkey',  # Composite for Q3
    ],
    'partsupp': [
        'idx_partsupp_partkey',    # Foreign key for joins
        'idx_partsupp_suppkey',    # Foreign key for joins
    ],
    'customer': [
        'idx_customer_nationkey',  # Foreign key for joins
        'idx_customer_mktsegment', # Market segment filter (Q3, Q18)
    ],
    'supplier': [
        'idx_supplier_nationkey',  # Foreign key for joins
    ],
    'part': [
        # Removed: idx_part_type, idx_part_size, idx_part_container
        # These are low-selectivity and rarely help queries
        # Primary key index on p_partkey is sufficient for joins
    ],
    'nation': [
        'idx_nation_regionkey',    # Foreign key for joins
    ],
}

# The TPC-C secondary indexes, from create_tpcc_schema_<vendor>.sql.
#
# These were unmanaged until 2026-09-02, and the consequence reached the
# published results: the SF10 campaign recorded 30 TPC-C rows as "Indexed" and
# 30 as "Non-Indexed" while nothing in the harness ever touched a TPC-C index,
# so the two sets are the same physical configuration measured twice under two
# names. The numbers say as much - PostgreSQL T1 Django SQL reads 0.004346 s
# indexed against 0.003533 s non-indexed, and SQLAlchemy moves the other way,
# which is run-to-run variation in a write workload rather than an index effect.
# Indexed versus non-indexed is one of the study's three primary contrasts, so
# a claim about physical design and transactional overhead would have been
# measuring noise between two identical setups.
#
# Primary keys are deliberately absent from this list. Dropping them would
# change what the schema enforces, not merely how it is accessed, and TPC-C's
# transactions depend on those constraints for correctness.
TPCC_INDEXES = {
    'district':   ['idx_district_w_id'],
    'customer':   ['idx_customer_wd', 'idx_customer_wdl'],
    'history':    ['idx_history_customer'],
    'stock':      ['idx_stock_w_id', 'idx_stock_i_id'],
    'order':      ['idx_order_customer'],
    'new_order':  ['idx_neworder_wd'],
    'order_line': ['idx_orderline_order'],
}

TPCC_INDEX_COLUMNS = {
    'idx_district_w_id':    ('d_w_id',),
    'idx_customer_wd':      ('c_w_id', 'c_d_id'),
    'idx_customer_wdl':     ('c_w_id', 'c_d_id', 'c_last'),
    'idx_history_customer': ('h_c_w_id', 'h_c_d_id', 'h_c_id'),
    'idx_stock_w_id':       ('s_w_id',),
    'idx_stock_i_id':       ('s_i_id',),
    'idx_order_customer':   ('o_w_id', 'o_d_id', 'o_c_id'),
    'idx_neworder_wd':      ('no_w_id', 'no_d_id'),
    'idx_orderline_order':  ('ol_w_id', 'ol_d_id', 'ol_o_id'),
}

# ORDER is a reserved word in every dialect here, so the TPC-C table of that
# name has to be quoted, and each vendor quotes differently. An unquoted
# `CREATE INDEX ... ON order(...)` is a syntax error, not a silent wrong answer,
# but it would fail one index out of nine and leave the configuration half
# applied - which is exactly the state the verify action refuses.
RESERVED_TABLES = {'order'}


def quote_table(name, vendor):
    if name.lower() not in RESERVED_TABLES:
        return name
    if vendor == 'mysql':
        return f"`{name}`"
    if vendor == 'sqlserver':
        return f"[{name}]"
    return f'"{name}"'          # PostgreSQL and Oracle


def get_db_vendor(connection):
    """Get normalized database vendor name."""
    vendor = connection.vendor
    if 'postgres' in vendor:
        return 'postgresql'
    elif 'mysql' in vendor:
        return 'mysql'
    elif 'oracle' in vendor:
        return 'oracle'
    elif 'microsoft' in vendor or 'sqlserver' in str(connection.settings_dict.get('ENGINE', '')):
        return 'sqlserver'
    return vendor


def check_index_exists(cursor, vendor, table, index_name):
    """Check if an index exists."""
    try:
        if vendor == 'postgresql':
            cursor.execute("""
                SELECT 1 FROM pg_indexes 
                WHERE indexname = %s AND tablename = %s
            """, [index_name, table])
        elif vendor == 'mysql':
            cursor.execute("""
                SELECT 1 FROM information_schema.STATISTICS 
                WHERE INDEX_NAME = %s AND TABLE_NAME = %s AND TABLE_SCHEMA = DATABASE()
            """, [index_name, table])
        elif vendor == 'oracle':
            # Django's Oracle backend uses %s format, not :1, :2
            cursor.execute("""
                SELECT 1 FROM USER_INDEXES 
                WHERE INDEX_NAME = %s AND TABLE_NAME = %s
            """, [index_name.upper(), table.upper()])
        elif vendor == 'sqlserver':  # mssql-django uses %s format
            cursor.execute("""
                SELECT 1 FROM sys.indexes i
                JOIN sys.tables t ON i.object_id = t.object_id
                WHERE i.name = %s AND t.name = %s
            """, [index_name, table])
        
        return cursor.fetchone() is not None
    except Exception as e:
        # Don't print warning if it's just checking for non-existent index
        if "does not exist" not in str(e).lower():
            print(f"    Warning: Could not check index {index_name}: {e}")
        return False


def create_indexes(db_alias):
    """Create all indexes for the specified database."""
    conn = connections[db_alias]
    vendor = get_db_vendor(conn)
    cursor = conn.cursor()
    
    print(f"\n{'='*70}")
    print(f"Creating Indexes on {db_alias} ({vendor})")
    print(f"{'='*70}")
    
    created_count = 0
    skipped_count = 0
    failed_count = 0
    
    # Get column name format (lowercase for postgres/mysql, uppercase for oracle/sqlserver)
    col_format = str.lower if vendor in ['postgresql', 'mysql'] else str.upper
    table_format = str.lower if vendor in ['postgresql', 'mysql'] else str.upper
    
    # Index column mappings for whichever benchmark is selected. TPC-C's live
    # in TPCC_INDEX_COLUMNS; --benchmark swaps both dictionaries together so a
    # table list can never be paired with the other benchmark's columns.
    if INDEXES is TPCC_INDEXES:
        index_columns = TPCC_INDEX_COLUMNS
    else:
        index_columns = {
        # LINEITEM indexes
        'idx_lineitem_shipdate': ('l_shipdate',),
        'idx_lineitem_orderkey': ('l_orderkey',),
        'idx_lineitem_partkey': ('l_partkey',),
        'idx_lineitem_suppkey': ('l_suppkey',),
        'idx_lineitem_shipdate_discount_qty': ('l_shipdate', 'l_discount', 'l_quantity'),
        'idx_lineitem_shipmode_receiptdate': ('l_shipmode', 'l_receiptdate', 'l_commitdate', 'l_shipdate'),
        # ORDERS indexes
        'idx_orders_custkey': ('o_custkey',),
        'idx_orders_orderdate': ('o_orderdate',),
        'idx_orders_orderdate_custkey': ('o_orderdate', 'o_custkey'),
        # PARTSUPP indexes
        'idx_partsupp_partkey': ('ps_partkey',),
        'idx_partsupp_suppkey': ('ps_suppkey',),
        # CUSTOMER indexes
        'idx_customer_nationkey': ('c_nationkey',),
        'idx_customer_mktsegment': ('c_mktsegment',),
        # SUPPLIER indexes
        'idx_supplier_nationkey': ('s_nationkey',),
        # NATION indexes
        'idx_nation_regionkey': ('n_regionkey',),
        }

    for table, indexes in INDEXES.items():
        print(f"\n{table}:")
        for idx_name in indexes:
            # Check if index already exists
            if check_index_exists(cursor, vendor, table, idx_name):
                print(f"  ⊙ {idx_name} (already exists)")
                skipped_count += 1
                continue
            
            # Get column names (can be tuple for composite indexes)
            col_names = index_columns.get(idx_name, ())
            if not col_names:
                print(f"  ✗ {idx_name} (unknown column mapping)")
                failed_count += 1
                continue
            
            # Format table and column names
            fmt_table = table_format(table)
            
            # Handle composite indexes (multiple columns)
            if isinstance(col_names, tuple):
                fmt_cols = ', '.join([col_format(col) for col in col_names])
            else:
                # Backward compatibility: single column as string
                fmt_cols = col_format(col_names)
            
            # ORDER is reserved everywhere; quote it in the dialect's own way.
            fmt_table = quote_table(fmt_table, vendor)

            # SQL Server needs schema prefix
            if vendor == 'sqlserver':
                fmt_table = f"dbo.{fmt_table}"

            try:
                sql = f"CREATE INDEX {idx_name} ON {fmt_table}({fmt_cols})"
                cursor.execute(sql)
                print(f"  ✓ {idx_name} ({fmt_cols})")
                created_count += 1
            except Exception as e:
                print(f"  ✗ {idx_name}: {e}")
                failed_count += 1
    
    update_statistics(db_alias)

    conn.commit()
    cursor.close()

    print(f"\n{'='*70}")
    print(f"Summary: {created_count} created, {skipped_count} skipped, {failed_count} failed")
    print(f"{'='*70}")

    return created_count, skipped_count, failed_count


def update_statistics(db_alias):
    """Rebuild the optimiser's statistics, as its own step.

    This used to run only at the end of create_indexes, which made a correct
    campaign depend on having created the indexes in the same session. A
    database that arrives already indexed - the normal case when a
    configuration is reused - was measured with whatever statistics happened to
    be there.

    It cost the first SQL Server campaign. With auto_create_stats on, the
    optimiser built the missing statistics *during* the run: Q19's django/orm
    path sat at about 6.1 s for six blocks, dropped to 0.29 s at block 7 and
    stayed there, and re-running the same cell afterwards gave 0.18-0.28 s on
    all four paths. A 30x change on a re-run means the campaign measured a
    system that was still adapting to it, which is the same class of defect as
    C19's Oracle result cache: a database feature quietly altering the thing
    under measurement.
    """
    conn = connections[db_alias]
    vendor = get_db_vendor(conn)
    cursor = conn.cursor()
    print(f"\nUpdating statistics...")
    try:
        if vendor == 'postgresql':
            for table in INDEXES.keys():
                cursor.execute(f"ANALYZE {quote_table(table, vendor)}")
            print("  ✓ Statistics updated (ANALYZE)")
        elif vendor == 'mysql':
            for table in INDEXES.keys():
                cursor.execute(f"ANALYZE TABLE {table}")
            print("  ✓ Statistics updated (ANALYZE TABLE)")
        elif vendor == 'oracle':
            # callproc, not an anonymous PL/SQL block. Django's Oracle backend
            # strips a trailing semicolon from every statement, so
            # "BEGIN DBMS_STATS.GATHER_TABLE_STATS(...); END;" arrives as
            # "... END" and dies with PLS-00103 "encountered the symbol
            # end-of-file". That failure was caught by the enclosing except and
            # printed as a warning, so every Oracle campaign in this study has
            # run against whatever statistics happened to exist. The SF0.01
            # shakedown is what surfaced it, in about a minute.
            for table in INDEXES.keys():
                cursor.callproc("DBMS_STATS.GATHER_TABLE_STATS",
                                [conn.settings_dict["USER"].upper(), table.upper()])
            print("  ✓ Statistics updated (DBMS_STATS)")
        elif vendor == 'sqlserver':
            for table in INDEXES.keys():
                cursor.execute(f"UPDATE STATISTICS dbo.{table} WITH FULLSCAN")
            print("  ✓ Statistics updated (UPDATE STATISTICS)")
    except Exception as e:
        print(f"  ⚠ Warning: Could not update statistics: {e}")
        cursor.close()
        return False

    conn.commit()
    cursor.close()
    return True


def drop_indexes(db_alias):
    """Drop all indexes for the specified database."""
    conn = connections[db_alias]
    vendor = get_db_vendor(conn)
    cursor = conn.cursor()
    
    print(f"\n{'='*70}")
    print(f"Dropping Indexes on {db_alias} ({vendor})")
    print(f"{'='*70}")
    
    dropped_count = 0
    skipped_count = 0
    failed_count = 0
    
    for table, indexes in INDEXES.items():
        print(f"\n{table}:")
        for idx_name in indexes:
            # Check if index exists
            if not check_index_exists(cursor, vendor, table, idx_name):
                print(f"  ⊙ {idx_name} (doesn't exist)")
                skipped_count += 1
                continue
            
            # Quoted, like the create path. Only the two vendors that name the
            # table in DROP INDEX are affected, and only for TPC-C, whose
            # ORDER table is a reserved word: dropping idx_order_customer on
            # MySQL failed with a syntax error "near 'order'" while the other
            # eight succeeded, which leaves the database in neither
            # configuration. The verify action is what caught it - the drop
            # reported "7 dropped, 2 failed" and carried on.
            qtable = quote_table(table, vendor)
            try:
                if vendor == 'postgresql':
                    cursor.execute(f"DROP INDEX {idx_name}")
                elif vendor == 'mysql':
                    cursor.execute(f"DROP INDEX {idx_name} ON {qtable}")
                elif vendor == 'oracle':
                    cursor.execute(f"DROP INDEX {idx_name}")
                elif vendor == 'sqlserver':
                    cursor.execute(f"DROP INDEX {idx_name} ON dbo.{qtable}")
                
                print(f"  ✓ {idx_name}")
                dropped_count += 1
            except Exception as e:
                print(f"  ✗ {idx_name}: {e}")
                failed_count += 1
    
    conn.commit()
    cursor.close()
    
    print(f"\n{'='*70}")
    print(f"Summary: {dropped_count} dropped, {skipped_count} skipped, {failed_count} failed")
    print(f"{'='*70}")
    
    return dropped_count, skipped_count, failed_count


def list_indexes(db_alias):
    """List all current indexes for the specified database."""
    conn = connections[db_alias]
    vendor = get_db_vendor(conn)
    cursor = conn.cursor()
    
    print(f"\n{'='*70}")
    print(f"Current Indexes on {db_alias} ({vendor})")
    print(f"{'='*70}")
    
    for table, expected_indexes in INDEXES.items():
        print(f"\n{table}:")
        for idx_name in expected_indexes:
            exists = check_index_exists(cursor, vendor, table, idx_name)
            status = "✓ EXISTS" if exists else "✗ MISSING"
            print(f"  {status:12s} {idx_name}")
    
    cursor.close()
    print()


def verify_indexes(db_alias, expect):
    """Assert the database's actual index state matches the label being recorded.

    `--schema indexed` and `--schema non-indexed` are written onto every raw
    measurement row, and until this existed nothing checked that the database
    agreed. A campaign run against a database whose indexes were never dropped,
    or never recreated, produces rows labelled one way and measured the other -
    and the two configurations are one of the study's three primary contrasts
    (ANALYSIS_PLAN.md section 4). There is no signal in the timings that would
    reveal it, because a query being fast is exactly what "indexed" predicts.

    Returns True when the state matches, and prints what it found either way.
    Partial states - some indexes present, some missing - fail against both
    labels, which is right: that database is in neither configuration.
    """
    conn = connections[db_alias]
    vendor = get_db_vendor(conn)
    cursor = conn.cursor()
    present, missing = [], []
    for table, expected_indexes in INDEXES.items():
        for idx_name in expected_indexes:
            (present if check_index_exists(cursor, vendor, table, idx_name)
             else missing).append(idx_name)
    cursor.close()

    total = len(present) + len(missing)
    if expect in ("indexed", "Indexed"):
        ok, want = not missing, "all present"
    elif expect in ("non-indexed", "non_indexed", "Non-Indexed"):
        ok, want = not present, "all absent"
    else:
        print(f"unknown configuration '{expect}'; expected indexed or non-indexed")
        return False

    print(f"index state on {db_alias} ({vendor}): "
          f"{len(present)}/{total} present, {len(missing)}/{total} missing")
    print(f"  configuration claimed: {expect}  (requires {want})")
    if ok:
        print("  MATCHES")
    else:
        print("  DOES NOT MATCH - refusing to let a run be filed under the "
              "wrong configuration.")
        sample = (missing if expect.startswith("index") else present)[:6]
        print(f"  offending indexes (first {len(sample)}): {', '.join(sample)}")
    return ok


def main():
    parser = argparse.ArgumentParser(
        description='Manage database indexes for TPC-H benchmark schema configurations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create indexes on PostgreSQL for "Indexed" schema
  python manage_indexes.py --database default --action create
  
  # Drop indexes on MySQL for "Non-Indexed" schema testing
  python manage_indexes.py --database mysql --action drop
  
  # List current index status
  python manage_indexes.py --database oracle --action list
  
  # Operate on all databases
  python manage_indexes.py --all --action drop
        """
    )
    
    parser.add_argument(
        '--database', '-d',
        choices=['default', 'postgresql', 'postgres', 'mysql', 'oracle', 'sqlserver'],
        help='Database alias to operate on'
    )
    
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='Operate on all databases'
    )
    
    parser.add_argument(
        '--action',
        choices=['create', 'drop', 'list', 'verify', 'analyze'],
        required=True,
        help='Action to perform: create (add indexes), drop (remove indexes), '
             'list (show status), verify (assert the state matches --expect '
             'and exit non-zero if it does not)'
    )

    parser.add_argument(
        '--benchmark',
        choices=['tpch', 'tpcc'],
        default='tpch',
        help='Which index set to manage. TPC-C keeps its indexes in a separate '
             'database, so point the connection at it (POSTGRES_DB=tpcc or the '
             "vendor's equivalent) as well as passing this flag."
    )

    parser.add_argument(
        '--expect',
        choices=['indexed', 'non-indexed'],
        help='With --action verify: the schema configuration the caller is '
             'about to record on every measurement row. Exits 1 on a mismatch.'
    )
    
    args = parser.parse_args()
    
    if not args.database and not args.all:
        parser.error("Either --database or --all must be specified")

    if args.action == 'verify' and not args.expect:
        parser.error("--action verify requires --expect indexed|non-indexed")

    # Rebind the module-level table list so every action - create, drop, list
    # and verify - operates on one benchmark's indexes. They are swapped as a
    # pair with their column mappings inside create_indexes().
    global INDEXES
    if args.benchmark == 'tpcc':
        INDEXES = TPCC_INDEXES
        print(f"managing the TPC-C index set ({sum(len(v) for v in INDEXES.values())} "
              f"secondary indexes across {len(INDEXES)} tables)")
    
    # Determine which databases to operate on
    if args.all:
        db_aliases = ['default', 'mysql', 'oracle', 'sqlserver']
    else:
        db_aliases = [args.database if args.database != 'postgres' else 'default']
    
    # Execute action on each database
    total_success = 0
    total_failed = 0
    
    for db_alias in db_aliases:
        try:
            conn = connections[db_alias]
            conn.ensure_connection()
            
            if args.action == 'create':
                created, skipped, failed = create_indexes(db_alias)
                total_success += created
                total_failed += failed
            elif args.action == 'drop':
                dropped, skipped, failed = drop_indexes(db_alias)
                total_success += dropped
                total_failed += failed
            elif args.action == 'analyze':
                if not update_statistics(db_alias):
                    total_failed += 1
            elif args.action == 'list':
                list_indexes(db_alias)
            elif args.action == 'verify':
                if not verify_indexes(db_alias, args.expect):
                    total_failed += 1
        
        except Exception as e:
            print(f"\n✗ Error with {db_alias}: {e}")
            # Print full traceback for debugging
            if str(e) == "isinstance() arg 2 must be a type, a tuple of types, or a union":
                import traceback
                traceback.print_exc()
            total_failed += 1
    
    # Print overall summary for multi-database operations
    if len(db_aliases) > 1 and args.action not in ('list', 'verify'):
        print(f"\n{'='*70}")
        print(f"Overall Summary: {total_success} successful, {total_failed} failed")
        print(f"{'='*70}")
    
    return 0 if total_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

