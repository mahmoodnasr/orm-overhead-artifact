#!/usr/bin/env python3
"""
Execution Plan Collection Orchestrator

Collects query execution plans from all database systems for MOEF analysis.

Paper Reference: Section 3.5.2 - "Phase 2: Plan Collection"

This script:
1. Connects to each DBMS (PostgreSQL, MySQL, Oracle, SQL Server)
2. Executes queries with EXPLAIN ANALYZE to get runtime statistics
3. Collects execution plans in native format
4. Parses plans into standardized format
5. Saves plans as JSON for analysis

Usage:
    # Collect plans for all queries
    python collect_execution_plans.py --database all --orm all --queries all

    # Collect specific query
    python collect_execution_plans.py --database postgresql --orm django --queries 8

    # Collect with actual execution (includes runtime stats)
    python collect_execution_plans.py --database postgresql --with-execution
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Setup Django before imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')

try:
    import django
    django.setup()
except Exception as e:
    logging.warning(f"Django setup failed: {e}")

# Import parsers
from parsers.postgres_parser import parse_postgres_plan
# from parsers.mysql_parser import parse_mysql_plan
# from parsers.oracle_parser import parse_oracle_plan
# from parsers.sqlserver_parser import parse_sqlserver_plan

from utils.qerror import calculate_qerror

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ExecutionPlanCollector:
    """
    Orchestrates execution plan collection across multiple databases.

    Handles database-specific EXPLAIN syntax and plan format differences.
    """

    def __init__(self, output_dir: Path):
        """
        Initialize plan collector.

        Args:
            output_dir: Directory to save collected plans
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Track statistics
        self.stats = {
            'plans_collected': 0,
            'plans_failed': 0,
            'databases_processed': set(),
            'queries_processed': set()
        }

    def collect_postgresql_plan(
        self,
        query_sql: str,
        query_id: str,
        orm: str,
        schema: str,
        with_execution: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Collect execution plan from PostgreSQL.

        Uses: EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)

        Args:
            query_sql: SQL query to explain
            query_id: Query identifier (e.g., "Q8")
            orm: ORM framework ("django", "sqlalchemy", "raw")
            schema: Schema type ("indexed", "nonindexed")
            with_execution: Include ANALYZE (actual execution)

        Returns:
            Parsed execution plan or None if failed
        """
        from django.db import connections

        try:
            connection = connections['default']  # PostgreSQL

            # Build EXPLAIN command
            if with_execution:
                explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query_sql}"
            else:
                explain_sql = f"EXPLAIN (FORMAT JSON) {query_sql}"

            # Execute EXPLAIN
            with connection.cursor() as cursor:
                cursor.execute(explain_sql)
                result = cursor.fetchone()

                if result:
                    plan_json = result[0]

                    # Parse plan
                    parsed_plan = parse_postgres_plan(plan_json)

                    # Add metadata
                    parsed_plan['metadata']['query_id'] = query_id
                    parsed_plan['metadata']['orm'] = orm
                    parsed_plan['metadata']['schema'] = schema
                    parsed_plan['metadata']['database'] = 'postgresql'
                    parsed_plan['metadata']['collection_timestamp'] = datetime.now().isoformat()

                    # Save plan
                    self._save_plan(parsed_plan, 'postgresql', orm, schema, query_id)

                    self.stats['plans_collected'] += 1
                    self.stats['databases_processed'].add('postgresql')
                    self.stats['queries_processed'].add(query_id)

                    logger.info(f"✓ Collected PostgreSQL plan: {query_id} ({orm}, {schema})")
                    return parsed_plan

        except Exception as e:
            logger.error(f"✗ Failed to collect PostgreSQL plan for {query_id}: {e}")
            self.stats['plans_failed'] += 1
            return None

    def collect_mysql_plan(
        self,
        query_sql: str,
        query_id: str,
        orm: str,
        schema: str,
        with_execution: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Collect execution plan from MySQL.

        Uses: EXPLAIN ANALYZE (MySQL 8.0.18+)
        or EXPLAIN FORMAT=JSON for older versions

        Note: MySQL's EXPLAIN ANALYZE has limited statistics compared to PostgreSQL
        """
        from django.db import connections

        try:
            connection = connections['mysql']

            # Try EXPLAIN ANALYZE first (MySQL 8.0.18+)
            if with_execution:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(f"EXPLAIN ANALYZE {query_sql}")
                        result = cursor.fetchall()

                        # EXPLAIN ANALYZE returns text format
                        # For now, save raw output
                        plan_data = {
                            'type': 'MySQL EXPLAIN ANALYZE',
                            'raw_output': [row[0] for row in result],
                            'metadata': {
                                'query_id': query_id,
                                'orm': orm,
                                'schema': schema,
                                'database': 'mysql',
                                'collection_timestamp': datetime.now().isoformat()
                            }
                        }

                        self._save_plan(plan_data, 'mysql', orm, schema, query_id)
                        self.stats['plans_collected'] += 1
                        logger.info(f"✓ Collected MySQL plan: {query_id} ({orm}, {schema})")
                        return plan_data

                except Exception as e:
                    logger.warning(f"EXPLAIN ANALYZE failed, trying EXPLAIN FORMAT=JSON: {e}")

            # Fallback to EXPLAIN FORMAT=JSON
            with connection.cursor() as cursor:
                cursor.execute(f"EXPLAIN FORMAT=JSON {query_sql}")
                result = cursor.fetchone()

                if result:
                    plan_json = json.loads(result[0])

                    # Add metadata
                    plan_json['metadata'] = {
                        'query_id': query_id,
                        'orm': orm,
                        'schema': schema,
                        'database': 'mysql',
                        'collection_timestamp': datetime.now().isoformat()
                    }

                    self._save_plan(plan_json, 'mysql', orm, schema, query_id)
                    self.stats['plans_collected'] += 1
                    logger.info(f"✓ Collected MySQL plan: {query_id} ({orm}, {schema})")
                    return plan_json

        except Exception as e:
            logger.error(f"✗ Failed to collect MySQL plan for {query_id}: {e}")
            self.stats['plans_failed'] += 1
            return None

    def _save_plan(
        self,
        plan: Dict[str, Any],
        database: str,
        orm: str,
        schema: str,
        query_id: str
    ):
        """
        Save execution plan to JSON file.

        Directory structure:
        results/execution_plans/{database}/{schema}/{orm}/{query_id}_plan.json
        """
        plan_dir = self.output_dir / database / schema / orm
        plan_dir.mkdir(parents=True, exist_ok=True)

        plan_file = plan_dir / f"{query_id}_plan.json"

        with open(plan_file, 'w') as f:
            json.dump(plan, f, indent=2, default=str)

        logger.debug(f"Saved plan to {plan_file}")

    def collect_for_query(
        self,
        query_sql: str,
        query_id: str,
        database: str,
        orm: str,
        schema: str,
        with_execution: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Collect execution plan for a specific query.

        Routes to appropriate database-specific collector.
        """
        if database == 'postgresql' or database == 'default':
            return self.collect_postgresql_plan(
                query_sql, query_id, orm, schema, with_execution
            )
        elif database == 'mysql':
            return self.collect_mysql_plan(
                query_sql, query_id, orm, schema, with_execution
            )
        elif database == 'oracle':
            logger.warning("Oracle plan collection not yet implemented")
            return None
        elif database == 'sqlserver':
            logger.warning("SQL Server plan collection not yet implemented")
            return None
        else:
            logger.error(f"Unknown database: {database}")
            return None

    def print_summary(self):
        """Print collection summary statistics."""
        print("\n" + "=" * 70)
        print("EXECUTION PLAN COLLECTION SUMMARY")
        print("=" * 70)
        print(f"Plans collected: {self.stats['plans_collected']}")
        print(f"Plans failed: {self.stats['plans_failed']}")
        print(f"Databases processed: {', '.join(sorted(self.stats['databases_processed']))}")
        print(f"Unique queries: {len(self.stats['queries_processed'])}")
        print(f"Output directory: {self.output_dir}")
        print("=" * 70 + "\n")


def get_tpch_query_sql(query_num: int, orm: str = 'raw') -> Tuple[str, str]:
    """
    Get TPC-H query SQL for a specific query number and ORM.

    Args:
        query_num: TPC-H query number (1-22)
        orm: ORM framework ('django', 'sqlalchemy', 'raw')

    Returns:
        Tuple of (query_sql, query_id)
    """
    query_id = f"Q{query_num}"

    if orm == 'django':
        # Import Django query implementation
        try:
            from django_app.queries.tpch.base import get_query_function
            query_func = get_query_function(query_num)
            # Execute query and get SQL
            # This is a simplified version - actual implementation would need
            # to extract SQL from QuerySet
            query_sql = f"-- Django ORM query {query_num}\n-- TODO: Extract actual SQL"
        except Exception as e:
            logger.warning(f"Failed to get Django query {query_num}: {e}")
            query_sql = None

    elif orm == 'sqlalchemy':
        # Import SQLAlchemy query implementation
        try:
            from sqlalchemy_app.queries.tpch.base import get_query_function
            query_func = get_query_function(query_num)
            # Get SQL from SQLAlchemy query
            query_sql = f"-- SQLAlchemy query {query_num}\n-- TODO: Extract actual SQL"
        except Exception as e:
            logger.warning(f"Failed to get SQLAlchemy query {query_num}: {e}")
            query_sql = None

    else:  # raw SQL
        # Load raw SQL from file
        sql_file = project_root / 'data' / 'tpch_queries' / f'q{query_num}.sql'
        if sql_file.exists():
            query_sql = sql_file.read_text()
        else:
            logger.warning(f"SQL file not found: {sql_file}")
            query_sql = None

    return query_sql, query_id


def main():
    parser = argparse.ArgumentParser(
        description='Collect execution plans for MOEF analysis'
    )
    parser.add_argument(
        '--database',
        choices=['postgresql', 'mysql', 'oracle', 'sqlserver', 'all'],
        default='postgresql',
        help='Database system to collect from'
    )
    parser.add_argument(
        '--orm',
        choices=['django', 'sqlalchemy', 'raw', 'all'],
        default='all',
        help='ORM framework'
    )
    parser.add_argument(
        '--schema',
        choices=['indexed', 'nonindexed', 'both'],
        default='indexed',
        help='Schema configuration'
    )
    parser.add_argument(
        '--queries',
        default='8,9',
        help='Comma-separated query numbers (e.g., "8,9") or "all" for all 22'
    )
    parser.add_argument(
        '--with-execution',
        action='store_true',
        default=True,
        help='Include ANALYZE (actual execution)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('results/execution_plans'),
        help='Output directory for plans'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize collector
    collector = ExecutionPlanCollector(args.output_dir)

    # Parse query list
    if args.queries.lower() == 'all':
        query_numbers = list(range(1, 23))  # TPC-H Q1-Q22
    else:
        query_numbers = [int(q.strip()) for q in args.queries.split(',')]

    # Parse ORM list
    if args.orm == 'all':
        orms = ['django', 'sqlalchemy', 'raw']
    else:
        orms = [args.orm]

    # Parse schema list
    if args.schema == 'both':
        schemas = ['indexed', 'nonindexed']
    else:
        schemas = [args.schema]

    # Parse database list
    if args.database == 'all':
        databases = ['postgresql', 'mysql', 'oracle', 'sqlserver']
    else:
        databases = [args.database]

    # Collect plans
    logger.info(f"Collecting plans for {len(query_numbers)} queries, "
                f"{len(orms)} ORMs, {len(schemas)} schemas, {len(databases)} databases")

    total_configs = len(query_numbers) * len(orms) * len(schemas) * len(databases)
    logger.info(f"Total configurations: {total_configs}")

    for database in databases:
        for schema in schemas:
            for orm in orms:
                for query_num in query_numbers:
                    # Get query SQL
                    query_sql, query_id = get_tpch_query_sql(query_num, orm)

                    if not query_sql:
                        logger.warning(f"Skipping {query_id} ({orm}) - no SQL available")
                        continue

                    # Collect plan
                    collector.collect_for_query(
                        query_sql=query_sql,
                        query_id=query_id,
                        database=database,
                        orm=orm,
                        schema=schema,
                        with_execution=args.with_execution
                    )

    # Print summary
    collector.print_summary()

    # Calculate success rate
    if total_configs > 0:
        success_rate = (collector.stats['plans_collected'] / total_configs) * 100
        logger.info(f"Success rate: {success_rate:.1f}%")


if __name__ == '__main__':
    main()
