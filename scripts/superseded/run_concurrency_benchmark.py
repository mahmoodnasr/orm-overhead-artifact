#!/usr/bin/env python3
"""
Run concurrency/throughput benchmarks and merge results with main benchmark data.

This script measures throughput (QPS) at different concurrency levels and
updates the main benchmark results CSV with throughput data.

Usage:
    python scripts/run_concurrency_benchmark.py \
        --benchmark tpch \
        --orm django \
        --database postgresql \
        --queries 1,3,6 \
        --levels 1,5,10,25,50 \
        --duration 60 \
        --results-file results/raw/indexed_results.csv
"""

import os
import sys
import csv
import argparse
import logging
import threading
import time
import random
from pathlib import Path
from typing import Dict, List, Optional

# Oracle compatibility: Use oracledb as cx_Oracle replacement
try:
    import oracledb
    sys.modules['cx_Oracle'] = oracledb
except ImportError:
    pass
from collections import defaultdict

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


class ConcurrencyBenchmark:
    """Measure throughput at different concurrency levels."""
    
    def __init__(self, benchmark_type: str, orm: str, database: str, 
                 items: List[int], concurrency_levels: List[int], duration: int):
        self.benchmark_type = benchmark_type.lower()
        self.orm = orm.lower()
        self.database = database
        self.items = items
        self.concurrency_levels = concurrency_levels
        self.duration = duration
        self.warmup_duration = 10  # 10 seconds warmup
        
        # Load query/transaction modules
        if self.benchmark_type == 'tpch':
            if self.orm == 'django':
                from django_app.queries import get_query_module_for_db, get_all_queries
                self.get_item_module = lambda n: get_query_module_for_db(n, database)
                self.all_items = get_all_queries()
            else:  # sqlalchemy
                from sqlalchemy_app.queries import get_query_module_for_db, get_all_queries
                self.get_item_module = lambda n: get_query_module_for_db(n, database)
                self.all_items = get_all_queries()
        else:  # tpcc
            if self.orm == 'django':
                from django_app.tpcc_queries import get_transaction_module_for_db, get_all_transactions
                self.get_item_module = lambda n: get_transaction_module_for_db(n, database)
                self.all_items = get_all_transactions()
            else:  # sqlalchemy
                from sqlalchemy_app.tpcc_queries import get_transaction_module_for_db, get_all_transactions
                self.get_item_module = lambda n: get_transaction_module_for_db(n, database)
                self.all_items = get_all_transactions()
    
    def measure_throughput(self, concurrency: int, item_num: Optional[int] = None) -> float:
        """Measure queries per second at given concurrency level."""
        # Limit concurrency for Oracle to prevent connection exhaustion
        if self.database == 'oracle' and concurrency > 20:
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
                    # Select query/transaction to run
                    if item_num:
                        item_to_run = item_num
                    else:
                        item_to_run = random.choice(self.items if self.items else self.all_items)
                    
                    item_module = self.get_item_module(item_to_run)
                    if not item_module:
                        continue
                    
                    # Execute query/transaction with retry logic for connection errors
                    max_retries = 3
                    retry_delay = 0.1
                    
                    for attempt in range(max_retries):
                        try:
                            if self.orm == 'django':
                                if self.benchmark_type == 'tpch':
                                    item_module.run_query_orm(using=self.database)
                                else:  # tpcc
                                    item_module.run_transaction_orm(using=self.database)
                            else:  # sqlalchemy
                                from sqlalchemy_app.database import db_manager
                                session = db_manager.get_session(self.database)
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
                    # Continue despite errors
        
        # Start worker threads with small delay to reduce connection burst
        threads = []
        for i in range(concurrency):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)
            # Small delay between thread starts for Oracle to reduce connection burst
            if self.database == 'oracle' and i < concurrency - 1:
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
        
        # Clean up database connections after measurement
        self.cleanup_database_connections()
        
        return qps
    
    def cleanup_database_connections(self):
        """Clean up database connections to prevent session exhaustion."""
        try:
            if self.orm == 'django':
                # Close all Django database connections for this database
                from django.db import connections
                if self.database in connections:
                    connections[self.database].close()
                    logger.debug(f"    Closed Django connection for {self.database}")
            else:  # sqlalchemy
                # For SQLAlchemy, dispose of the engine to close all connections
                from sqlalchemy_app.database import db_manager
                if hasattr(db_manager, '_engines') and self.database in db_manager._engines:
                    db_manager._engines[self.database].dispose()
                    logger.debug(f"    Disposed SQLAlchemy engine for {self.database}")
        except Exception as e:
            logger.warning(f"    Warning: Could not clean up connections for {self.database}: {e}")
    
    def run_benchmark(self) -> Dict[int, float]:
        """Run concurrency benchmark at all levels."""
        results = {}
        
        logger.info(f"Running concurrency benchmark: {self.orm.upper()} on {self.database}")
        logger.info(f"Concurrency levels: {self.concurrency_levels}")
        logger.info(f"Duration per level: {self.duration}s")
        
        for level in self.concurrency_levels:
            logger.info(f"\nTesting concurrency level: {level}")
            
            # Warmup
            logger.info(f"  Warmup ({self.warmup_duration}s)...")
            self.measure_throughput(level)
            time.sleep(2)
            
            # Measurement
            logger.info(f"  Measuring ({self.duration}s)...")
            qps = self.measure_throughput(level)
            results[level] = qps
            
            logger.info(f"  ✓ QPS: {qps:.2f}")
            
            # Additional cleanup after each concurrency level
            self.cleanup_database_connections()
            
            # Cool down
            time.sleep(5)
        
        # Final cleanup after all concurrency levels
        self.cleanup_database_connections()
        
        return results


