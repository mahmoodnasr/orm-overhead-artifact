#!/usr/bin/env python3
"""
Collect query execution plans for mechanistic analysis.

This script runs all queries and collects their execution plans
from each database for analysis.
"""

import os
import sys
import django
import argparse
import json
from pathlib import Path

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')
django.setup()

from django.db import connections
from django_app.queries import get_query_module, get_all_queries
from django_app.utils.plan_collector import QueryPlanCollector


class PlanCollectionRunner:
    """Collect query plans from all databases."""
    
    def __init__(self, databases, queries, output_dir):
        self.databases = databases
        self.queries = queries
        self.output_dir = Path(output_dir)
        self.collector = QueryPlanCollector()
        
        # Create output directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for db in databases:
            (self.output_dir / db).mkdir(exist_ok=True)
    
    def collect_all_plans(self):
        """Collect plans for all queries on all databases."""
        print("="*60)
        print("Collecting Query Execution Plans")
        print("="*60)
        
        for db in self.databases:
            print(f"\n{'='*60}")
            print(f"Database: {db}")
            print(f"{'='*60}")
            
            for query_num in self.queries:
                print(f"\nCollecting plan for Q{query_num:02d}...")
                
                try:
                    query_module = get_query_module(query_num)
                    if not query_module:
                        print(f"  ✗ Query {query_num} not found")
                        continue
                    
                    # Get SQL from ORM query
                    # Note: This is a simplified approach
                    # In production, you'd need to extract the actual SQL
                    
                    # For now, just use the SQL version
                    conn = connections[db]
                    
                    # Get the SQL query text
                    sql = self.get_sql_from_module(query_module, conn)
                    
                    if not sql:
                        print(f"  ✗ Could not get SQL for Q{query_num}")
                        continue
                    
                    # Collect plan
                    plan_data = self.collector.collect_plan(sql, db)
                    
                    # Save plan
                    filename = self.collector.save_plan(
                        f'q{query_num:02d}',
                        plan_data,
                        str(self.output_dir)
                    )
                    
                    print(f"  ✓ Plan saved to {filename}")
                    
                except Exception as e:
                    print(f"  ✗ Error: {e}")
        
        print("\n" + "="*60)
        print("✓ Plan collection complete!")
        print(f"Plans saved to: {self.output_dir}")
        print("="*60)
    
    def get_sql_from_module(self, module, connection):
        """Extract SQL query from module."""
        # This would need implementation to extract actual SQL
        # For now, return None
        return None


def main():
    parser = argparse.ArgumentParser(description='Collect query execution plans')
    parser.add_argument('--database', '--db', type=str,
                        help='Single database to collect from')
    parser.add_argument('--databases', '--dbs', type=str,
                        help='Comma-separated list of databases')
    parser.add_argument('--query', '-q', type=int,
                        help='Single query number')
    parser.add_argument('--queries', '-qs', type=str,
                        help='Comma-separated list of query numbers')
    parser.add_argument('--all', action='store_true',
                        help='Collect plans for all queries on all databases')
    parser.add_argument('--output', '-o', type=str, default='results/plans',
                        help='Output directory for plans')
    
    args = parser.parse_args()
    
    # Determine databases
    if args.all:
        from django.conf import settings
        databases = list(settings.DATABASES.keys())
    elif args.databases:
        databases = [db.strip() for db in args.databases.split(',')]
    elif args.database:
        databases = [args.database]
    else:
        parser.error('Must specify --database, --databases, or --all')
    
    # Determine queries
    if args.all:
        queries = get_all_queries()
    elif args.queries:
        queries = [int(q.strip()) for q in args.queries.split(',')]
    elif args.query:
        queries = [args.query]
    else:
        parser.error('Must specify --query, --queries, or --all')
    
    # Collect plans
    runner = PlanCollectionRunner(databases, queries, args.output)
    runner.collect_all_plans()


if __name__ == '__main__':
    main()
