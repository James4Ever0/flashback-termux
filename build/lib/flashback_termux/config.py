"""
Configuration management for Flashback Termux.
"""

import json
import os
from typing import Dict, Any


def get_default_config() -> Dict[str, Any]:
    """Get default configuration with home directory expansion."""
    home = os.path.expanduser("~")
    return {
        "screenshot_dir": os.path.join(home, "storage", "pictures", "flashback"),
        "interval_seconds": 60,
        "webui": {
            "host": "127.0.0.1",
            "port": 8080,
            "mobile_friendly": True
        },
        "context_detection": {
            "enabled": True,
            "use_app_name": True,
            "fallback_to_package": True
        },
        "retention": {
            "days": 30
        }
    }


def get_config_path() -> str:
    """Get the configuration file path using home directory expansion."""
    return os.path.expanduser("~/.config/flashback-termux/config.json")


def load_config() -> Dict[str, Any]:
    """
    Load configuration from file or create default.

    Returns:
        Configuration dictionary
    """
    config_path = get_config_path()
    defaults = get_default_config()

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            # Merge with defaults for any missing keys
            merged = defaults.copy()
            merged.update(config)
            return merged
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load config: {e}")
            return defaults
    else:
        return defaults


def save_config(config: Dict[str, Any]) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration dictionary to save
    """
    config_path = get_config_path()
    config_dir = os.path.dirname(config_path)
    os.makedirs(config_dir, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
