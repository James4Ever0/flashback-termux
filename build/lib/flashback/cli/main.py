"""Main CLI entry point for flashback."""

import shutil
import sys
from pathlib import Path

import click

# Import only what's needed for CLI structure
# Heavy imports happen inside command functions


def get_console():
    """Get rich console (lazy import)."""
    from rich.console import Console
    return Console()


@click.group()
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--data-dir", "-d",
    type=click.Path(path_type=Path),
    help="Override data directory",
)
@click.option(
    "--verbose", "-v",
    count=True,
    help="Increase output verbosity"
)
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-error output")
@click.option("--debug", is_flag=True, hidden=True, help="Enable debug output (same as -vv)")
@click.option("--trace", is_flag=True, hidden=True, help="Enable trace output (same as -vvv)")
@click.option("--log-file", type=click.Path(path_type=Path), help="Path to log file")
@click.version_option(version="0.1.0", prog_name="flashback")
@click.pass_context
def cli(ctx, config, data_dir, verbose, quiet, debug, trace, log_file):
    """Flashback - Search through your screenshot history.

    Flashback captures screenshots, performs OCR, and creates semantic
    embeddings to make your visual history searchable.

    \b
    Commands:
      serve     Start the backend daemon (captures screenshots)
      webui     Start the web UI server
      status    Check daemon health and status
      search    Search screenshots from command line
      view      View a specific screenshot
      config    Manage configuration
      stop      Stop running daemon(s)
      logs      View daemon logs

    \b
    Global Options (before COMMAND):
      -v, --verbose       Increase verbosity (-v=INFO, -vv=DEBUG, -vvv=TRACE)
      -q, --quiet         Suppress non-error output (overrides -v)
      --log-file PATH     Write logs to file

    \b
    Examples:
      flashback serve --daemon          # Start backend as daemon
      flashback search "meeting notes"  # Search for text in screenshots
      flashback view 20240320_142312    # View specific screenshot
      flashback -vv serve               # Start with debug logging
    """
    # Setup logging
    from flashback.core.config import Config
    from flashback.core.logging_config import setup_logging, get_log_level_from_verbosity

    # Map verbosity flags: -v=INFO, -vv=DEBUG, -vvv=TRACE
    # --debug is alias for -vv, --trace is alias for -vvv
    if quiet:
        effective_verbose = 0
    elif trace or verbose >= 3:
        effective_verbose = 3  # TRACE level
    elif debug or verbose >= 2:
        effective_verbose = 2  # DEBUG level
    elif verbose >= 1:
        effective_verbose = 1  # INFO level
    else:
        effective_verbose = 0  # WARNING level

    level = get_log_level_from_verbosity(effective_verbose, quiet)
    enable_trace = effective_verbose >= 3

    cfg = Config(config_path=config)
    if data_dir:
        cfg.set("data_dir", str(data_dir))

    setup_logging(cfg, level=level, log_file=str(log_file) if log_file else None, trace=enable_trace)

    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["data_dir"] = data_dir
    ctx.obj["verbose"] = effective_verbose


@cli.command()
@click.option("--daemon", "-D", is_flag=True, help="Run as background daemon")
@click.option("--foreground", "-F", is_flag=True, help="Run in foreground (default)")
@click.option("--pid-file", type=click.Path(path_type=Path), help="Write PID to file")
@click.option("--log-file", type=click.Path(path_type=Path), help="Write logs to file")
@click.pass_context
def serve(ctx, daemon, foreground, pid_file, log_file):
    """Start the backend daemon (screenshot capture and workers).

    This command starts all enabled workers including screenshot capture,
    OCR, embedding generation, and cleanup.

    \b
    Examples:
        flashback serve              # Run in foreground
        flashback serve --daemon     # Run as background daemon
        flashback serve -D --pid-file /tmp/flashback.pid
    """
    try:
        from flashback.core.config import Config
        from flashback.core.daemon import DaemonManager, daemonize
        from flashback.cli.commands import run_workers, check_dependencies
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies for 'serve' command", err=True)
        click.echo("Install with: pip install flashback-screenshots", err=True)
        sys.exit(1)

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))

    daemon_mgr = DaemonManager("backend")
    if daemon_mgr.is_running():
        console.print(f"[red]Backend is already running (PID: {daemon_mgr.get_pid()})[/red]")
        sys.exit(1)

    if not check_dependencies(config, console):
        sys.exit(1)

    if daemon:
        console.print("[green]Starting backend daemon...[/green]")
        if pid_file:
            daemon_mgr.pid_file = pid_file
        if log_file:
            daemon_mgr.log_file = log_file

        pid = daemonize(run_workers, daemon_mgr, config)
        if pid:
            console.print(f"[green]Daemon started (PID: {pid})[/green]")
        else:
            console.print("[red]Failed to start daemon[/red]")
            sys.exit(1)
    else:
        console.print("[bold]Flashback Backend[/bold]")
        console.print(f"Data directory: {config.data_dir}")
        enabled = [w for w in ["screenshot", "ocr", "embedding", "cleanup", "window_title"]
                   if config.is_worker_enabled(w)]
        console.print(f"Workers: {enabled}")
        console.print("Press Ctrl+C to stop\n")
        run_workers(config, console)


