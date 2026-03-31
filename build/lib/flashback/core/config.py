"""YAML configuration management for flashback."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from flashback.core.paths import get_config_dir, get_data_dir

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    yaml = None  # type: ignore


# Default configuration
DEFAULT_CONFIG: Dict[str, Any] = {
    "data_dir": str(get_data_dir()),
    "screenshot": {
        "enabled": True,
        "interval_seconds": 60,
        "quality": 85,
        "formats": ["png"],
        # Screenshot backend for Android/Termux 
        # Note: Screenshots require root access (su) on Android/Termux
        "backend": {
            "enabled": "screencap",
            # Uses Android's screencap binary via su to capture screenshots
            # Target display configuration is invalid for screencap. 
            # One can only capture main display using screencap.
            "screencap": {},
            "scrcpy": {"target_display": "focused"},
        }
    },
    "workers": {
        "screenshot": {"enabled": True},
        "ocr": {
            "enabled": True,
            "work_interval_seconds": 1,
            "batch_size": 5,
            "languages": ["eng", "chi_sim"],
        },
        "embedding": {
            "enabled": False,
            "work_interval_seconds": 1,
            "batch_size": 3,
            # Embedding mode: text-only, image-only, text-image-hybrid
            "mode": "text-image-hybrid",
            # Text embedding configuration (OpenAI-compatible API)
            "text": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "${OPENAI_API_KEY}",
                "model": "text-embedding-3-small",
                "dimension": None,  # Auto-detected via test-embedding command
                "extra_headers": {},
            },
            # Image embedding configuration (vision-capable API)
            "image": {
                "base_url": "http://localhost:11434/v1",
                "api_key": "",
                "model": "llava",
                "dimension": None,  # Auto-detected via test-embedding command
                "extra_headers": {},
            },
            # Hybrid search weights (only used in text-image-hybrid mode)
            "hybrid_weights": {
                "text_weight": 0.5,
                "image_weight": 0.5,
                "rrf_k": 60,
            },
        },
        "cleanup": {
            "enabled": True,
            "check_interval_seconds": 3600,
            "retention_days": 7,
        },
        "window_title": {
            "enabled": True,
            "poll_interval_seconds": 1,
            # Only associate window titles with screenshots taken within this time window
            # Prevents updating old screenshots when user switches windows
            "max_screenshot_age_seconds": 30,
        },
    },
    "search": {
        "enabled_methods": {"bm25": True, "text_embedding": False, "image_embedding": False},
        "bm25": {
            "k1": 1.5,
            "b": 0.75,
            "default_limit": 50,
            "refresh_interval_seconds": 600,  # BM25 index refresh interval (10 minutes)
            "db_path": "bm25_index.db",
            "tokenizer": {
                "backend": "jieba",  # Default tokenizer: "jieba", "spacy", "simple", or "auto"
                "language_confidence_threshold": 0.7,
                "jieba": {"mode": "accurate"},
                "spacy": {
                    "model": "en_core_web_sm",  # Options: en_core_web_sm, zh_core_web_sm, etc.
                    "auto_download": True,
                },
            },
        },
        "text_embedding": {"default_limit": 50},
        "image_embedding": {"default_limit": 50},
        # Comprehensive search modes
        "search_modes": {
            "bm25_only": {
                "description": "BM25 text search only",
                "inputs": ["text"],
                "methods": {"bm25": {"weight": 1.0}},
            },
            "text_embedding_only": {
                "description": "Text embedding search only",
                "inputs": ["text"],
                "methods": {"text_embedding": {"weight": 1.0}},
            },
            "text_hybrid": {
                "description": "BM25 + text embedding fusion",
                "inputs": ["text"],
                "methods": {"bm25": {"weight": 0.3}, "text_embedding": {"weight": 0.7}},
                "fusion": "reciprocal_rank",
                "rrf_k": 60,
            },
            "image_embedding_only": {
                "description": "Image embedding search only",
                "inputs": ["image"],
                "methods": {"image_embedding": {"weight": 1.0}},
            },
            "text_to_image": {
                "description": "Search images using text query (requires CLIP-like model)",
                "inputs": ["text"],
                "methods": {"image_embedding": {"weight": 1.0}},
            },
            "text_and_image": {
                "description": "Query with both text and image",
                "inputs": ["text", "image"],
                "methods": {
                    "text_embedding": {"weight": 0.5},
                    "image_embedding": {"weight": 0.5},
                },
                "fusion": "reciprocal_rank",
                "rrf_k": 60,
            },
            "comprehensive": {
                "description": "BM25 + text embedding + image embedding",
                "inputs": ["text", "image"],
                "methods": {
                    "bm25": {"weight": 0.2},
                    "text_embedding": {"weight": 0.4},
                    "image_embedding": {"weight": 0.4},
                },
                "fusion": "reciprocal_rank",
                "rrf_k": 60,
            },
        },
        "default_search_mode": "bm25_only",
    },
    "webui": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8080,
        # Maximum age for "latest screenshot" endpoint (seconds)
        # Screenshots older than this will return 404
        "latest_screenshot_age_limit_seconds": 120,  # Default: 2 minutes
    },
    "features": {
        "ocr": "auto",
        "embedding_search": "auto",
        "semantic_search": "auto",
    },
    "viewer": {
        "command": "xdg-open",
        "args": ["{path}"],
    },
    "logging": {
        "level": "INFO",
        "console": {
            "enabled": True,
            "level": "INFO",
            "format": "rich",
            "colors": True,
            "show_time": True,
            "show_location": False,
        },
        "file": {
            "enabled": False,
            "level": "DEBUG",
            "path": "~/.local/share/flashback/flashback.log",
            "max_size": "10MB",
            "max_files": 5,
            "format": "detailed",
        },
        "modules": {},
        "trace_calls": False,
        "trace_loops": False,
        "trace_sql": False,
        "trace_api": False,
    },
}


class Config:
    """Configuration manager for flashback."""

    _instance: Optional["Config"] = None

    def __new__(cls, config_path: Optional[Path] = None) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: Optional[Path] = None):
        if self._initialized:
            return

        self._config: Dict[str, Any] = {}
        self._config_path = config_path or self._find_config_file()
        self._load_config()
        self._validate()
        self._initialized = True

    def _find_config_file(self) -> Optional[Path]:
        """Find configuration file in standard locations.

        Search order:
        1. $FLASHBACK_CONFIG environment variable (if set and file exists)
        2. ./config.yaml (current directory)
        3. ~/.config/flashback/config.yaml (user config directory)
        """
        # Check environment variable
        if "FLASHBACK_CONFIG" in os.environ:
            path = Path(os.environ["FLASHBACK_CONFIG"])
            if path.exists():
                return path

        # Check local directory
        local = Path("config.yaml")
        if local.exists():
            return local

        # Check user config directory
        user = get_config_dir() / "config.yaml"
        if user.exists():
            return user

        return None

    def _load_config(self):
        """Load configuration from file or use defaults."""
        self._config = self._deep_copy(DEFAULT_CONFIG)

        if not HAS_YAML:
            print("[WARN] PyYAML not installed, using default config")
            print("[INFO] Install with: pip install pyyaml")
            self._config = self._substitute_env_vars(self._config)
            return

        if self._config_path and self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    user_config = yaml.safe_load(f)
                    if user_config:
                        self._deep_merge(self._config, user_config)
            except Exception as e:
                print(f"[WARN] Failed to load config: {e}, using defaults")

        # Substitute environment variables
        self._config = self._substitute_env_vars(self._config)

    def _deep_copy(self, obj: Any) -> Any:
        """Deep copy a nested dict/list structure."""
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._deep_copy(item) for item in obj]
        return obj

    def _deep_merge(self, base: Dict, override: Dict):
        """Deep merge override into base."""
        for key, value in override.items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _substitute_env_vars(self, obj: Any) -> Any:
        """Substitute environment variables in string values.

        Supports ${VAR_NAME} syntax.
        """
        if isinstance(obj, dict):
            return {k: self._substitute_env_vars(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._substitute_env_vars(item) for item in obj]
        if isinstance(obj, str):
            # Pattern: ${VAR_NAME} or ${VAR_NAME:-default}
            pattern = r'\$\{([^}]+)\}'

            def replace_var(match):
                var_expr = match.group(1)
                if ':-' in var_expr:
                    var_name, default = var_expr.split(':-', 1)
                    return os.environ.get(var_name, default)
                return os.environ.get(var_expr, match.group(0))

            return re.sub(pattern, replace_var, obj)
        return obj

    def _validate(self):
        """Validate and normalize configuration."""
        # Expand data directory path
        data_dir = Path(self._config["data_dir"]).expanduser()
        self._config["data_dir"] = str(data_dir)

        # Create subdirectories
        self.screenshot_dir = data_dir / "screenshots"
        self.ocr_dir = data_dir / "ocr"
        self.embedding_dir = data_dir / "embeddings"
        self.db_path = data_dir / "database.db"

        for d in [self.screenshot_dir, self.ocr_dir, self.embedding_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Auto-detect platform for viewer
        if os.name == "darwin":  # macOS
            self._config["viewer"]["command"] = "open"
        elif os.name == "nt":  # Windows
            self._config["viewer"]["command"] = "start"

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-separated key."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if not isinstance(value, dict) or k not in value:
                return default
            value = value[k]
        return value

    def set(self, key: str, value: Any):
        """Set configuration value by dot-separated key."""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def is_worker_enabled(self, worker_name: str) -> bool:
        """Check if a worker is enabled."""
        return self.get(f"workers.{worker_name}.enabled", True)

    def is_search_enabled(self, method: str) -> bool:
        """Check if a search method is enabled."""
        return self.get(f"search.enabled_methods.{method}", True)

    def get_ocr_languages(self) -> List[str]:
        """Get configured OCR languages."""
        return self.get("workers.ocr.languages", ["eng"])

    def get_embedding_mode(self) -> str:
        """Get embedding mode: text-only, image-only, or text-image-hybrid."""
        return self.get("workers.embedding.mode", "text-image-hybrid")

    def get_text_embedding_config(self) -> Dict[str, Any]:
        """Get text embedding API configuration."""
        return self.get("workers.embedding.text", {})

    def get_image_embedding_config(self) -> Dict[str, Any]:
        """Get image embedding API configuration."""
        return self.get("workers.embedding.image", {})

    def get_embedding_dimension(self, embedding_type: str) -> Optional[int]:
        """Get configured embedding dimension for text or image.

        Args:
            embedding_type: 'text' or 'image'
        """
        return self.get(f"workers.embedding.{embedding_type}.dimension")

    def set_embedding_dimension(self, embedding_type: str, dimension: int):
        """Set embedding dimension after auto-detection.

        Args:
            embedding_type: 'text' or 'image'
            dimension: The detected dimension
        """
        self.set(f"workers.embedding.{embedding_type}.dimension", dimension)

    def get_search_mode_config(self, mode: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a search mode."""
        return self.get(f"search.search_modes.{mode}")

    def get_default_search_mode(self) -> str:
        """Get default search mode."""
        return self.get("search.default_search_mode", "text_hybrid")

    def get_hybrid_weights(self) -> Dict[str, float]:
        """Get hybrid search weights."""
        return self.get("workers.embedding.hybrid_weights", {
            "text_weight": 0.5,
            "image_weight": 0.5,
            "rrf_k": 60,
        })

    @property
    def screenshot_interval(self) -> int:
        return self.get("screenshot.interval_seconds", 60)


    @property
    def bm25_index_db_path(self) -> Path:
        return self.data_dir / self.get("search.bm25.db_path", "bm25_index.db")

    @property
    def retention_days(self) -> int:
        return self.get("workers.cleanup.retention_days", 7)

    @property
    def webui_host(self) -> str:
        return self.get("webui.host", "127.0.0.1")

    @property
    def webui_port(self) -> int:
        return self.get("webui.port", 8080)

    @property
    def data_dir(self) -> Path:
        return Path(self._config["data_dir"])

    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary."""
        return self._deep_copy(self._config)

    def save(self, path: Optional[Path] = None):
        """Save configuration to file."""
        if not HAS_YAML:
            raise RuntimeError("PyYAML not installed, cannot save config")

        save_path = path or self._config_path or get_config_dir() / "config.yaml"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, default_flow_style=False, sort_keys=True)

    @classmethod
    def create_default(cls, path: Optional[Path] = None) -> Path:
        """Create default configuration file."""
        if not HAS_YAML:
            raise RuntimeError("PyYAML not installed")

        config_path = path or get_config_dir() / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=True)

        return config_path
