"""Config endpoints."""

from typing import Any, Dict

from flask import Blueprint, current_app, jsonify

bp = Blueprint('config', __name__)


@bp.get("/config")
def get_config() -> Dict[str, Any]:
    """Get current configuration (sensitive values masked)."""
    config = current_app.config['FLASHBACK_CONFIG']

    # Return a safe subset of config
    cfg = config.to_dict()

    # Mask any sensitive paths
    return {
        "screenshot": cfg.get("screenshot"),
        "workers": cfg.get("workers"),
        "search": cfg.get("search"),
        "webui": cfg.get("webui"),
        "features": cfg.get("features"),
    }


@bp.post("/config/reload")
def reload_config() -> Dict[str, str]:
    """Reload configuration from file."""
    # Note: This won't affect already-running workers
    # A full restart is needed for some changes
    return {"status": "reload not implemented - restart required"}