@cli.command()
@click.option("--host", help="Bind address")
@click.option("--port", type=int, help="Port number")
@click.option("--daemon", "-D", is_flag=True, help="Run as background daemon")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
@click.pass_context
def webui(ctx, host, port, daemon, no_browser):
    """Start the web UI server.

    This command starts the FastAPI web server for browser-based searching.

    \b
    Examples:
        flashback webui              # Run on default port, open browser
        flashback webui --port 3000  # Run on custom port
        flashback webui -D           # Run as daemon
    """
    try:
        from flashback.core.config import Config
        from flashback.core.daemon import DaemonManager
        from flashback.api.server import create_app
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies for 'webui' command", err=True)
        click.echo("Install with: pip install flashback-screenshots[webui]", err=True)
        sys.exit(1)

    console = get_console()

    config = Config(config_path=ctx.obj.get("config_path"))
    host = host or config.webui_host
    port = port or config.webui_port

    backend = DaemonManager("backend")
    if not backend.is_running():
        console.print("[yellow]Warning: Backend daemon is not running[/yellow]")
        console.print("[dim]Start it with: flashback serve --daemon[/dim]")

    webui_daemon = DaemonManager("webui")
    if webui_daemon.is_running():
        console.print(f"[red]Web UI is already running (PID: {webui_daemon.get_pid()})[/red]")
        sys.exit(1)

    if daemon:
        console.print("[green]Starting web UI daemon...[/green]")

    console.print(f"[green]Starting web UI on http://{host}:{port}[/green]")

    app = create_app(config)
    app.run(host=host, port=port, debug=False, threaded=True)


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--watch", "-w", type=int, help="Watch mode (refresh every N seconds)")
@click.pass_context
def status(ctx, json_output, watch):
    """Check backend health and status.

    \b
    Examples:
        flashback status
        flashback status --json
        flashback status -w 5
    """
    try:
        import json
        import time
        from flashback.core.config import Config
        from flashback.cli.commands import get_status
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies for 'status' command", err=True)
        click.echo("Install with: pip install flashback-screenshots", err=True)
        sys.exit(1)

    from rich.table import Table

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))

    def render_table(data):
        table = Table(title="Flashback Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")

        # Config file info
        cfg = data["config"]
        if cfg["found"]:
            table.add_row("Config File", f"[green]{cfg['path']}[/green]")
        else:
            table.add_row("Config File", "[yellow]Not found (using defaults)[/yellow]")

        backend = data["backend"]
        status_str = "[green]Running[/green]" if backend["running"] else "[red]Stopped[/red]"
        if backend["pid"]:
            status_str += f" (PID: {backend['pid']})"
        table.add_row("Backend", status_str)

        webui = data["webui"]
        status_str = "[green]Running[/green]" if webui["running"] else "[red]Stopped[/red]"
        if webui["pid"]:
            status_str += f" (PID: {webui['pid']})"
        table.add_row("Web UI", status_str)

        db = data["database"]
        table.add_row("Screenshots", str(db["screenshot_count"]))
        table.add_row("With OCR", str(db.get("with_ocr", 0)))
        table.add_row("With Embeddings", str(db.get("with_embedding", 0)))
        table.add_row("With Window Title", str(db.get("with_window_title", 0)))

        console.print(table)

        # If config not found, show search paths
        if not cfg["found"]:
            console.print("\n[dim]Config file search order:[/dim]")
            console.print(f"  1. $FLASHBACK_CONFIG: {cfg['search_paths']['env']}")
            console.print(f"  2. Local: {cfg['search_paths']['local']}")
            console.print(f"  3. User: {cfg['search_paths']['user']}")
            console.print("\n[dim]Create a config file with:[/dim] flashback config init")

    if watch:
        try:
            while True:
                console.clear()
                data = get_status(config)
                if json_output:
                    console.print(json.dumps(data, indent=2))
                else:
                    render_table(data)
                time.sleep(watch)
        except KeyboardInterrupt:
            console.print()
    else:
        data = get_status(config)
        if json_output:
            console.print(json.dumps(data, indent=2))
        else:
            render_table(data)


