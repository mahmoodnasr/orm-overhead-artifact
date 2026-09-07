#!/usr/bin/env python3
"""
Run per-query concurrency/throughput benchmarks with multi-database and index mode support.

This script measures throughput (QPS) at different concurrency levels for each query individually
across multiple databases and schema configurations.

Usage:
    # Single database
    python scripts/run_per_query_concurrency_benchmark.py \
        --benchmark tpch \
        --orm django \
        --database mysql \
        --queries 8,9 \
        --levels 1,5,10,25,50 \
        --duration 60 \
        --index-mode indexed \
        --output-dir results/per_query/

    # Multiple databases
    python scripts/run_per_query_concurrency_benchmark.py \
        --benchmark tpch \
        --orm django \
        --databases mysql,postgresql \
        --all \
        --levels 1,5,10,25,50 \
        --duration 60 \
        --index-mode both \
        --output-dir results/multi_db_concurrency/

    # All databases with both index configurations
    python scripts/run_per_query_concurrency_benchmark.py \
        --benchmark tpch \
        --orm django \
        --all-databases \
        --all \
        --levels 1,5,10,25,50 \
        --duration 60 \
        --index-mode both \
        --output-dir results/full_concurrency_benchmark/
"""

import os
import sys
import csv
import argparse
import logging
import threading
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Oracle compatibility: Use oracledb as cx_Oracle replacement
try:
    import oracledb
    sys.modules['cx_Oracle'] = oracledb
except ImportError:
    pass

# Import Oracle connection manager
try:
    from scripts.oracle_connection_manager import OracleConnectionContext
except ImportError:
    # Fallback if import fails - disable Oracle connection management
    class OracleConnectionContext:
        def __init__(self, timeout=30.0):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Initialize oracledb compatibility BEFORE importing Django
try:
    import oracledb
    if not isinstance(oracledb.Binary, type):
        oracledb.Binary = bytes
    if not isinstance(getattr(oracledb, 'Timestamp', None), type):
        import datetime
        oracledb.Timestamp = datetime.datetime
    sys.modules['cx_Oracle'] = oracledb
except ImportError:
    pass

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')

try:
    import django
    django.setup()
except Exception as e:
    logger.error(f"Failed to setup Django: {e}")
    sys.exit(1)

# Database mappings
DBMS_MAPPING = {
    'default': 'PostgreSQL',
    'postgresql': 'PostgreSQL', 
    'postgres': 'PostgreSQL',
    'mysql': 'MySQL',
    'oracle': 'Oracle',
    'sqlserver': 'SQL Server'
}

# All available databases
ALL_DATABASES = ['postgresql', 'mysql', 'oracle', 'sqlserver']


