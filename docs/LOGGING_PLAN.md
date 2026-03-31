# Comprehensive Logging Plan for Flashback

## Goals

1. **Configurable verbosity** - From silent (errors only) to debug (everything)
2. **Multiple outputs** - Console, file, or both
3. **Structured information** - Timestamps, code locations, function names
4. **Performance awareness** - Logging shouldn't slow down the system
5. **Compatibility** - Use standard library with optional rich formatting

## Architecture

### Core Logging Strategy

**Primary Tool**: Python's built-in `logging` module
- Maximum compatibility (no extra dependencies)
- Standard configuration patterns
- Works with all Python libraries

**Console Enhancement**: `rich.logging.RichHandler` (optional)
- Already a project dependency
- Pretty colors, tracebacks, progress
- Falls back to standard StreamHandler if rich not available

### Configuration Schema

```yaml
# config.yaml
logging:
  # Global log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
  level: INFO

  # Console output settings
  console:
    enabled: true
    level: INFO           # Can be different from global
    format: "rich"        # Options: rich, simple, detailed
    colors: true          # ANSI colors (disable for pipes/files)
    show_time: true
    show_location: false  # File:line in console (verbose)

  # File output settings
  file:
    enabled: true
    level: DEBUG          # Usually more verbose than console
    path: "~/.local/share/flashback/flashback.log"
    max_size: "10MB"      # Rotate when exceeds size
    max_files: 5          # Number of rotated files to keep
    format: "detailed"    # Always detailed for files

  # Module-specific overrides (fine-grained control)
  modules:
    workers.screenshot: INFO
    workers.ocr: WARNING      # OCR can be noisy
    workers.embedding: DEBUG  # Debug embedding issues
    api.server: INFO
    api.routes.search: DEBUG
    database: WARNING
    search.bm25: INFO
    search.embedding: DEBUG

  # Special flags
  trace_calls: false      # Log function entry/exit
  trace_loops: false      # Log worker loop iterations
  trace_sql: false        # Log database queries
  trace_api: false        # Log API requests/responses
```

### Environment Variables

```bash
# Quick overrides without editing config
export FLASHBACK_CONFIG=/path/to/config.yaml
export FLASHBACK_LOG_LEVEL=DEBUG
export FLASHBACK_LOG_FILE=/var/log/flashback.log
export FLASHBACK_VERBOSE=1          # Shortcut for DEBUG level
export FLASHBACK_TRACE=1            # Enable all tracing
```

### CLI Flags

```bash
# Global verbosity flags
flashback serve --verbose           # INFO level
flashback serve --debug             # DEBUG level
flashback serve --trace             # DEBUG + all tracing
flashback serve --quiet             # WARNING level only

# Specific tracing
flashback serve --trace-workers     # Trace worker loops
flashback serve --trace-api         # Trace API calls
flashback serve --trace-sql         # Trace database queries

# Output control
flashback serve --log-file /path/to.log
flashback serve --no-console-log    # File only
```

## Implementation Plan

### Phase 1: Core Logging Infrastructure

**File: `flashback/core/logging_config.py`**

```python
"""Centralized logging configuration for flashback."""

import logging
import sys
from pathlib import Path
from typing import Optional

def setup_logging(config: Config) -> None:
    """Configure logging based on config."""
    # Get logging config from settings
    log_config = config.get("logging", {})

    # Root logger setup
    root_logger = logging.getLogger("flashback")
    root_logger.setLevel(log_config.get("level", "INFO"))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Setup console handler
    if log_config.get("console", {}).get("enabled", True):
        console_handler = _create_console_handler(log_config["console"])
        root_logger.addHandler(console_handler)

    # Setup file handler
    if log_config.get("file", {}).get("enabled", False):
        file_handler = _create_file_handler(log_config["file"])
        root_logger.addHandler(file_handler)

    # Apply module-specific levels
    _apply_module_levels(log_config.get("modules", {}))

def _create_console_handler(console_config: dict) -> logging.Handler:
    """Create console handler with rich or standard formatting."""
    level = console_config.get("level", "INFO")
    fmt = console_config.get("format", "rich")

    if fmt == "rich":
        try:
            from rich.logging import RichHandler
            handler = RichHandler(
                show_time=console_config.get("show_time", True),
                show_path=console_config.get("show_location", False),
            )
        except ImportError:
            handler = logging.StreamHandler(sys.stdout)
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setLevel(getattr(logging, level.upper()))
    handler.setFormatter(_get_formatter(fmt))
    return handler
```

### Phase 2: Logger Access Pattern

**File: `flashback/core/logger.py`**

```python
"""Logger access utilities."""

import logging
import functools
import time
from typing import Callable

# Cache of loggers by module name
_logger_cache = {}

def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module."""
    if name not in _logger_cache:
        _logger_cache[name] = logging.getLogger(f"flashback.{name}")
    return _logger_cache[name]

# Decorators for tracing

def trace_entry_exit(func: Callable) -> Callable:
    """Decorator to log function entry and exit."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        logger.debug(f"ENTER {func.__name__}({args}, {kwargs})")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"EXIT {func.__name__} -> {type(result).__name__}")
            return result
        except Exception as e:
            logger.debug(f"EXIT {func.__name__} with ERROR: {e}")
            raise
    return wrapper

def trace_loop(iteration_interval: int = 1):
    """Decorator to log worker loop iterations."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            counter = 0
            for item in func(*args, **kwargs):
                counter += 1
                if counter % iteration_interval == 0:
                    logger.debug(f"LOOP {func.__name__} iteration {counter}")
                yield item
        return wrapper
    return decorator

def timed(logger_name: str = None):
    """Decorator to log execution time."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name or func.__module__)
            start = time.monotonic()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                logger.debug(f"TIMER {func.__name__} took {elapsed:.3f}s")
        return wrapper
    return decorator
```