def _search_via_webui(console, webui_url, query, image_path, search_mode, limit, from_time, to_time,
                     output_format, preview, text_weight, image_weight):
    """Search via webui client mode (lazy imports)."""
    import requests

    # Check if webui is running via healthcheck endpoint
    health_url = f"{webui_url}/healthcheck"
    try:
        response = requests.get(health_url, timeout=5)
        if response.status_code != 200:
            console.print(f"[red]Web UI health check failed at {webui_url}/healthcheck [/red]")
            sys.exit(1)
    except requests.exceptions.Timeout:
        console.print(f"[red]Web UI not responding at {webui_url} (timeout after 5s)[/red]")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        console.print(f"[red]Web UI not running at {webui_url}[/red]")
        console.print("[dim]Start it with: flashback webui --daemon[/dim]")
        sys.exit(1)

    # Build search request
    params = {
        "q": query or "",
        "search_mode": search_mode,
        "limit": str(limit),
    }
    if from_time:
        params["from"] = from_time
    if to_time:
        params["to"] = to_time

    search_url = f"{webui_url}/api/v1/search"

    with console.status("[bold green]Searching via Web UI..."):
        try:
            if image_path:
                with open(image_path, "rb") as f:
                    files = {"image": f}
                    response = requests.post(search_url, params=params, files=files, timeout=30)
            else:
                response = requests.get(search_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Search request failed: {e}[/red]")
            sys.exit(1)

    if data.get("error"):
        console.print(f"[red]Search error: {data['error']}[/red]")
        sys.exit(1)

    # Display results
    results = data.get("results", [])
    score_breakdown = data.get("score_breakdown", {})

    # Convert webui results to format expected by display_search_results
    from flashback.core.database import Database
    from flashback.core.config import Config
    config = Config()
    db = Database(config.db_path, readonly=True)

    formatted_results = []
    for r in results:
        doc_id = r.get("id")
        score = r.get("score", 0)
        if doc_id:
            formatted_results.append((doc_id, score))

    from flashback.cli.commands import display_search_results
    display_search_results(formatted_results, db, query, search_mode, output_format, preview, score_breakdown, console)

    return formatted_results


def _search_local(console, config, query, image_path, search_mode, limit, from_time, to_time,
                 output_format, preview, text_weight, image_weight):
    """Search using local compute mode (lazy imports)."""
    from flashback.core.database import Database
    from flashback.cli.commands import (
        parse_time, search_bm25, search_text_embedding,
        search_image, search_multi_modal, display_search_results
    )
    from flashback.search.fusion import reciprocal_rank_fusion

    db = Database(config.db_path)

    if not query and not image_path:
        console.print("[red]Error: Either QUERY or --image must be provided[/red]")
        sys.exit(1)

    if search_mode is None:
        if image_path and query:
            search_mode = "text_and_image"
        elif image_path:
            search_mode = "image_embedding_only"
        else:
            search_mode = config.get_default_search_mode()

    start_ts = None
    end_ts = None
    if from_time:
        try:
            start_ts = parse_time(from_time)
        except ValueError as e:
            console.print(f"[red]Invalid --from: {e}[/red]")
            return []
    if to_time:
        try:
            end_ts = parse_time(to_time)
        except ValueError as e:
            console.print(f"[red]Invalid --to: {e}[/red]")
            return []

    results = []
    score_breakdown = {}

    with console.status("[bold green]Searching..."):
        if search_mode == "bm25_only":
            results = search_bm25(query, config, db, limit)
            score_breakdown = {"bm25": len(results)}
        elif search_mode == "text_embedding_only":
            results = search_text_embedding(query, config, db, limit)
            score_breakdown = {"text_embedding": len(results)}
        elif search_mode == "text_hybrid":
            bm25_results = search_bm25(query, config, db, limit * 2)
            emb_results = search_text_embedding(query, config, db, limit * 2)
            results = reciprocal_rank_fusion(bm25_results, emb_results, k=60, top_k=limit)
            score_breakdown = {"bm25": len(bm25_results), "text_embedding": len(emb_results)}
        elif search_mode == "image_embedding_only":
            results = search_image(image_path, config, db, limit)
            score_breakdown = {"image_embedding": len(results)}
        elif search_mode in ("text_and_image", "comprehensive"):
            results, score_breakdown = search_multi_modal(
                query, image_path, config, db, limit, text_weight, image_weight
            )

    if start_ts or end_ts:
        filtered = []
        for doc_id, score in results:
            record = db.get_by_id(doc_id)
            if not record:
                continue
            if start_ts and record.timestamp < start_ts:
                continue
            if end_ts and record.timestamp > end_ts:
                continue
            filtered.append((doc_id, score))
        results = filtered

    display_search_results(results, db, query, search_mode, output_format, preview, score_breakdown, console)

    return results


@cli.command()
@click.argument("query", required=False)
@click.option("--image", "image_path", type=click.Path(exists=True), help="Search by image file")
@click.option(
    "--search-mode",
    "-m",
    default=None,
    type=click.Choice([
        "bm25_only",
        "text_embedding_only",
        "text_hybrid",
        "image_embedding_only",
        "text_to_image",
        "text_and_image",
        "comprehensive",
    ]),
    help="Search mode to use",
)
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--from", "from_time", help="Start time (ISO or relative: 1d, 2h, 30m)")
@click.option("--to", "to_time", help="End time (ISO or relative)")
@click.option(
    "--format", "-F",
    "output_format",
    default="table",
    type=click.Choice(["table", "json", "csv", "simple"]),
)
@click.option("--preview", "-p", is_flag=True, help="Show OCR text excerpt")
@click.option("--open", "open_result", is_flag=True, help="Open first result in image viewer")
@click.option("--text-weight", type=float, default=0.5, help="Weight for text query")
@click.option("--image-weight", type=float, default=0.5, help="Weight for image query")
@click.option("--compute-mode", '-c', type=click.Choice(["local", "webui"]), default="local", help="Compute mode")
@click.pass_context
def search(ctx, query, image_path, search_mode, limit, from_time, to_time,
           output_format, preview, open_result, text_weight, image_weight, compute_mode):
    """Search through screenshot history.

    \b
    Examples:
        flashback search "meeting notes"
        flashback search --compute-mode webui "meeting notes"
        flashback search --image screenshot.png
        flashback search "bug" --from 1d --to now
        flashback search "TODO" --preview -n 10
    """
    try:
        from flashback.core.config import Config
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies for 'search' command", err=True)
        click.echo("Install with: pip install flashback-screenshots[search]", err=True)
        sys.exit(1)

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))

    if compute_mode == "webui":
        # Get webui URL from config
        host = config.webui_host
        port = config.webui_port
        webui_url = f"http://{host}:{port}"

        results = _search_via_webui(
            console, webui_url, query, image_path, search_mode, limit,
            from_time, to_time, output_format, preview, text_weight, image_weight
        )
    else:
        # Local compute mode
        results = _search_local(
            console, config, query, image_path, search_mode, limit,
            from_time, to_time, output_format, preview, text_weight, image_weight
        )

    if open_result and results:
        import subprocess
        try:
            from flashback.core.database import Database
            db = Database(config.db_path)
            record = db.get_by_id(results[0][0])
            if record:
                viewer_cmd = config.get("viewer.command", "xdg-open")
                subprocess.Popen([viewer_cmd, record.screenshot_path],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


@cli.command()
@click.argument("id_or_path")
@click.option("--text", "-t", is_flag=True, help="Show OCR text in terminal")
@click.option("--neighbors", "-n", default=0, help="Show N timeline neighbors")
@click.option("--copy", "-c", is_flag=True, help="Copy image path to clipboard")
@click.option("--export", "export_path", type=click.Path(), help="Copy image to path")
@click.pass_context
def view(ctx, id_or_path, text, neighbors, copy, export_path):
    """View a specific screenshot.

    \b
    Examples:
        flashback view 12
        flashback view 12 -t
        flashback view 12 -n 10
    """
    try:
        from flashback.core.config import Config
        from flashback.core.database import Database
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies for 'view' command", err=True)
        click.echo("Install with: pip install flashback-screenshots", err=True)
        sys.exit(1)

    import subprocess

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))
    db = Database(config.db_path)

    screenshot_path = None

    if Path(id_or_path).exists():
        screenshot_path = id_or_path
    else:
        try:
            screenshot_id = int(id_or_path)
        except ValueError:
            console.print(f"[red]Invalid ID or path: {id_or_path}[/red]")
            sys.exit(1)

    record = None
    if screenshot_id:
        record = db.get_by_id(screenshot_id)
    elif screenshot_path:
        all_records = db.get_unprocessed_ocr(limit=10000)
        for r in all_records:
            if r.screenshot_path == screenshot_path:
                record = r
                break

    if not record:
        console.print(f"[red]Screenshot not found: {id_or_path}[/red]")
        sys.exit(1)

    if text:
        if record.ocr_text:
            console.print(record.ocr_text)
        else:
            console.print("[yellow]No OCR text available[/yellow]")
        return

    if copy:
        try:
            import pyperclip
            pyperclip.copy(record.screenshot_path)
            console.print(f"[green]Copied: {record.screenshot_path}[/green]")
        except ImportError:
            console.print("[red]pyperclip not installed. Run: pip install pyperclip[/red]")
        return

    if export_path:
        shutil.copy(record.screenshot_path, export_path)
        console.print(f"[green]Exported to: {export_path}[/green]")
        return

    if neighbors > 0:
        neighbor_records = db.get_neighbors(record.timestamp, window_seconds=neighbors * 300)
        console.print(f"\n[bold]Timeline Context ({neighbors} neighbors):[/bold]\n")
        for r in sorted(neighbor_records, key=lambda x: x.timestamp):
            if r.timestamp < record.timestamp:
                rel = f"[-{int((record.timestamp - r.timestamp) / 60)}m]"
            elif r.timestamp > record.timestamp:
                rel = f"[+{int((r.timestamp - record.timestamp) / 60)}m]"
            else:
                rel = "[NOW]"
            marker = " <--" if abs(r.timestamp - record.timestamp) < 1 else ""
            console.print(f"{rel} {r.timestamp_formatted} - {r.window_title or 'Unknown'}{marker}")
        console.print()

    viewer_cmd = config.get("viewer.command", "xdg-open")
    args = [arg.replace("{path}", record.screenshot_path) for arg in config.get("viewer.args", ["{path}"])]
    subprocess.Popen([viewer_cmd] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@cli.group()
def config():
    """Manage flashback configuration."""
    pass


@config.command("show")
@click.pass_context
def config_show(ctx):
    """Display current configuration."""
    try:
        from flashback.core.config import Config
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies", err=True)
        sys.exit(1)

    from rich.syntax import Syntax

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))
    cfg_dict = config.to_dict()

    import yaml
    yaml_str = yaml.dump(cfg_dict, default_flow_style=False, sort_keys=True)
    console.print(Syntax(yaml_str, "yaml"))


