"""Command implementations for flashback CLI.

This module contains the actual command logic. It's separate from main.py
to enable lazy imports - commands are only imported when invoked.
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def parse_time(time_str: str) -> Optional[float]:
    """Parse time string (relative or absolute)."""
    if not time_str:
        return None

    # Check for relative time (e.g., "1d", "2h", "30m")
    if time_str.endswith("d"):
        days = int(time_str[:-1])
        return (datetime.now() - timedelta(days=days)).timestamp()
    if time_str.endswith("h"):
        hours = int(time_str[:-1])
        return (datetime.now() - timedelta(hours=hours)).timestamp()
    if time_str.endswith("m"):
        minutes = int(time_str[:-1])
        return (datetime.now() - timedelta(minutes=minutes)).timestamp()

    # Try absolute time
    try:
        return datetime.fromisoformat(time_str).timestamp()
    except ValueError:
        pass

    # Try common formats
    for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(time_str, fmt).timestamp()
        except ValueError:
            continue

    raise ValueError(f"Cannot parse time: {time_str}")


def check_dependencies(config: Any, console: Any) -> bool:
    """Check if required dependencies are available.

    Returns True if should continue, False to exit.
    """
    import click

    errors = []

    if config.is_worker_enabled("ocr"):
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception as e:
            errors.append(f"OCR (tesseract) not available: {e}")
            errors.append("  Install: sudo apt-get install tesseract-ocr")

    if config.is_worker_enabled("embedding"):
        try:
            import requests
        except ImportError:
            errors.append("Embedding requires 'requests' package")
            errors.append("  Install: pip install flashback-screenshots")
        try:
            import numpy
        except ImportError:
            errors.append("Embedding requires 'numpy' package")
            errors.append("  Install: pip install flashback-screenshots[embedding]")

    if errors:
        for error in errors:
            console.print(f"[red]{error}[/red]")
        if click.confirm("Continue without these features?"):
            for worker in ["ocr", "embedding"]:
                if any(worker in e.lower() for e in errors):
                    config.set(f"workers.{worker}.enabled", False)
            return True
        return False
    return True


def run_workers(config: Any, console: Any) -> None:
    """Run all enabled workers (in separate processes)."""
    from flashback.workers.screenshot import ScreenshotWorker
    from flashback.workers.ocr import OCRWorker
    from flashback.workers.embedding import EmbeddingWorker
    from flashback.workers.cleanup import CleanupWorker
    from flashback.workers.window_title import WindowTitleWorker

    config_path = str(config._config_path) if hasattr(config, '_config_path') else None
    db_path = str(config.db_path) if hasattr(config, 'db_path') else None

    workers = []

    if config.is_worker_enabled("screenshot"):
        workers.append(ScreenshotWorker(config_path=config_path, db_path=db_path))

    if config.is_worker_enabled("ocr"):
        try:
            workers.append(OCRWorker(config_path=config_path, db_path=db_path))
        except Exception as e:
            console.print(f"[yellow]Failed to start OCR worker: {e}[/yellow]")

    if config.is_worker_enabled("embedding"):
        try:
            workers.append(EmbeddingWorker(config_path=config_path, db_path=db_path))
        except Exception as e:
            console.print(f"[yellow]Failed to start Embedding worker: {e}[/yellow]")

    if config.is_worker_enabled("cleanup"):
        workers.append(CleanupWorker(config_path=config_path, db_path=db_path))

    if config.is_worker_enabled("window_title"):
        try:
            workers.append(WindowTitleWorker(config_path=config_path, db_path=db_path))
        except Exception as e:
            console.print(f"[yellow]Failed to start Window Title worker: {e}[/yellow]")

    if not workers:
        console.print("[red]No workers enabled![/red]")
        sys.exit(1)

    for worker in workers:
        worker.start()
        console.print(f"[green]Started {worker.name}[/green]")

    running = True

    def signal_handler(signum, frame):
        nonlocal running
        console.print("\n[yellow]Shutting down...[/yellow]")
        running = False
        for worker in workers:
            worker.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while running:
        for worker in workers:
            if not worker.is_alive() and running:
                console.print(f"[red]{worker.name} died unexpectedly[/red]")
        time.sleep(1)

    for worker in workers:
        worker.join(timeout=5)

    console.print("[green]Shutdown complete[/green]")


def get_status(config: Any) -> Dict[str, Any]:
    """Get system status."""
    from flashback.core.daemon import DaemonManager
    from flashback.core.database import Database
    from flashback.core.paths import get_config_dir

    backend = DaemonManager("backend")
    webui = DaemonManager("webui")
    db = Database(config.db_path)
    stats = db.get_stats()

    # Get config file info
    config_path = getattr(config, '_config_path', None)
    config_found = config_path is not None and config_path.exists()

    return {
        "config": {
            "found": config_found,
            "path": str(config_path) if config_found else None,
            "search_paths": {
                "env": os.environ.get("FLASHBACK_CONFIG", "not set"),
                "local": str(Path("config.yaml").absolute()),
                "user": str(get_config_dir() / "config.yaml"),
            },
        },
        "backend": {
            "running": backend.is_running(),
            "pid": backend.get_pid(),
        },
        "webui": {
            "running": webui.is_running(),
            "pid": webui.get_pid(),
        },
        "database": {
            "screenshot_count": stats["total"],
            "with_ocr": stats.get("with_ocr", 0),
            "with_embedding": stats.get("with_embedding", 0),
            "with_window_title": stats.get("with_window_title", 0),
            "oldest_timestamp": stats.get("oldest_timestamp"),
            "newest_timestamp": stats.get("newest_timestamp"),
        },
    }


def search_bm25(query: str, config: Any, db: Any, top_k: int) -> List[Tuple[int, float]]:
    """Perform BM25 search."""
    from flashback.search.bm25 import BM25Search
    bm25 = BM25Search(config, db)
    return bm25.search(query, top_k=top_k)


def search_text_embedding(query: str, config: Any, db: Any, top_k: int) -> List[Tuple[int, float]]:
    """Perform text embedding search."""
    from flashback.search.embedding import TextEmbeddingSearch
    text_search = TextEmbeddingSearch(config, db)
    return text_search.search(query, top_k=top_k)


def search_image(image_path: str, config: Any, db: Any, top_k: int) -> List[Tuple[int, float]]:
    """Perform image embedding search."""
    from flashback.search.embedding import ImageEmbeddingSearch
    image_search = ImageEmbeddingSearch(config, db)
    return image_search.search_by_image(image_path, top_k=top_k)


def search_multi_modal(
    query: Optional[str],
    image_path: Optional[str],
    config: Any,
    db: Any,
    top_k: int,
    text_weight: float,
    image_weight: float
) -> Tuple[List[Tuple[int, float]], Dict]:
    """Perform multi-modal search."""
    from flashback.search.embedding import HybridEmbeddingSearch
    from PIL import Image

    hybrid = HybridEmbeddingSearch(config, db)
    hybrid.weights["text_weight"] = text_weight
    hybrid.weights["image_weight"] = image_weight

    image = None
    if image_path:
        image = Image.open(image_path)

    results, metadata = hybrid.search_fused(
        text_query=query,
        image_query=image,
        top_k=top_k,
    )
    return results, metadata


def display_search_results(
    results: List[Tuple[int, float]],
    db: Any,
    query: str,
    search_mode: str,
    output_format: str,
    preview: bool,
    score_breakdown: Dict,
    console: Any
) -> None:
    """Display search results."""
    from rich.table import Table

    formatted_results = []
    for doc_id, score in results:
        record = db.get_by_id(doc_id)
        if record:
            formatted_results.append((record, score))

    if not formatted_results:
        console.print("[yellow]No results found[/yellow]")
        return

    if output_format == "simple":
        for record, _ in formatted_results:
            console.print(record.screenshot_path)
    elif output_format == "json":
        output = [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "path": r.screenshot_path,
                "window_title": r.window_title,
                "score": score,
                "ocr_preview": (r.ocr_text or "")[:200] if preview else None,
            }
            for r, score in formatted_results
        ]
        console.print(json.dumps({
            "query": query,
            "search_mode": search_mode,
            "score_breakdown": score_breakdown,
            "results": output,
        }, indent=2))
    elif output_format == "csv":
        console.print("id,timestamp,path,window_title,score")
        for record, score in formatted_results:
            console.print(
                f"{record.id},{record.timestamp_formatted},{record.screenshot_path},"
                f"{record.window_title or ''},{score:.4f}"
            )
    else:  # table
        table = Table(title=f'Search Results: "{query or "(image query)"}" ({search_mode})')
        table.add_column("#", style="cyan", justify="right")
        table.add_column("ID", style="red")
        table.add_column("Time", style="green")
        table.add_column("Score", style="yellow")
        table.add_column("Window", style="blue")
        if preview:
            table.add_column("Preview", style="dim")

        for i, (record, score) in enumerate(formatted_results, 1):
            row = [
                str(i),
                str(record.id),
                record.timestamp_formatted,
                f"{score:.2f}",
                (record.window_title or "")[:30],
            ]
            if preview:
                text = (record.ocr_text or "")[:100].replace("\n", " ")
                row.append(text + "..." if len(record.ocr_text or "") > 100 else text)
            table.add_row(*row)

        console.print(table)

        if score_breakdown:
            breakdown_str = ", ".join(
                f"{k}: {v}" for k, v in score_breakdown.items() if not k.endswith("_error")
            )
            if breakdown_str:
                console.print(f"\n[dim]Score breakdown: {breakdown_str}[/dim]")