def merge_throughput_results(results_file: Path, throughput_data: Dict[str, Dict[int, float]]):
    """
    Merge throughput data into existing results CSV.
    
    Args:
        results_file: Path to CSV file with benchmark results
        throughput_data: Dict mapping (orm, query_id, dbms) -> {concurrency_level: qps}
    """
    if not results_file.exists():
        logger.warning(f"Results file not found: {results_file}")
        return
    
    # Read existing results
    rows = []
    with open(results_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    # Update rows with throughput data
    updated_count = 0
    for row in rows:
        key = (row.get('orm', ''), row.get('query_id', ''), row.get('dbms', ''))
        if key in throughput_data:
            # Find best throughput (highest QPS) or use concurrency_level=1
            throughputs = throughput_data[key]
            if 1 in throughputs:
                row['concurrency_level'] = '1'
                row['throughput_qps'] = f"{throughputs[1]:.2f}"
            elif throughputs:
                # Use highest QPS
                best_level = max(throughputs.items(), key=lambda x: x[1])
                row['concurrency_level'] = str(best_level[0])
                row['throughput_qps'] = f"{best_level[1]:.2f}"
            updated_count += 1
    
    # Write updated results
    with open(results_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    logger.info(f"Updated {updated_count} rows with throughput data in {results_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Run concurrency/throughput benchmarks',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--benchmark', choices=['tpch', 'tpcc'], default='tpch',
                       help='Benchmark type')
    parser.add_argument('--orm', choices=['django', 'sqlalchemy'], required=True,
                       help='ORM framework')
    parser.add_argument('--database', required=True,
                       help='Database alias')
    parser.add_argument('--queries', help='Query numbers (comma-separated, for TPC-H)')
    parser.add_argument('--transactions', help='Transaction numbers (comma-separated, for TPC-C)')
    parser.add_argument('--all', action='store_true',
                       help='Run all queries/transactions')
    parser.add_argument('--levels', default='1,5,10,25,50',
                       help='Concurrency levels (comma-separated)')
    parser.add_argument('--duration', type=int, default=60,
                       help='Test duration per level in seconds (default: 60)')
    parser.add_argument('--results-file', type=Path,
                       help='Path to results CSV to update with throughput data')
    parser.add_argument('--output', type=Path,
                       help='Output file for throughput results (CSV)')
    
    args = parser.parse_args()
    
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
    
    # Run benchmark
    benchmark = ConcurrencyBenchmark(
        benchmark_type=args.benchmark,
        orm=args.orm,
        database=args.database,
        items=items,
        concurrency_levels=concurrency_levels,
        duration=args.duration
    )
    
    # For now, measure overall throughput (not per-query)
    # In future, could measure per-query throughput
    logger.info("Measuring overall throughput (all queries mixed)...")
    throughput_results = benchmark.run_benchmark()
    
    # Save results
    if args.output:
        with open(args.output, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['concurrency_level', 'throughput_qps'])
            for level, qps in sorted(throughput_results.items()):
                writer.writerow([level, f"{qps:.2f}"])
        logger.info(f"✓ Throughput results saved to: {args.output}")
    
    # Print summary
    logger.info("\n" + "="*60)
    logger.info("Throughput Results Summary")
    logger.info("="*60)
    for level, qps in sorted(throughput_results.items()):
        logger.info(f"  {level:3d} concurrent users: {qps:8.2f} QPS")
    
    # Note: To merge with main results, you would need to run this for each query
    # and then merge the results. For now, this provides overall throughput metrics.


if __name__ == '__main__':
    main()

