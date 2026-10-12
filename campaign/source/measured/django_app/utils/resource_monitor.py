"""
Resource monitoring utility for CPU and memory utilization during benchmarks.
"""

import psutil
import time
import threading
import logging
from typing import Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)


class ResourceMonitor:
    """Monitor CPU and memory utilization during benchmark execution."""
    
    def __init__(self, sample_interval: float = 0.1):
        """
        Initialize resource monitor.
        
        Args:
            sample_interval: Time in seconds between samples (default: 0.1s = 10 samples/sec)
        """
        self.sample_interval = sample_interval
        self.monitoring = False
        self.samples: List[Dict[str, float]] = []
        self.monitor_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
    
    def start(self):
        """Start monitoring in background thread."""
        if self.monitoring:
            logger.warning("Monitor already running")
            return
        
        self.monitoring = True
        self.samples = []
        self.stop_event.clear()
        
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.debug("Resource monitoring started")
    
    def stop(self) -> Dict[str, float]:
        """
        Stop monitoring and return summary statistics.
        
        Returns:
            Dictionary with avg_cpu_percent, max_cpu_percent, avg_memory_percent, 
            max_memory_percent, avg_memory_mb, max_memory_mb
        """
        if not self.monitoring:
            return self._empty_stats()
        
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        
        self.monitoring = False
        
        if not self.samples:
            return self._empty_stats()
        
        # Calculate statistics
        cpu_values = [s['cpu_percent'] for s in self.samples]
        memory_percent_values = [s['memory_percent'] for s in self.samples]
        memory_mb_values = [s['memory_mb'] for s in self.samples]
        
        stats = {
            'avg_cpu_percent': sum(cpu_values) / len(cpu_values),
            'max_cpu_percent': max(cpu_values),
            'avg_memory_percent': sum(memory_percent_values) / len(memory_percent_values),
            'max_memory_percent': max(memory_percent_values),
            'avg_memory_mb': sum(memory_mb_values) / len(memory_mb_values),
            'max_memory_mb': max(memory_mb_values),
        }
        
        logger.debug(f"Resource monitoring stopped. Collected {len(self.samples)} samples")
        return stats
    
    def _monitor_loop(self):
        """Background monitoring loop."""
        import os
        process = psutil.Process(os.getpid())
        
        # Get initial CPU measurement (needed for accurate first reading)
        process.cpu_percent(interval=0.1)
        
        while not self.stop_event.is_set():
            try:
                # Get CPU usage for this process (non-blocking)
                cpu_percent = process.cpu_percent(interval=None)
                
                # Get memory usage for this process
                mem_info = process.memory_info()
                memory_mb = mem_info.rss / (1024 * 1024)  # Resident Set Size in MB
                
                # Get system memory to calculate percentage
                system_memory = psutil.virtual_memory()
                memory_percent = (mem_info.rss / system_memory.total) * 100
                
                self.samples.append({
                    'timestamp': time.time(),
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory_percent,
                    'memory_mb': memory_mb,
                })
                
                time.sleep(self.sample_interval)
                
            except Exception as e:
                logger.error(f"Error in resource monitoring: {e}")
                break
    
    def _empty_stats(self) -> Dict[str, float]:
        """Return empty statistics dictionary."""
        return {
            'avg_cpu_percent': 0.0,
            'max_cpu_percent': 0.0,
            'avg_memory_percent': 0.0,
            'max_memory_percent': 0.0,
            'avg_memory_mb': 0.0,
            'max_memory_mb': 0.0,
        }
    
    def get_current_stats(self) -> Dict[str, float]:
        """Get current resource usage (one-time snapshot)."""
        try:
            import os
            process = psutil.Process(os.getpid())
            cpu_percent = process.cpu_percent(interval=0.1)
            mem_info = process.memory_info()
            memory_mb = mem_info.rss / (1024 * 1024)
            
            system_memory = psutil.virtual_memory()
            memory_percent = (mem_info.rss / system_memory.total) * 100
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': memory_percent,
                'memory_mb': memory_mb,
            }
        except Exception as e:
            logger.error(f"Error getting current stats: {e}")
            return self._empty_stats()


class ContextResourceMonitor:
    """Context manager for resource monitoring."""
    
    def __init__(self, sample_interval: float = 0.1):
        self.monitor = ResourceMonitor(sample_interval=sample_interval)
        self.stats: Optional[Dict[str, float]] = None
    
    def __enter__(self):
        try:
            self.monitor.start()
        except Exception as e:
            logger.warning(f"Failed to start resource monitor: {e}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.stats = self.monitor.stop()
            # Validate stats were collected
            if self.stats and self.stats.get('avg_cpu_percent', 0) == 0:
                # If no samples collected, try to get at least one snapshot
                try:
                    current = self.monitor.get_current_stats()
                    if current and current.get('cpu_percent', 0) > 0:
                        self.stats = {
                            'avg_cpu_percent': current.get('cpu_percent', 0.0),
                            'max_cpu_percent': current.get('cpu_percent', 0.0),
                            'avg_memory_percent': current.get('memory_percent', 0.0),
                            'max_memory_percent': current.get('memory_percent', 0.0),
                            'avg_memory_mb': current.get('memory_mb', 0.0),
                            'max_memory_mb': current.get('memory_mb', 0.0),
                        }
                except:
                    pass
        except Exception as e:
            logger.warning(f"Failed to stop resource monitor: {e}")
            self.stats = self.monitor._empty_stats()
        return False
    
    def get_stats(self) -> Dict[str, float]:
        """Get collected statistics."""
        if self.stats is not None:
            return self.stats
        # Try to get current stats as fallback
        try:
            current = self.monitor.get_current_stats()
            if current:
                return {
                    'avg_cpu_percent': current.get('cpu_percent', 0.0),
                    'max_cpu_percent': current.get('cpu_percent', 0.0),
                    'avg_memory_percent': current.get('memory_percent', 0.0),
                    'max_memory_percent': current.get('memory_percent', 0.0),
                    'avg_memory_mb': current.get('memory_mb', 0.0),
                    'max_memory_mb': current.get('memory_mb', 0.0),
                }
        except:
            pass
        return self.monitor._empty_stats()

