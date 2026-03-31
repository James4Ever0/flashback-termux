# Lazy Import Strategy for CLI

## Problem

Currently, imports happen at module load time. This causes issues when:
1. User only wants help but missing deps cause import errors
2. One subcommand's deps block other subcommands from working
3. Import errors are cryptic instead of helpful

## Solution

Use lazy imports - only import when a command is actually invoked.

## Architecture

### 1. Main CLI Entry Point (main.py)

Should import only:
- Standard library
- click
- Core config (minimal)

Everything else imported lazily.

### 2. Lazy Import Pattern

```python
# In command function, at the top:
def my_command():
    try:
        from some_module import some_function
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("\nTo use this feature, install: pip install flashback-screenshots[extra_name]")
        sys.exit(1)

    # Now use the imported function
    some_function()
```

### 3. Help Behavior

Click's help system should work without importing subcommand modules.

Current structure that breaks this:
```python
from flashback.cli.serve import serve  # Import happens at module load
cli.add_command(serve)
```

New structure - use entry points:
```python
# Define commands in main.py with lazy loading
def get_serve_command():
    from flashback.cli.serve import serve
    return serve

# Or use click's lazy loading pattern
```

### 4. Specific Implementation Plan

**File: flashback/cli/main.py**

```python
import click
import sys

# Only import what's needed for CLI structure
from flashback.core.config import Config
from flashback.core.logging_config import setup_logging

def get_cmd(name):
    """Lazy load command modules."""
    if name == 'serve':
        try:
            from flashback.cli.serve import serve
            return serve
        except ImportError as e:
            # Return a placeholder that shows error when invoked
            @click.command(name='serve')
            def serve_cmd():
                import traceback
                traceback.print_exc()
                print("\nTo use the serve command, install: pip install flashback-screenshots")
                sys.exit(1)
            return serve_cmd
    elif name == 'webui':
        # Similar pattern...
        pass
    # etc...

@cli.group()
def cli():
    pass

# Register commands lazily
cli.add_command(get_cmd('serve'))
cli.add_command(get_cmd('webui'))
# etc...
```

### 5. Alternative: Inline Command Definitions

Define all commands in main.py with lazy imports inside:

```python
@click.command()
@click.option('--daemon', is_flag=True)
def serve(daemon):
    """Start backend daemon."""
    try:
        from flashback.core.daemon import DaemonManager
        from flashback.workers.screenshot import ScreenshotWorker
        # ... other imports
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("\nTo use the serve command: pip install flashback-screenshots")
        sys.exit(1)

    # Actual command logic here
```

### 6. Recommended Approach

Use **inline command definitions in main.py**:

Pros:
- Help works immediately (click extracts docstrings)
- Imports happen only when command runs
- Clear error messages with installation instructions
- No circular import issues

Cons:
- main.py becomes larger
- Less modular

Mitigation for cons:
- Keep actual logic in separate modules
- Command functions just import and call logic functions

### 7. Implementation Steps

1. **Create flashback/cli/commands.py** - Contains actual command logic
   ```python
   def do_serve(daemon, config):
       # All the serve logic here
       pass

   def do_webui(port, host):
       # All webui logic here
       pass

   def do_search(query, mode):
       # All search logic here
       pass
   ```

2. **Update flashback/cli/main.py** - CLI entry points with lazy imports
   ```python
   @click.command()
   @click.option('--daemon')
   def serve(daemon):
       try:
           from flashback.cli.commands import do_serve
       except ImportError as e:
           traceback.print_exc()
           print("\nInstall with: pip install flashback-screenshots")
           sys.exit(1)
       do_serve(daemon, Config())
   ```

3. **Remove old subcommand files** or keep as internal modules

### 8. Dependency Mapping

| Command | Required Extras | Import Error Message |
|---------|----------------|---------------------|
| serve | core | `pip install flashback-screenshots` |
| webui | webui | `pip install flashback-screenshots[webui]` |
| search | search | `pip install flashback-screenshots[search]` |
| config | core | `pip install flashback-screenshots` |
| status | core | `pip install flashback-screenshots` |

### 9. Help Handling

Click extracts help text from function docstrings. This happens at import time, but since we're defining commands in main.py with docstrings, help works without importing heavy deps.

For subcommand help (e.g., `flashback serve --help`):
- Click still needs to import the command
- But we can use lazy loading for sub-subcommands

### 10. Example Implementation

```python
# flashback/cli/main.py

import click
import sys

@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Flashback - Screenshot history search."""
    pass


@cli.command()
@click.option('--daemon', is_flag=True)
def serve(daemon):
    """Start backend daemon."""
    try:
        from flashback.core.daemon import DaemonManager
        from flashback.workers.manager import WorkerManager
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print(f"\nError: Missing dependencies for 'serve' command")
        print("Install with: pip install flashback-screenshots")
        sys.exit(1)

    # Actual logic
    if daemon:
        DaemonManager("backend").start()
    else:
        WorkerManager().run()


@cli.command()
@click.option('--port', default=8080)
def webui(port):
    """Start web UI server."""
    try:
        from flashback.api.server import main as server_main
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print(f"\nError: Missing dependencies for 'webui' command")
        print("Install with: pip install flashback-screenshots[webui]")
        sys.exit(1)

    # Run server
    server_main(port=port)


# ... other commands follow same pattern


if __name__ == '__main__':
    cli()
```

## Migration Plan

1. Create `flashback/cli/commands.py` - Move all command logic here
2. Update `flashback/cli/main.py` - Define commands with lazy imports
3. Keep old files for backward compatibility or remove them
4. Test each command works independently
5. Verify help works: `flashback --help`, `flashback serve --help`
6. Test import error messages work

## Files to Modify

- `flashback/cli/main.py` - Rewrite with inline commands
- `flashback/cli/commands.py` - NEW file with command logic
- (Optional) Deprecate `flashback/cli/serve.py`, `webui.py`, etc.
