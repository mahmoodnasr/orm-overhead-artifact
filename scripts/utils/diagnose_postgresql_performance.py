#!/usr/bin/env python3
"""
PostgreSQL Performance Diagnostic Script for Django ORM Benchmark

This script diagnoses why PostgreSQL queries are running slowly by checking:
1. Index existence and health
2. Table statistics (ANALYZE status)
3. PostgreSQL configuration
4. Query execution plans
5. Comparison with expected performance
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.db import connections
from decimal import Decimal
import time


def print_header(text):
    """Print a formatted header."""
    print(f"\n{'='*80}")
    print(f"  {text}")
    print(f"{'='*80}\n")


def check_indexes(db_alias='postgresql'):
    """Check if indexes are created on PostgreSQL."""
    print_header("INDEX STATUS CHECK")
    
    conn = connections[db_alias]
    with conn.cursor() as cursor:
        # Get all indexes
        cursor.execute("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
            FROM pg_indexes
            JOIN pg_class ON indexname = relname
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname
        """)
        
        indexes = cursor.fetchall()
        
        if not indexes:
            print("❌ NO INDEXES FOUND! This explains the slow queries.")
            print("\nRECOMMENDATION: Run the following command to create indexes:")
            print("  psql -h localhost -p 5433 -U benchmark -d tpch -f data/indexes/postgres_indexes.sql")
            return False
        
        print(f"✓ Found {len(indexes)} indexes:\n")
        
        current_table = None
        for schema, table, index, size in indexes:
            if table != current_table:
                print(f"\n{table}:")
                current_table = table
            print(f"  - {index} ({size})")
        
        # Check for critical missing indexes
        critical_indexes = [
            'idx_lineitem_shipdate',
            'idx_lineitem_orderkey',
            'idx_orders_custkey',
            'idx_orders_orderdate',
            'idx_customer_mktsegment',
        ]
        
        index_names = [idx[2] for idx in indexes]
        missing = [idx for idx in critical_indexes if idx not in index_names]
        
        if missing:
            print(f"\n❌ MISSING CRITICAL INDEXES:")
            for idx in missing:
                print(f"  - {idx}")
            return False
        
        print(f"\n✓ All critical indexes present")
        return True


def check_statistics(db_alias='postgresql'):
    """Check if ANALYZE has been run on tables."""
    print_header("TABLE STATISTICS CHECK")
    
    conn = connections[db_alias]
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT 
                schemaname,
                tablename,
                last_analyze,
                last_autoanalyze,
                n_live_tup as row_count
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        
        stats = cursor.fetchall()
        
        print("Table Statistics Status:\n")
        needs_analyze = []
        
        for schema, table, last_analyze, last_autoanalyze, row_count in stats:
            analyze_status = "✓" if (last_analyze or last_autoanalyze) else "❌"
            analyze_time = last_analyze or last_autoanalyze or "NEVER"
            print(f"{analyze_status} {table:15s} - Rows: {row_count:>12,} - Last ANALYZE: {analyze_time}")
            
            if not (last_analyze or last_autoanalyze):
                needs_analyze.append(table)
        
        if needs_analyze:
            print(f"\n❌ TABLES NEED ANALYZE:")
            for table in needs_analyze:
                print(f"  - {table}")
            print("\nRECOMMENDATION: Run ANALYZE on all tables:")
            print("  psql -h localhost -p 5433 -U benchmark -d tpch -c 'ANALYZE;'")
            return False
        
        print(f"\n✓ All tables have statistics")
        return True


def check_postgres_config(db_alias='postgresql'):
    """Check PostgreSQL configuration settings."""
    print_header("POSTGRESQL CONFIGURATION")
    
    conn = connections[db_alias]
    with conn.cursor() as cursor:
        # Check important settings
        settings_to_check = [
            'shared_buffers',
            'effective_cache_size',
            'work_mem',
            'maintenance_work_mem',
            'random_page_cost',
            'effective_io_concurrency',
            'max_parallel_workers_per_gather',
            'max_worker_processes',
        ]
        
        print("Current PostgreSQL Settings:\n")
        
        for setting in settings_to_check:
            cursor.execute(f"SHOW {setting}")
            value = cursor.fetchone()[0]
            print(f"  {setting:30s} = {value}")
        
        # Get version
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]
        print(f"\n  PostgreSQL Version: {version.split(',')[0]}")


