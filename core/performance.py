"""
performance.py — Performance profiling and execution time logging utilities.
"""

import time
import functools
import logging
from typing import Callable, Any

logger = logging.getLogger("performance")


def profile_perf(action_name: str = ""):
    """Decorator to measure and log execution time of functions."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            name = action_name or func.__qualname__
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                if elapsed > 50:
                    logger.info("⏱ PERF: [%s] completed in %.2f ms", name, elapsed)
                else:
                    logger.debug("⏱ PERF: [%s] completed in %.2f ms", name, elapsed)
        return wrapper
    return decorator


class PerfTimer:
    """Context manager for timing code blocks."""
    def __init__(self, action_name: str):
        self.action_name = action_name
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.perf_counter() - self.start) * 1000
        if elapsed > 50:
            logger.info("⏱ PERF: [%s] completed in %.2f ms", self.action_name, elapsed)
        else:
            logger.debug("⏱ PERF: [%s] completed in %.2f ms", self.action_name, elapsed)