def manage_indexes(database: str, action: str) -> bool:
    """Manage database indexes using the manage_indexes.py script."""
    try:
        cmd = [
            sys.executable, 
            str(project_root / 'scripts' / 'manage_indexes.py'),
            '--database', database,
            '--action', action
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        if result.returncode != 0:
            logger.error(f"Failed to {action} indexes for {database}: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"Error managing indexes for {database}: {e}")
        return False


def test_database_connection(database: str) -> bool:
    """Test if database connection is working."""
    try:
        from django.db import connections
        conn = connections[database]
        conn.ensure_connection()
        return True
    except Exception as e:
        logger.error(f"Connection test failed for {database}: {e}")
        return False


class PerQueryConcurrencyBenchmark:
    """Measure throughput for individual queries at different concurrency levels."""
    
    def __init__(self, benchmark_type: str, orm: str, databases: List[str], 
                 concurrency_levels: List[int], duration: int, index_mode: str):
        self.benchmark_type = benchmark_type.lower()
        self.orm = orm.lower()
        self.databases = databases
        self.concurrency_levels = concurrency_levels
        self.duration = duration
        self.warmup_duration = 10  # 10 seconds warmup
        self.index_mode = index_mode.lower()
        
        # Load query/transaction modules
        if self.benchmark_type == 'tpch':
            if self.orm == 'django':
                from django_app.queries import get_query_module_for_db, get_all_queries
                self.get_item_module = get_query_module_for_db
                self.all_items = get_all_queries()
            else:  # sqlalchemy
                from sqlalchemy_app.queries import get_query_module_for_db, get_all_queries
                self.get_item_module = get_query_module_for_db
                self.all_items = get_all_queries()
        else:  # tpcc
            if self.orm == 'django':
                from django_app.tpcc_queries import get_transaction_module_for_db, get_all_transactions
                self.get_item_module = get_transaction_module_for_db
                self.all_items = get_all_transactions()
            else:  # sqlalchemy
                from sqlalchemy_app.tpcc_queries import get_transaction_module_for_db, get_all_transactions
                self.get_item_module = get_transaction_module_for_db
                self.all_items = get_all_transactions()
    
    def measure_single_query_throughput(self, query_id: int, database: str, concurrency: int) -> float:
        """Measure queries per second for a specific query at given concurrency level."""
        # Limit concurrency for Oracle to prevent connection exhaustion
        if database == 'oracle' and concurrency > 20:
            logger.warning(f"    Reducing concurrency from {concurrency} to 20 for Oracle to prevent connection issues")
            concurrency = 20
            
        query_count = 0
        error_count = 0
        query_count_lock = threading.Lock()
        stop_event = threading.Event()
        
        def worker():
            nonlocal query_count, error_count
            while not stop_event.is_set():
                try:
                    # Always run the specific query
                    item_module = self.get_item_module(query_id, database)
                    if not item_module:
                        continue
                    
                    # Execute query/transaction with retry logic for connection errors
                    max_retries = 3
                    retry_delay = 0.1
                    
                    for attempt in range(max_retries):
                        try:
                            # Use connection manager for Oracle to prevent session exhaustion
                            if database == 'oracle':
                                with OracleConnectionContext(timeout=30.0):
                                    if self.orm == 'django':
                                        if self.benchmark_type == 'tpch':
                                            item_module.run_query_orm(using=database)
                                        else:  # tpcc
                                            item_module.run_transaction_orm(using=database)
                                    else:  # sqlalchemy
                                        from sqlalchemy_app.database import db_manager
                                        session = db_manager.get_session(database)
                                        try:
                                            if self.benchmark_type == 'tpch':
                                                item_module.run_query_orm(session)
                                            else:  # tpcc
                                                item_module.run_transaction_orm(session)
                                            session.commit()
                                        finally:
                                            session.close()
                            else:
                                # For non-Oracle databases, execute normally
                                if self.orm == 'django':
                                    if self.benchmark_type == 'tpch':
                                        item_module.run_query_orm(using=database)
                                    else:  # tpcc
                                        item_module.run_transaction_orm(using=database)
                                else:  # sqlalchemy
                                    from sqlalchemy_app.database import db_manager
                                    session = db_manager.get_session(database)
                                    try:
                                        if self.benchmark_type == 'tpch':
                                            item_module.run_query_orm(session)
                                        else:  # tpcc
                                            item_module.run_transaction_orm(session)
                                        session.commit()
                                    finally:
                                        session.close()
                            
                            # If we get here, the query succeeded
                            with query_count_lock:
                                query_count += 1
                            break  # Exit retry loop on success
                            
                        except Exception as retry_e:
                            # Check if it's a connection-related error
                            error_msg = str(retry_e).lower()
                            if any(keyword in error_msg for keyword in ['connection', 'listener', 'dpy-6005', 'dpy-6000', 'ora-12516']):
                                if attempt < max_retries - 1:  # Not the last attempt
                                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                                    continue
                            # If not a connection error or last attempt, re-raise
                            raise retry_e
                
                except Exception as e:
                    with query_count_lock:
                        error_count += 1
                    # Log first few errors for debugging
                    if error_count <= 5:
                        logger.error(f"    Error in worker thread: {type(e).__name__}: {e}")
                    # Continue despite errors
        
        # Start worker threads with small delay to reduce connection burst
        threads = []
        for i in range(concurrency):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)
            # Small delay between thread starts for Oracle to reduce connection burst
            if database == 'oracle' and i < concurrency - 1:
                time.sleep(0.01)
        
        # Wait for duration
        time.sleep(self.duration)
        
        # Stop workers
        stop_event.set()
        
        # Wait for threads to finish
        for t in threads:
            t.join(timeout=5)
        
        # Calculate QPS
        qps = query_count / self.duration if self.duration > 0 else 0
        if error_count > 0:
            logger.warning(f"    ⚠ {error_count} errors occurred during measurement")
        
        # Clean up database connections after measurement
        self.cleanup_database_connections(database)
        
        return qps
    
    def cleanup_database_connections(self, database: str):
        """Clean up database connections to prevent session exhaustion."""
        try:
            if self.orm == 'django':
                # Close all Django database connections for this database
                from django.db import connections
                if database in connections:
                    connections[database].close()
                    logger.debug(f"    Closed Django connection for {database}")
            else:  # sqlalchemy
                # For SQLAlchemy, dispose of the engine to close all connections
                from sqlalchemy_app.database import db_manager
                if hasattr(db_manager, '_engines') and database in db_manager._engines:
                    db_manager._engines[database].dispose()
                    logger.debug(f"    Disposed SQLAlchemy engine for {database}")
        except Exception as e:
            logger.warning(f"    Warning: Could not clean up connections for {database}: {e}")
    
    def setup_schema_configuration(self, database: str, schema_config: str) -> bool:
        """Setup database schema configuration (indexed/non-indexed)."""
        # TPC-C indexes are part of the schema definition and cannot be managed separately
        if self.benchmark_type == 'tpcc':
            logger.info(f"  Using TPC-C schema for {database} (indexes are part of schema)")
            return True
        
        # For TPC-H, manage indexes dynamically
        if schema_config == 'indexed':
            logger.info(f"  Setting up indexed schema for {database}...")
            return manage_indexes(database, 'create')
        elif schema_config == 'non-indexed':
            logger.info(f"  Setting up non-indexed schema for {database}...")
            return manage_indexes(database, 'drop')
        else:
            logger.info(f"  Using existing schema configuration for {database}")
            return True

    def run_query_benchmark(self, query_id: int, database: str, schema_config: str, output_dir: Path) -> Dict[int, float]:
        """Run concurrency benchmark for a specific query at all levels."""
        results = {}
        
        query_name = f"Q{query_id:02d}" if self.benchmark_type == 'tpch' else f"T{query_id:02d}"
        dbms_name = DBMS_MAPPING.get(database, database)
        
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {query_name} concurrency benchmark: {self.orm.upper()} on {dbms_name}")
        logger.info(f"Schema configuration: {schema_config}")
        logger.info(f"Concurrency levels: {self.concurrency_levels}")
        logger.info(f"Duration per level: {self.duration}s")
        logger.info(f"{'='*70}")
        
        # Prepare combined output file
        combined_file = output_dir / f"combined_{self.orm}_{schema_config}_concurrency.csv"
        
        # Initialize combined file with header if it doesn't exist
        if not combined_file.exists():
            with open(combined_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['query_id', 'database', 'dbms', 'schema_config', 'concurrency_level', 'throughput_qps'])
        
        for level in self.concurrency_levels:
            logger.info(f"\nTesting {query_name} at concurrency level: {level}")
            
            # Warmup
            logger.info(f"  Warmup ({self.warmup_duration}s)...")
            self.measure_single_query_throughput(query_id, database, level)
            time.sleep(2)
            
            # Measurement
            logger.info(f"  Measuring ({self.duration}s)...")
            qps = self.measure_single_query_throughput(query_id, database, level)
            results[level] = qps
            
            logger.info(f"  ✓ QPS: {qps:.2f}")
            
            # Save immediately after each level to combined file
            with open(combined_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([query_id, database, dbms_name, schema_config, level, f"{qps:.2f}"])
            
            logger.info(f"  💾 Results saved to: {combined_file.name}")
            
            # Additional cleanup after each concurrency level
            self.cleanup_database_connections(database)
            
            # Cool down
            time.sleep(5)
        
        # Final cleanup after all concurrency levels for this query
        self.cleanup_database_connections(database)
        
        return results


def main():
    parser = argparse.ArgumentParser(
        description='Run per-query concurrency/throughput benchmarks',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--benchmark', choices=['tpch', 'tpcc'], default='tpch',
                       help='Benchmark type')
    parser.add_argument('--orm', choices=['django', 'sqlalchemy'], required=True,
                       help='ORM framework')
    # Database selection (mutually exclusive)
    db_group = parser.add_mutually_exclusive_group(required=True)
    db_group.add_argument('--database', 
                         help='Single database alias (mysql, postgresql, oracle, sqlserver)')
    db_group.add_argument('--databases', 
                         help='Multiple databases (comma-separated: mysql,postgresql,oracle)')
    db_group.add_argument('--all-databases', action='store_true',
                         help='Run on all available databases')
    
    # Query/transaction selection
    parser.add_argument('--queries', help='Query numbers (comma-separated, for TPC-H)')
    parser.add_argument('--transactions', help='Transaction numbers (comma-separated, for TPC-C)')
    parser.add_argument('--all', action='store_true',
                       help='Run all queries/transactions')
    
    # Benchmark configuration
    parser.add_argument('--levels', default='1,5,10,25,50',
                       help='Concurrency levels (comma-separated)')
    parser.add_argument('--duration', type=int, default=60,
                       help='Test duration per level in seconds (default: 60)')
    parser.add_argument('--index-mode', choices=['indexed', 'non-indexed', 'both'], 
                       default='indexed',
                       help='Schema configuration: indexed, non-indexed, or both (default: indexed)')
    parser.add_argument('--output-dir', type=Path, default=Path('results/per_query'),
                       help='Output directory for per-query results (CSV files)')
    parser.add_argument('--skip-connection-test', action='store_true',
                       help='Skip database connection testing')
    
    args = parser.parse_args()
    
    # Determine databases to test
    if args.database:
        databases = [args.database]
    elif args.databases:
        databases = [db.strip() for db in args.databases.split(',')]
    elif args.all_databases:
        databases = ALL_DATABASES.copy()
    else:
        parser.error("Must specify --database, --databases, or --all-databases")
    
    # Determine items to test
    if args.all:
        if args.benchmark == 'tpch':
            items = list(range(1, 23))  # Q1-Q22
        else:  # tpcc
            items = list(range(1, 6))  # T1-T5
    elif args.queries:
        items = [int(q.strip()) for q in args.queries.split(',')]
    elif args.transactions:
        items = [int(t.strip()) for t in args.transactions.split(',')]
    else:
        parser.error("Must specify --queries, --transactions, or --all")
    
    # Parse concurrency levels
    concurrency_levels = [int(l.strip()) for l in args.levels.split(',')]
    
    # Determine schema configurations
    if args.index_mode == 'both':
        schema_configs = ['indexed', 'non-indexed']
    else:
        schema_configs = [args.index_mode]
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Test database connections
    if not args.skip_connection_test:
        logger.info("Testing database connections...")
        failed_databases = []
        for database in databases:
            if not test_database_connection(database):
                failed_databases.append(database)
        
        if failed_databases:
            logger.error(f"Failed to connect to databases: {failed_databases}")
            logger.error("Use --skip-connection-test to bypass this check")
            return 1
        
        logger.info("✓ All database connections successful")
    
    # Initialize benchmark runner
    benchmark = PerQueryConcurrencyBenchmark(
        benchmark_type=args.benchmark,
        orm=args.orm,
        databases=databases,
        concurrency_levels=concurrency_levels,
        duration=args.duration,
        index_mode=args.index_mode
    )
    
    all_results = {}
    total_combinations = len(databases) * len(schema_configs) * len(items)
    current_combination = 0
    
    logger.info(f"\n{'='*80}")
    logger.info(f"CONCURRENCY BENCHMARK PLAN")
    logger.info(f"{'='*80}")
    logger.info(f"Databases: {databases}")
    logger.info(f"Schema configurations: {schema_configs}")
    logger.info(f"Items: {len(items)} {'queries' if args.benchmark == 'tpch' else 'transactions'}")
    logger.info(f"Concurrency levels: {concurrency_levels}")
    logger.info(f"Duration per level: {args.duration}s")
    logger.info(f"Total combinations: {total_combinations}")
    logger.info(f"Estimated time: {total_combinations * len(concurrency_levels) * (args.duration + 15) / 3600:.1f} hours")
    logger.info(f"{'='*80}")
    
    # Run benchmarks for each combination
    for database in databases:
        dbms_name = DBMS_MAPPING.get(database, database)
        logger.info(f"\n🗄️  Starting benchmarks for {dbms_name} ({database})")
        
        for schema_config in schema_configs:
            logger.info(f"\n📊 Schema configuration: {schema_config}")
            
            # Setup schema configuration
            if not benchmark.setup_schema_configuration(database, schema_config):
                logger.error(f"Failed to setup {schema_config} schema for {database}, skipping...")
                continue
            
            for item_id in items:
                current_combination += 1
                item_name = f"Q{item_id:02d}" if args.benchmark == 'tpch' else f"T{item_id:02d}"
                
                logger.info(f"\n[{current_combination}/{total_combinations}] Measuring {item_name} throughput...")
                
                # Run benchmark for this specific query/database/schema combination
                try:
                    throughput_results = benchmark.run_query_benchmark(
                        item_id, database, schema_config, args.output_dir
                    )
                    all_results[(database, schema_config, item_id)] = throughput_results
                    
                    logger.info(f"✓ {item_name} on {dbms_name} ({schema_config}) completed")
                    
                except Exception as e:
                    logger.error(f"✗ {item_name} on {dbms_name} ({schema_config}) failed: {e}")
                    continue
    
    # Log completion
    logger.info(f"\n{'='*80}")
    logger.info(f"CONCURRENCY BENCHMARK COMPLETE!")
    logger.info(f"{'='*80}")
    logger.info(f"Results saved in: {args.output_dir}")
    logger.info(f"Combined files: combined_{args.orm}_*_concurrency.csv")
    
    return 0
    
    # Print summary
    logger.info("\n" + "="*80)
    logger.info("Per-Query Throughput Results Summary")
    logger.info("="*80)
    
    for (database, schema_config, item_id), results in sorted(all_results.items()):
        item_name = f"Q{item_id:02d}" if args.benchmark == 'tpch' else f"T{item_id:02d}"
        dbms_name = DBMS_MAPPING.get(database, database)
        logger.info(f"\n{item_name} on {dbms_name} ({schema_config}):")
        for level, qps in sorted(results.items()):
            logger.info(f"  {level:3d} concurrent users: {qps:8.2f} QPS")


if __name__ == '__main__':
    main()
