"""
Database management utilities for benchmark orchestration.
Handles connection management, data integrity verification, and database operations.
"""

from django.db import connections, connection
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manage database connections and operations for benchmark."""
    
    # Expected row counts for TPC-H SF=100
    EXPECTED_ROW_COUNTS_SF100 = {
        'lineitem': 600_037_902,
        'orders': 150_000_000,
        'partsupp': 80_000_000,
        'part': 20_000_000,
        'customer': 15_000_000,
        'supplier': 1_000_000,
        'nation': 25,
        'region': 5,
    }
    
    def __init__(self):
        """Initialize DatabaseManager with available database aliases from settings."""
        from django.conf import settings
        self.databases = list(settings.DATABASES.keys())
    
    def close_connection(self, database='default'):
        """Close database connection to clear caches."""
        try:
            connections[database].close()
            logger.info(f"Closed connection to {database}")
        except Exception as e:
            logger.error(f"Error closing connection to {database}: {e}")
    
    def close_all_connections(self):
        """Close all database connections."""
        for db in self.databases:
            try:
                self.close_connection(db)
            except Exception as e:
                logger.warning(f"Could not close connection to {db}: {e}")
    
    def restart_connection(self, database='default'):
        """Close and reopen connection to clear caches."""
        self.close_connection(database)
        # Connection will be reopened on next query
        logger.info(f"Restarted connection to {database}")
    
    def get_connection_info(self, database='default'):
        """Get database version and configuration info."""
        conn = connections[database]
        info = {
            'database': database,
            'vendor': conn.vendor,
            'settings': conn.settings_dict.copy()
        }
        
        # Remove sensitive information
        if 'PASSWORD' in info['settings']:
            info['settings']['PASSWORD'] = '***'
        
        # Get version
        try:
            with conn.cursor() as cursor:
                if conn.vendor == 'postgresql':
                    cursor.execute("SELECT version();")
                    info['version'] = cursor.fetchone()[0]
                elif conn.vendor == 'mysql':
                    cursor.execute("SELECT VERSION();")
                    info['version'] = cursor.fetchone()[0]
                elif conn.vendor == 'oracle':
                    cursor.execute("SELECT banner FROM v$version WHERE rownum = 1")
                    info['version'] = cursor.fetchone()[0]
                elif conn.vendor == 'microsoft':
                    cursor.execute("SELECT @@VERSION;")
                    info['version'] = cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Could not get version for {database}: {e}")
            info['version'] = 'Unknown'
        
        return info
    
    def get_table_row_count(self, table_name, database='default'):
        """Get row count for a specific table."""
        try:
            with connections[database].cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                return count
        except Exception as e:
            logger.error(f"Error getting row count for {table_name} on {database}: {e}")
            return None
    
    def verify_data_integrity(self, database='default', scale_factor=100, tolerance=0.01):
        """
        Check row counts match expected values for given scale factor.
        
        Args:
            database: Database alias
            scale_factor: TPC-H scale factor (default 100)
            tolerance: Acceptable percentage deviation (default 1%)
        
        Returns:
            Dictionary with verification results
        """
        results = {
            'database': database,
            'scale_factor': scale_factor,
            'tables': {},
            'all_valid': True
        }
        
        # Calculate expected counts for scale factor
        base_counts = self.EXPECTED_ROW_COUNTS_SF100
        expected_counts = {
            table: int(count * (scale_factor / 100))
            for table, count in base_counts.items()
        }
        
        for table, expected in expected_counts.items():
            actual = self.get_table_row_count(table, database)
            
            if actual is None:
                results['tables'][table] = {
                    'expected': expected,
                    'actual': None,
                    'valid': False,
                    'error': 'Could not retrieve count'
                }
                results['all_valid'] = False
                continue
            
            # Check if within tolerance
            deviation = abs(actual - expected) / expected if expected > 0 else 0
            is_valid = deviation <= tolerance
            
            results['tables'][table] = {
                'expected': expected,
                'actual': actual,
                'deviation_pct': deviation * 100,
                'valid': is_valid
            }
            
            if not is_valid:
                results['all_valid'] = False
                logger.warning(
                    f"Row count mismatch for {table} on {database}: "
                    f"expected {expected}, got {actual} ({deviation*100:.2f}% deviation)"
                )
        
        return results
    
    def execute_sql(self, sql, database='default', fetch=True):
        """Execute raw SQL and return results."""
        try:
            with connections[database].cursor() as cursor:
                cursor.execute(sql)
                if fetch:
                    columns = [col[0] for col in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()
                    return {'columns': columns, 'rows': rows}
                return {'success': True}
        except Exception as e:
            logger.error(f"Error executing SQL on {database}: {e}")
            return {'error': str(e)}
    
    def clear_query_cache(self, database='default'):
        """Clear query cache if supported by database."""
        conn = connections[database]
        
        try:
            with conn.cursor() as cursor:
                if conn.vendor == 'mysql':
                    # MySQL 8.0 doesn't have query cache, but we can flush tables
                    cursor.execute("FLUSH TABLES;")
                    logger.info(f"Flushed tables on {database}")
                elif conn.vendor == 'oracle':
                    # Clear result cache
                    cursor.execute("ALTER SYSTEM FLUSH SHARED_POOL;")
                    cursor.execute("ALTER SYSTEM FLUSH BUFFER_CACHE;")
                    logger.info(f"Flushed caches on {database}")
                elif conn.vendor == 'microsoft':
                    # Clear plan cache and buffer pool
                    cursor.execute("DBCC DROPCLEANBUFFERS;")
                    cursor.execute("DBCC FREEPROCCACHE;")
                    logger.info(f"Cleared caches on {database}")
                elif conn.vendor == 'postgresql':
                    # PostgreSQL doesn't have a direct cache clear command
                    # Best we can do is close connections
                    logger.info(f"PostgreSQL cache clearing via connection restart")
        except Exception as e:
            logger.warning(f"Could not clear cache on {database}: {e}")