### Phase 3: Worker Logging

**Example: `flashback/workers/embedding.py`**

```python
from flashback.core.logger import get_logger, trace_entry_exit, trace_loop, timed

logger = get_logger("workers.embedding")

class EmbeddingWorker(QueueWorker):
    @trace_entry_exit
    def run(self):
        logger.info(f"[{self.name}] Starting embedding worker")
        logger.debug(f"[{self.name}] Mode: {self.mode}, Text client: {self.text_client}")
        # ...

    @trace_loop(iteration_interval=10)  # Log every 10 iterations
    def get_items(self) -> list:
        logger.debug(f"[{self.name}] Fetching items from database")
        return self.db.get_unprocessed_embeddings(limit=self.batch_size * 2)

    @timed("workers.embedding")
    @trace_entry_exit
    def process_item(self, item: ScreenshotRecord):
        logger.info(f"[{self.name}] Processing: {item.timestamp}")
        try:
            # ... processing ...
            logger.debug(f"[{self.name}] Generated embedding shape: {embedding.shape}")
        except Exception as e:
            logger.exception(f"[{self.name}] Failed to process {item}")
```

### Phase 4: API Request/Response Logging

**File: `flashback/api/middleware/logging.py`**

```python
"""FastAPI middleware for request/response logging."""

import time
from fastapi import Request, Response

async def log_requests(request: Request, call_next):
    """Middleware to log all API requests."""
    logger = get_logger("api.request")

    start_time = time.time()

    # Log request
    logger.debug(
        f"REQUEST {request.method} {request.url.path} "
        f"from {request.client.host if request.client else 'unknown'}"
    )

    # Process request
    response = await call_next(request)

    # Log response
    process_time = time.time() - start_time
    logger.debug(
        f"RESPONSE {request.method} {request.url.path} "
        f"status={response.status_code} time={process_time:.3f}s"
    )

    return response
```

### Phase 5: Database Query Logging

**File: `flashback/core/database.py`**

```python
import logging

# Enable SQLite query logging at DEBUG level
class Database:
    def _connect(self):
        conn = sqlite3.connect(...)
        if logger.isEnabledFor(logging.DEBUG):
            conn.set_trace_callback(self._log_query)
        return conn

    def _log_query(self, sql: str):
        logger.debug(f"SQL: {sql[:200]}")  # Truncate long queries
```

### Phase 6: CLI Integration

**File: `flashback/cli/main.py`**

```python
@click.group()
@click.option("--verbose", "-v", count=True, help="Increase verbosity (-v, -vv, -vvv)")
@click.option("--quiet", "-q", is_flag=True, help="Only show errors")
@click.option("--trace", is_flag=True, help="Enable all tracing")
@click.option("--log-file", type=click.Path(), help="Log to file")
@click.pass_context
def cli(ctx, verbose, quiet, trace, log_file):
    # Determine log level
    if quiet:
        level = "ERROR"
    elif trace:
        level = "DEBUG"
    elif verbose == 1:
        level = "INFO"
    elif verbose >= 2:
        level = "DEBUG"
    else:
        level = "WARNING"  # Default

    # Setup logging with CLI overrides
    config = Config()
    config.set("logging.level", level)
    if log_file:
        config.set("logging.file.enabled", True)
        config.set("logging.file.path", log_file)

    setup_logging(config)
```

## Log Format Options

### "rich" format (console)
```
[11:23:45] INFO     [workers.embedding] Model loaded: nomic-embed-text
[11:23:45] DEBUG    [workers.embedding] Processing: 1710930225
[11:23:46] WARNING  [workers.ocr] Tesseract not found, OCR disabled
```

### "detailed" format (file)
```
2024-03-20 11:23:45,123 | DEBUG | workers.embedding:process_item:87 | Processing: 1710930225
2024-03-20 11:23:45,456 | DEBUG | workers.embedding:process_item:92 | Generated embedding shape: (768,)
2024-03-20 11:23:45,789 | INFO  | workers.embedding:run:45 | Processed 10 items
```

### "simple" format
```
INFO: Model loaded: nomic-embed-text
DEBUG: Processing: 1710930225
```

## Migration Strategy

1. **Phase 1**: Add logging infrastructure (logger.py, logging_config.py)
2. **Phase 2**: Update workers with basic logging (INFO for operations, DEBUG for details)
3. **Phase 3**: Add tracing decorators and API middleware
4. **Phase 4**: Add CLI flags and environment variable support
5. **Phase 5**: Update documentation with examples

## Performance Considerations

- Use `logger.isEnabledFor(level)` before expensive debug operations
- Async logging for file handlers (don't block workers)
- Rate limiting for high-frequency logs (loop iterations)
- Structured logging for machine parsing (optional JSON format)

## Files to Modify

1. `flashback/core/logging_config.py` - NEW
2. `flashback/core/logger.py` - NEW
3. `flashback/core/config.py` - Add logging defaults
4. `flashback/cli/main.py` - Add CLI flags
5. `flashback/workers/base.py` - Add loop tracing
6. `flashback/workers/*.py` - Add module loggers
7. `flashback/api/server.py` - Add request logging middleware
8. `flashback/api/routes/*.py` - Add route logging
9. `config.example.yaml` - Add logging examples
10. `README.md` - Document logging options
