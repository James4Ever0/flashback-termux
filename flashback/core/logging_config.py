"""Centralized logging configuration for flashback."""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def human_readable_size(size_str: str) -> int:
    """Convert human readable size to bytes."""
    size_str = size_str.upper().strip()
    multipliers = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
    }
    for suffix, multiplier in multipliers.items():
        if size_str.endswith(suffix):
            return int(size_str[:-len(suffix)]) * multiplier
    return int(size_str)


def get_formatter(fmt_type: str, detailed: bool = False) -> logging.Formatter:
    """Get a formatter based on type."""
    if detailed or fmt_type == "detailed":
        return logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    elif fmt_type == "simple":
        return logging.Formatter("%(levelname)s: %(message)s")
    else:
        # Default format with timestamp
        return logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S"
        )


def _create_console_handler(console_config: Dict[str, Any]) -> logging.Handler:
    """Create console handler with rich or standard formatting."""
    level = console_config.get("level", "INFO")
    fmt = console_config.get("format", "rich")
    show_time = console_config.get("show_time", True)
    show_location = console_config.get("show_location", False)

    handler: logging.Handler

    if fmt == "rich":
        try:
            from rich.logging import RichHandler
            handler = RichHandler(
                show_time=show_time,
                show_path=show_location,
                rich_tracebacks=True,
                tracebacks_show_locals=True,
            )
            # RichHandler has its own formatter
            return handler
        except ImportError:
            # Fall back to standard handler
            handler = logging.StreamHandler(sys.stdout)
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Set formatter based on type
    if fmt == "simple":
        handler.setFormatter(get_formatter("simple"))
    elif show_location:
        handler.setFormatter(get_formatter("detailed"))
    else:
        handler.setFormatter(get_formatter("default"))

    return handler


def _create_file_handler(file_config: Dict[str, Any]) -> logging.Handler:
    """Create file handler with rotation."""
    level = file_config.get("level", "DEBUG")
    path_str = file_config.get("path", "~/.local/share/flashback/flashback.log")
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    max_size_str = file_config.get("max_size", "10MB")
    max_size = human_readable_size(max_size_str)
    max_files = file_config.get("max_files", 5)

    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_size,
        backupCount=max_files,
        encoding="utf-8",
    )
    handler.setLevel(getattr(logging, level.upper(), logging.DEBUG))
    handler.setFormatter(get_formatter("detailed"))

    return handler


def _apply_module_levels(modules_config: Dict[str, str]) -> None:
    """Apply module-specific log levels."""
    for module_name, level in modules_config.items():
        logger = logging.getLogger(f"flashback.{module_name}")
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))


def setup_logging(
    config: Optional[Any] = None,
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    trace: bool = False,
) -> None:
    """Configure logging based on config and CLI overrides.

    Args:
        config: Config object (optional)
        level: Override log level from CLI (optional)
        log_file: Override log file from CLI (optional)
        trace: Enable all tracing (optional)
    """
    # Get logging config from settings
    log_config: Dict[str, Any] = {}
    if config:
        log_config = getattr(config, '_config', {}).get("logging", {})

    # Determine log level
    if level:
        log_level = level.upper()
    elif trace:
        log_level = "DEBUG"
    else:
        log_level = log_config.get("level", "INFO").upper()

    # Root logger setup
    root_logger = logging.getLogger("flashback")
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Setup console handler
    console_config = log_config.get("console", {})
    if console_config.get("enabled", True):
        # CLI flags can override console level
        if level:
            console_config = {**console_config, "level": level}
        handler = _create_console_handler(console_config)
        root_logger.addHandler(handler)

    # Setup file handler
    file_config = log_config.get("file", {})
    if file_config.get("enabled", False) or log_file:
        if log_file:
            file_config = {**file_config, "path": log_file, "enabled": True}
        handler = _create_file_handler(file_config)
        root_logger.addHandler(handler)

    # Apply module-specific levels
    if trace:
        # In trace mode, set all flashback modules to DEBUG
        for name in ["workers", "api", "search", "core"]:
            logging.getLogger(f"flashback.{name}").setLevel(logging.DEBUG)
    else:
        _apply_module_levels(log_config.get("modules", {}))

    # Silence noisy third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    root_logger.debug(f"Logging configured: level={log_level}")


def get_log_level_from_verbosity(verbose: int, quiet: bool = False) -> str:
    """Get log level from verbosity count.

    Args:
        verbose: Verbosity level (0=WARNING, 1=INFO, 2=DEBUG, 3+=DEBUG with trace)
        quiet: If True, return ERROR regardless of verbose

    Returns:
        Logging level name
    """
    if quiet:
        return "ERROR"
    if verbose >= 2:
        return "DEBUG"
    elif verbose == 1:
        return "INFO"
    return "WARNING"
