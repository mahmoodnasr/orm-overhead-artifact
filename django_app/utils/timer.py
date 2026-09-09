"""
High-precision timer for benchmark measurements.
Uses time.perf_counter() for microsecond precision as specified in paper.
"""

import time


class PrecisionTimer:
    """High-precision timer using time.perf_counter() for microsecond accuracy."""

    def __init__(self):
        self._start_time = None
        self._end_time = None

    def start(self):
        """Start timing."""
        self._start_time = time.perf_counter()
        self._end_time = None
        return self._start_time

    def stop(self):
        """Stop timing and return elapsed seconds."""
        if self._start_time is None:
            raise RuntimeError("Timer was not started")
        self._end_time = time.perf_counter()
        return self.elapsed()

    def elapsed(self):
        """Return elapsed time in seconds."""
        if self._start_time is None:
            raise RuntimeError("Timer was not started")
        end = self._end_time if self._end_time is not None else time.perf_counter()
        return end - self._start_time

    def elapsed_ms(self):
        """Return elapsed time in milliseconds."""
        return self.elapsed() * 1000

    def elapsed_us(self):
        """Return elapsed time in microseconds."""
        return self.elapsed() * 1_000_000

    def reset(self):
        """Reset the timer."""
        self._start_time = None
        self._end_time = None

    def __enter__(self):
        """Context manager support."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        self.stop()
        return False


def time_execution(func):
    """
    Decorator to time function execution.

    Returns:
        Tuple of (result, elapsed_seconds)
    """

    def wrapper(*args, **kwargs):
        timer = PrecisionTimer()
        timer.start()
        result = func(*args, **kwargs)
        elapsed = timer.stop()
        return result, elapsed

    return wrapper