def run_sample_query_test(db_alias='postgresql'):
    """Run a sample query to test performance."""
    print_header("SAMPLE QUERY PERFORMANCE TEST")
    
    from django_app.models import LineItem
    from django.db.models import Sum, Avg, Count, F
    from datetime import date
    
    print("Testing Q01 (Pricing Summary Report)...\n")
    
    cutoff_date = date(1998, 9, 2)
    
    # Test SQL execution
    conn = connections[db_alias]
    sql = """
    SELECT
        l_returnflag,
        l_linestatus,
        SUM(l_quantity) as sum_qty,
        SUM(l_extendedprice) as sum_base_price,
        SUM(l_extendedprice * (1 - l_discount)) as sum_disc_price,
        SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) as sum_charge,
        AVG(l_quantity) as avg_qty,
        AVG(l_extendedprice) as avg_price,
        AVG(l_discount) as avg_disc,
        COUNT(*) as count_order
    FROM lineitem
    WHERE l_shipdate <= '1998-09-02'
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
    """
    
    start = time.perf_counter()
    with conn.cursor() as cursor:
        cursor.execute(sql)
        results = cursor.fetchall()
    sql_time = (time.perf_counter() - start) * 1000
    
    print(f"SQL Execution Time: {sql_time:.2f} ms")
    print(f"Rows Returned: {len(results)}")
    
    # Test ORM execution
    start = time.perf_counter()
    results = list(
        LineItem.objects
        .using(db_alias)
        .filter(shipdate__lte=cutoff_date)
        .values('returnflag', 'linestatus')
        .annotate(
            sum_qty=Sum('quantity'),
            sum_base_price=Sum('extendedprice'),
            sum_disc_price=Sum(F('extendedprice') * (1 - F('discount'))),
            sum_charge=Sum(F('extendedprice') * (1 - F('discount')) * (1 + F('tax'))),
            avg_qty=Avg('quantity'),
            avg_price=Avg('extendedprice'),
            avg_disc=Avg('discount'),
            count_order=Count('*')
        )
        .order_by('returnflag', 'linestatus')
    )
    orm_time = (time.perf_counter() - start) * 1000
    
    print(f"ORM Execution Time: {orm_time:.2f} ms")
    print(f"ORM Overhead: {orm_time - sql_time:.2f} ms ({((orm_time/sql_time - 1) * 100):.1f}%)")
    
    # Performance assessment
    print("\nPerformance Assessment:")
    if sql_time < 100:
        print("  ✓ EXCELLENT - SQL execution is fast (<100ms)")
    elif sql_time < 300:
        print("  ⚠ ACCEPTABLE - SQL execution is moderate (100-300ms)")
    elif sql_time < 1000:
        print("  ❌ SLOW - SQL execution is slow (300-1000ms)")
    else:
        print("  ❌ VERY SLOW - SQL execution is very slow (>1000ms)")
    
    if sql_time > 300:
        print("\n  Likely causes:")
        print("    - Missing indexes (check above)")
        print("    - Outdated statistics (run ANALYZE)")
        print("    - Poor query plan (check EXPLAIN)")
        print("    - Insufficient PostgreSQL memory settings")


def get_query_plan(db_alias='postgresql'):
    """Get query execution plan for Q01."""
    print_header("QUERY EXECUTION PLAN (Q01)")
    
    conn = connections[db_alias]
    
    sql = """
    SELECT
        l_returnflag,
        l_linestatus,
        SUM(l_quantity) as sum_qty,
        SUM(l_extendedprice) as sum_base_price,
        SUM(l_extendedprice * (1 - l_discount)) as sum_disc_price,
        SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) as sum_charge,
        AVG(l_quantity) as avg_qty,
        AVG(l_extendedprice) as avg_price,
        AVG(l_discount) as avg_disc,
        COUNT(*) as count_order
    FROM lineitem
    WHERE l_shipdate <= '1998-09-02'
    GROUP BY l_returnflag, l_linestatus
    ORDER BY l_returnflag, l_linestatus
    """
    
    with conn.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}")
        plan = cursor.fetchall()
        
        print("Execution Plan:\n")
        for line in plan:
            print(f"  {line[0]}")
        
        # Check for sequential scans
        plan_text = '\n'.join([line[0] for line in plan])
        if 'Seq Scan on lineitem' in plan_text:
            print("\n❌ WARNING: Query is using Sequential Scan on lineitem table!")
            print("   This indicates missing or unused indexes.")
            print("   Expected: Index Scan on idx_lineitem_shipdate")


def main():
    """Run all diagnostic checks."""
    print("\n" + "="*80)
    print("  PostgreSQL Performance Diagnostic Tool")
    print("  Django ORM Benchmark - TPC-H")
    print("="*80)
    
    try:
        # Test connection
        conn = connections['postgresql']
        conn.ensure_connection()
        print("\n✓ Successfully connected to PostgreSQL")
        
        # Run all checks
        indexes_ok = check_indexes()
        stats_ok = check_statistics()
        check_postgres_config()
        run_sample_query_test()
        get_query_plan()
        
        # Summary
        print_header("DIAGNOSTIC SUMMARY")
        
        if indexes_ok and stats_ok:
            print("✓ Database appears to be properly configured")
            print("\nIf queries are still slow, consider:")
            print("  1. Increasing PostgreSQL memory settings (shared_buffers, work_mem)")
            print("  2. Checking query execution plans for inefficiencies")
            print("  3. Verifying hardware resources (CPU, RAM, disk I/O)")
        else:
            print("❌ Issues detected that are causing slow queries")
            print("\nACTION REQUIRED:")
            if not indexes_ok:
                print("  1. Create indexes: psql -h localhost -p 5433 -U benchmark -d tpch -f data/indexes/postgres_indexes.sql")
            if not stats_ok:
                print("  2. Update statistics: psql -h localhost -p 5433 -U benchmark -d tpch -c 'ANALYZE;'")
            print("  3. Re-run benchmarks after fixes")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        print("\nMake sure PostgreSQL is running:")
        print("  docker-compose up -d postgresql")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

