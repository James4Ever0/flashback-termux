"""Path utilities for flashback."""

import os
from pathlib import Path


def get_config_dir() -> Path:
    """Get the user configuration directory."""
    # Check environment variable first
    if "SS_CONFIG_DIR" in os.environ:
        return Path(os.environ["SS_CONFIG_DIR"])

    # Use XDG config dir on Linux, appropriate dirs on other platforms
    if os.name == "posix":
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / "flashback"
        return Path.home() / ".config" / "flashback"

    return Path.home() / ".flashback"


def get_data_dir() -> Path:
    """Get the data directory."""
    # Check environment variable first
    if "SS_DATA_DIR" in os.environ:
        return Path(os.environ["SS_DATA_DIR"]).expanduser()

    if os.name == "posix":
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            return Path(xdg_data) / "flashback"
        return Path.home() / ".local" / "share" / "flashback"

    return Path.home() / ".flashback" / "data"


def get_cache_dir() -> Path:
    """Get the cache directory."""
    if os.name == "posix":
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            return Path(xdg_cache) / "flashback"
        return Path.home() / ".cache" / "flashback"

    return Path.home() / ".flashback" / "cache"


def get_log_dir() -> Path:
    """Get the log directory."""
    if os.name == "posix":
        return Path.home() / ".local" / "state" / "flashback"
    return Path.home() / ".flashback" / "logs"


def ensure_dirs():
    """Ensure all necessary directories exist."""
    for dir_func in [get_config_dir, get_data_dir, get_cache_dir, get_log_dir]:
        dir_func().mkdir(parents=True, exist_ok=True)