@config.command("edit")
def config_edit():
    """Open configuration in $EDITOR."""
    import os
    import subprocess

    from flashback.core.config import get_config_dir

    config_path = get_config_dir() / "config.yaml"
    editor = os.environ.get("EDITOR", "nano")
    subprocess.call([editor, str(config_path)])


@config.command("init")
@click.option("--path", type=click.Path(path_type=Path))
def config_init(path):
    """Create default configuration file."""
    try:
        from flashback.core.config import Config
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies", err=True)
        sys.exit(1)

    console = get_console()
    config_path = Config.create_default(path)
    console.print(f"[green]Created configuration: {config_path}[/green]")


@config.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx, key):
    """Get a configuration value."""
    try:
        from flashback.core.config import Config
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies", err=True)
        sys.exit(1)

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))
    value = config.get(key)

    if value is None:
        console.print(f"[yellow]Key not found: {key}[/yellow]")

        # Get all possible config keys and suggest similar ones
        import difflib

        def get_all_keys(d, prefix=""):
            """Recursively get all dot-separated keys from config dict."""
            keys = []
            for k, v in d.items():
                full_key = f"{prefix}.{k}" if prefix else k
                keys.append(full_key)
                if isinstance(v, dict):
                    keys.extend(get_all_keys(v, full_key))
            return keys

        all_keys = get_all_keys(config.to_dict())
        matches = difflib.get_close_matches(key, all_keys, n=3, cutoff=0.3)

        if matches:
            console.print("\n[dim]Did you mean:[/dim]")
            for match in matches:
                console.print(f"  [cyan]• {match}[/cyan]")
        else:
            # Show some common keys as reference
            console.print("\n[dim]Common config keys:[/dim]")
            console.print("  [cyan]• screenshot.interval_seconds[/cyan]")
            console.print("  [cyan]• workers.ocr.enabled[/cyan]")
            console.print("  [cyan]• workers.embedding.mode[/cyan]")
            console.print("  [cyan]• search.default_search_mode[/cyan]")
    else:
        console.print(value)


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx, key, value):
    """Set a configuration value."""
    try:
        from flashback.core.config import Config
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies", err=True)
        sys.exit(1)

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))

    parsed_value = value
    try:
        parsed_value = int(value)
    except ValueError:
        try:
            parsed_value = float(value)
        except ValueError:
            if value.lower() in ("true", "yes", "on"):
                parsed_value = True
            elif value.lower() in ("false", "no", "off"):
                parsed_value = False

    config.set(key, parsed_value)
    config.save()
    console.print(f"[green]Set {key} = {parsed_value}[/green]")


