#!/usr/bin/env python3
"""
Run concurrency tests to measure throughput under load.

Tests different concurrency levels (1-200 users) and measures
queries per second (QPS).
"""

import os
import sys
import django
import argparse
import threading
import time
import random
from queue import Queue
from datetime import datetime

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')
django.setup()

from django_app.queries import get_query_module, get_all_queries


class ConcurrencyTester:
    """Test query throughput under various concurrency levels."""
    
    def __init__(self, database, concurrency_levels, duration=300):
        """
        Initialize concurrency tester.
        
        Args:
            database: Database alias to test
            concurrency_levels: List of concurrency levels (e.g., [1, 10, 25, 50, 100])
            duration: Test duration in seconds (default 300 = 5 minutes)
        """
        self.database = database
        self.concurrency_levels = concurrency_levels
        self.duration = duration
        self.warmup_duration = 60  # 1 minute warmup
        self.queries = get_all_queries()
    
    def run_test(self):
        """Run concurrency test at each level."""
        print("="*60)
        print(f"Concurrency Test - Database: {self.database}")
        print("="*60)
        
        results = {}
        
        for level in self.concurrency_levels:
            print(f"\n{'='*60}")
            print(f"Testing concurrency level: {level} users")
            print(f"{'='*60}")
            
            # Warmup
            print(f"Warmup ({self.warmup_duration}s)...")
            self.warmup(level)
            
            # Measurement
            print(f"Measuring ({self.duration}s)...")
            qps = self.measure_throughput(level, self.duration)
            results[level] = qps
            
            print(f"✓ QPS: {qps:.2f}")
            
            # Cool down
            print("Cooling down (10s)...")
            time.sleep(10)
        
        print("\n" + "="*60)
        print("Concurrency Test Results")
        print("="*60)
        for level, qps in results.items():
            print(f"  {level:3d} users: {qps:8.2f} QPS")
        
        return results
    
    def warmup(self, concurrency):
        """Warmup run."""
        self.measure_throughput(concurrency, self.warmup_duration)
    
    def measure_throughput(self, concurrency, duration):
        """Measure queries per second with N concurrent workers."""
        query_count = 0
        query_count_lock = threading.Lock()
        stop_event = threading.Event()
        
        def worker():
            nonlocal query_count
            while not stop_event.is_set():
                try:
                    # Select random query
                    query_num = random.choice(self.queries)
                    query_module = get_query_module(query_num)
                    
                    if query_module:
                        # Execute query
                        results = query_module.run_query_orm(using=self.database)
                        
                        # Increment count
                        with query_count_lock:
                            query_count += 1
                
                except Exception as e:
                    # Ignore errors during load test
                    pass
        
        # Start worker threads
        threads = []
        for _ in range(concurrency):
            t = threading.Thread(target=worker)
            t.daemon = True
            t.start()
            threads.append(t)
        
        # Wait for duration
        time.sleep(duration)
        
        # Stop workers
        stop_event.set()
        
        # Wait for threads to finish
        for t in threads:
            t.join(timeout=5)
        
        # Calculate QPS
        qps = query_count / duration
        return qps


def main():
    parser = argparse.ArgumentParser(description='Run concurrency tests')
    parser.add_argument('--database', '--db', type=str, default='default',
                        help='Database to test (default: default)')
    parser.add_argument('--levels', type=str, default='1,10,25,50,100',
                        help='Comma-separated concurrency levels')
    parser.add_argument('--duration', type=int, default=300,
                        help='Test duration per level in seconds (default: 300)')
    parser.add_argument('--output', '-o', type=str,
                        help='Output file for results (CSV)')
    
    args = parser.parse_args()
    
    # Parse concurrency levels
    levels = [int(l.strip()) for l in args.levels.split(',')]
    
    # Run test
    tester = ConcurrencyTester(
        database=args.database,
        concurrency_levels=levels,
        duration=args.duration
    )
    
    results = tester.run_test()
    
    # Save results
    if args.output:
        import csv
        with open(args.output, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['concurrency_level', 'qps'])
            for level, qps in results.items():
                writer.writerow([level, qps])
        print(f"\n✓ Results saved to: {args.output}")


if __name__ == '__main__':
    main()
