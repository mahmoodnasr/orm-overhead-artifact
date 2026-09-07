#!/usr/bin/env python3
"""
Oracle Connection Manager for preventing session exhaustion during benchmarks.

This module provides a global connection limiter to prevent Oracle session exhaustion
when running multiple concurrent benchmarks.
"""

import threading
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class OracleConnectionManager:
    """
    Global connection manager to limit Oracle connections across all processes.
    
    This helps prevent Oracle session exhaustion during high-concurrency benchmarks.
    """
    
    def __init__(self, max_connections: int = 15):
        """
        Initialize the connection manager.
        
        Args:
            max_connections: Maximum number of concurrent Oracle connections allowed
        """
        self.max_connections = max_connections
        self._active_connections = 0
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
    
    def acquire_connection(self, timeout: float = 30.0) -> bool:
        """
        Acquire a connection slot.
        
        Args:
            timeout: Maximum time to wait for a connection slot
            
        Returns:
            True if connection slot acquired, False if timeout
        """
        with self._condition:
            start_time = time.time()
            
            while self._active_connections >= self.max_connections:
                remaining_time = timeout - (time.time() - start_time)
                if remaining_time <= 0:
                    logger.warning(f"Timeout waiting for Oracle connection slot (active: {self._active_connections})")
                    return False
                
                self._condition.wait(timeout=remaining_time)
            
            self._active_connections += 1
            logger.debug(f"Acquired Oracle connection slot (active: {self._active_connections}/{self.max_connections})")
            return True
    
    def release_connection(self):
        """Release a connection slot."""
        with self._condition:
            if self._active_connections > 0:
                self._active_connections -= 1
                logger.debug(f"Released Oracle connection slot (active: {self._active_connections}/{self.max_connections})")
                self._condition.notify()
    
    def get_active_count(self) -> int:
        """Get the current number of active connections."""
        with self._lock:
            return self._active_connections

# Global instance
_oracle_manager: Optional[OracleConnectionManager] = None
_manager_lock = threading.Lock()

def get_oracle_manager() -> OracleConnectionManager:
    """Get the global Oracle connection manager instance."""
    global _oracle_manager
    
    if _oracle_manager is None:
        with _manager_lock:
            if _oracle_manager is None:
                _oracle_manager = OracleConnectionManager(max_connections=15)
    
    return _oracle_manager

class OracleConnectionContext:
    """Context manager for Oracle connections with automatic slot management."""
    
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.manager = get_oracle_manager()
        self.acquired = False
    
    def __enter__(self):
        self.acquired = self.manager.acquire_connection(self.timeout)
        if not self.acquired:
            raise RuntimeError("Could not acquire Oracle connection slot within timeout")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            self.manager.release_connection()