@config.command("test-embedding")
@click.option("--type", "embedding_type", type=click.Choice(["text", "image"]), required=True)
@click.option("--write", is_flag=True, help="Write detected dimension to config")
@click.option("--image", "test_image_path", type=click.Path(exists=True))
@click.pass_context
def config_test_embedding(ctx, embedding_type, write, test_image_path):
    """Test embedding API connection."""
    try:
        from flashback.core.config import Config
        from flashback.core.embedding_client import EmbeddingAPIClient
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies", err=True)
        sys.exit(1)

    console = get_console()
    config = Config(config_path=ctx.obj.get("config_path"))

    if embedding_type == "text":
        api_config = config.get_text_embedding_config()
    else:
        api_config = config.get_image_embedding_config()

    if not api_config.get("model"):
        console.print(f"[red]Error: No {embedding_type} embedding model configured[/red]")
        return

    try:
        client = EmbeddingAPIClient(
            base_url=api_config.get("base_url", "https://api.openai.com/v1"),
            api_key=api_config.get("api_key", ""),
            model=api_config["model"],
            dimension=None,
            extra_headers=api_config.get("extra_headers", {}),
            name=embedding_type,
        )
    except Exception as e:
        console.print(f"[red]Failed to create embedding client: {e}[/red]")
        return

    console.print(f"[bold]Testing {embedding_type} embedding API...[/bold]")
    console.print(f"  Base URL: {client.base_url}")
    console.print(f"  Model: {client.model}\n")

    if embedding_type == "text":
        result = client.test_connection()
    else:
        result = client.test_image_embedding(test_image_path)

    if result["success"]:
        console.print(f"[green]Connection successful![/green]")
        console.print(f"  Detected dimension: [bold]{result['dimension']}[/bold]")
        if write:
            config.set_embedding_dimension(embedding_type, result["dimension"])
            config.save()
            console.print(f"[green]Saved dimension to configuration[/green]")
    else:
        console.print(f"[red]Connection failed:[/red]")
        console.print(f"  {result['message']}")


