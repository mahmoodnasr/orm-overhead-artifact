#!/usr/bin/env python3
"""
Validate benchmark results and data integrity.

Checks:
1. Row counts match expected values
2. Query results are consistent across databases
3. Data integrity checks
"""

import os
import sys
import django
import argparse
import logging

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')
django.setup()

from django_app.utils.database import DatabaseManager
from django_app.queries import get_query_module

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class ResultValidator:
    """Validate benchmark results."""
    
    def __init__(self, databases=None):
        self.db_manager = DatabaseManager()
        # Use dynamically loaded databases from settings if not specified
        self.databases = databases or self.db_manager.databases
    
    def check_data_integrity(self, scale_factor=100):
        """Check row counts for all databases."""
        logger.info("Checking data integrity...")
        
        all_valid = True
        for db in self.databases:
            logger.info(f"\nDatabase: {db}")
            try:
                results = self.db_manager.verify_data_integrity(db, scale_factor)
                
                if results['all_valid']:
                    logger.info("  ✓ All row counts valid")
                else:
                    logger.error("  ✗ Row count mismatches detected")
                    all_valid = False
                
                for table, info in results['tables'].items():
                    if info['valid']:
                        logger.info(f"    {table}: {info['actual']:,} rows ✓")
                    else:
                        logger.error(f"    {table}: {info['actual']:,} rows (expected {info['expected']:,}) ✗")
            
            except Exception as e:
                logger.error(f"  Error checking {db}: {e}")
                all_valid = False
        
        return all_valid
    
    def compare_query_results(self, query_num):
        """Compare query results across all databases."""
        logger.info(f"\nComparing Q{query_num} results across databases...")
        
        query_module = get_query_module(query_num)
        if not query_module:
            logger.error(f"Query {query_num} not found")
            return False
        
        results = {}
        for db in self.databases:
            try:
                logger.info(f"  Running on {db}...")
                results[db] = query_module.run_query_orm(using=db)
                logger.info(f"    Got {len(results[db])} rows")
            except Exception as e:
                logger.error(f"    Error: {e}")
                return False
        
        # Compare row counts
        row_counts = {db: len(r) for db, r in results.items()}
        if len(set(row_counts.values())) > 1:
            logger.error(f"  ✗ Row count mismatch: {row_counts}")
            return False
        
        logger.info(f"  ✓ All databases returned {list(row_counts.values())[0]} rows")
        return True


def main():
    parser = argparse.ArgumentParser(description='Validate benchmark results')
    parser.add_argument('--check-data-integrity', action='store_true',
                        help='Check row counts match expected values')
    parser.add_argument('--compare-results', type=int, metavar='QUERY_NUM',
                        help='Compare query results across databases')
    parser.add_argument('--scale-factor', type=int, default=100,
                        help='TPC-H scale factor (default: 100)')
    parser.add_argument('--databases', type=str,
                        help='Comma-separated list of databases to check')
    
    args = parser.parse_args()
    
    databases = None
    if args.databases:
        databases = [db.strip() for db in args.databases.split(',')]
    
    validator = ResultValidator(databases=databases)
    
    if args.check_data_integrity:
        valid = validator.check_data_integrity(args.scale_factor)
        sys.exit(0 if valid else 1)
    
    elif args.compare_results:
        valid = validator.compare_query_results(args.compare_results)
        sys.exit(0 if valid else 1)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
