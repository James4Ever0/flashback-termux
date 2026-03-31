"""Logger access utilities for flashback."""

import functools
import logging
import time
from typing import Any, Callable, TypeVar, Optional

# Cache of loggers by module name
_logger_cache: dict = {}

F = TypeVar("F", bound=Callable[..., Any])


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module.

    Args:
        name: Module name (e.g., 'workers.embedding', 'api.server')

    Returns:
        Logger instance
    """
    if name not in _logger_cache:
        # Ensure it starts with 'flashback.'
        if not name.startswith("flashback."):
            name = f"flashback.{name}"
        _logger_cache[name] = logging.getLogger(name)
    return _logger_cache[name]


def trace_entry_exit(func: F) -> F:
    """Decorator to log function entry and exit.

    Logs at DEBUG level when entering and exiting a function.
    Captures function arguments and return values.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger = get_logger(func.__module__)

        # Format arguments (truncate long values)
        args_repr = []
        for arg in args[1:] if len(args) > 0 and hasattr(args[0], '__class__') else args:  # Skip 'self'
            arg_str = repr(arg)
            if len(arg_str) > 100:
                arg_str = arg_str[:97] + "..."
            args_repr.append(arg_str)

        kwargs_repr = [f"{k}={repr(v)[:50]}" for k, v in kwargs.items()]
        all_args = ", ".join(args_repr + kwargs_repr)
        if len(all_args) > 200:
            all_args = all_args[:197] + "..."

        logger.debug(f"ENTER {func.__qualname__}({all_args})")

        try:
            start = time.monotonic()
            result = func(*args, **kwargs)
            elapsed = time.monotonic() - start

            result_type = type(result).__name__
            logger.debug(f"EXIT {func.__qualname__} -> {result_type} ({elapsed:.3f}s)")
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.debug(f"EXIT {func.__qualname__} with ERROR: {e} ({elapsed:.3f}s)")
            raise

    return wrapper  # type: ignore


def trace_loop(iteration_interval: int = 1) -> Callable[[F], F]:
    """Decorator to log worker loop iterations.

    Args:
        iteration_interval: Log every N iterations (default: 1)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger(func.__module__)
            counter = 0

            for item in func(*args, **kwargs):
                counter += 1
                if counter % iteration_interval == 0:
                    logger.debug(f"LOOP {func.__qualname__} iteration {counter}")
                yield item

        return wrapper  # type: ignore
    return decorator


def timed(logger_name: Optional[str] = None) -> Callable[[F], F]:
    """Decorator to log execution time.

    Args:
        logger_name: Optional logger name (defaults to function's module)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            name = logger_name or func.__module__
            logger = get_logger(name)

            start = time.monotonic()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                logger.debug(f"TIMER {func.__qualname__} took {elapsed:.3f}s")

        return wrapper  # type: ignore
    return decorator


def log_operation(
    operation: str,
    level: int = logging.INFO,
    logger_name: Optional[str] = None,
) -> Callable[[F], F]:
    """Decorator to log an operation with start/success/failure.

    Args:
        operation: Description of the operation
        level: Log level for success message
        logger_name: Optional logger name
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            name = logger_name or func.__module__
            logger = get_logger(name)

            logger.debug(f"START {operation}")
            start = time.monotonic()

            try:
                result = func(*args, **kwargs)
                elapsed = time.monotonic() - start
                logger.log(level, f"SUCCESS {operation} ({elapsed:.2f}s)")
                return result
            except Exception as e:
                elapsed = time.monotonic() - start
                logger.error(f"FAILED {operation}: {e} ({elapsed:.2f}s)")
                raise

        return wrapper  # type: ignore
    return decorator


# For compatibility with typing
from typing import Optional