@cli.command()
@click.option("--backend", is_flag=True, help="Stop backend daemon")
@click.option("--webui", "stop_webui", is_flag=True, help="Stop web UI daemon")
@click.option("--all", "stop_all", is_flag=True, help="Stop all daemons")
def stop(backend, stop_webui, stop_all):
    """Stop running daemon(s).

    \b
    Examples:
        flashback stop --backend    # Stop backend only
        flashback stop --webui      # Stop web UI only
        flashback stop --all        # Stop all daemons
    """
    try:
        from flashback.core.daemon import DaemonManager
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies", err=True)
        sys.exit(1)

    console = get_console()

    if not backend and not stop_webui and not stop_all:
        backend = True  # Default to stopping backend

    stopped = False

    if backend or stop_all:
        daemon = DaemonManager("backend")
        if daemon.is_running():
            if daemon.stop():
                console.print("[green]Backend daemon stopped[/green]")
                stopped = True
            else:
                console.print("[red]Failed to stop backend daemon[/red]")
        else:
            console.print("[yellow]Backend daemon is not running[/yellow]")

    if stop_webui or stop_all:
        daemon = DaemonManager("webui")
        if daemon.is_running():
            if daemon.stop():
                console.print("[green]Web UI daemon stopped[/green]")
                stopped = True
            else:
                console.print("[red]Failed to stop Web UI daemon[/red]")
        else:
            console.print("[yellow]Web UI daemon is not running[/yellow]")

    if not stopped:
        sys.exit(1)


@cli.command()
@click.option("--backend", is_flag=True, help="Show backend logs")
@click.option("--webui", "show_webui", is_flag=True, help="Show web UI logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def logs(backend, show_webui, follow, lines):
    """View daemon logs.

    \b
    Examples:
        flashback logs --backend     # Show backend logs
        flashback logs -f --lines 100  # Follow last 100 lines
    """
    try:
        from flashback.core.daemon import DaemonManager
    except ImportError as e:
        import traceback
        traceback.print_exc()
        click.echo("\nError: Missing dependencies", err=True)
        sys.exit(1)

    import subprocess

    console = get_console()

    if not backend and not show_webui:
        backend = True  # Default to backend logs

    daemon_name = "backend" if backend else "webui"
    daemon = DaemonManager(daemon_name)

    if not daemon.log_file.exists():
        console.print(f"[yellow]No log file found for {daemon_name}[/yellow]")
        return

    log_path = daemon.log_file

    # Check if tail command exists
    tail_cmd = shutil.which("tail")

    if tail_cmd and not follow:
        # Use system tail for simple case (no follow)
        subprocess.run([tail_cmd, "-n", str(lines), str(log_path)])
    elif tail_cmd and follow:
        # Use system tail for follow mode
        subprocess.run([tail_cmd, "-f", "-n", str(lines), str(log_path)])
    else:
        # Fallback to Python implementation
        _tail_python(log_path, lines, follow)


def _tail_python(file_path: Path, lines: int, follow: bool):
    """Platform-independent tail implementation."""
    import time

    # Read last N lines
    def read_last_n_lines(path, n):
        """Efficiently read last N lines from file."""
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            # Seek to end and read backwards
            f.seek(0, 2)  # Seek to end
            file_size = f.tell()

            if file_size == 0:
                return []

            # Estimate bytes to read (average 100 chars per line)
            buffer_size = min(file_size, n * 100)
            f.seek(max(0, file_size - buffer_size))

            # Read and split lines
            lines = f.readlines()

            # Return last N lines
            return lines[-n:] if len(lines) >= n else lines

    # Print initial lines
    for line in read_last_n_lines(file_path, lines):
        print(line, end='')

    # Follow mode
    if follow:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            # Go to end of file
            f.seek(0, 2)

            try:
                while True:
                    line = f.readline()
                    if line:
                        print(line, end='')
                    else:
                        time.sleep(0.1)  # Small delay to avoid busy waiting
            except KeyboardInterrupt:
                # Graceful exit on Ctrl+C
                pass


def main():
    """Main entry point."""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n[yellow]Interrupted[/yellow]")
        sys.exit(130)
    except Exception as e:
        click.echo(f"[red]Error: {e}[/red]")
        if "--verbose" in sys.argv or "-v" in sys.argv:
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
