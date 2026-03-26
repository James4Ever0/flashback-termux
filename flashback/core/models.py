"""Data models for flashback."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SearchResult:
    """Represents a search result."""
    id: int
    timestamp: float
    screenshot_path: str
    window_title: Optional[str]
    ocr_text_preview: str
    ocr_text_full: Optional[str]
    score: float
    has_embedding: bool

    @property
    def timestamp_dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)

    @property
    def timestamp_formatted(self) -> str:
        return self.timestamp_dt.isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "timestamp_formatted": self.timestamp_formatted,
            "screenshot_path": self.screenshot_path,
            "window_title": self.window_title,
            "ocr_text_preview": self.ocr_text_preview,
            "score": self.score,
            "has_embedding": self.has_embedding,
        }


@dataclass
class SystemStatus:
    """Represents system status."""
    backend_running: bool
    backend_pid: Optional[int]
    webui_running: bool
    webui_pid: Optional[int]
    screenshot_count: int
    storage_mb: float
    oldest_screenshot: Optional[float]
    newest_screenshot: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": {
                "running": self.backend_running,
                "pid": self.backend_pid,
            },
            "webui": {
                "running": self.webui_running,
                "pid": self.webui_pid,
            },
            "database": {
                "screenshot_count": self.screenshot_count,
                "storage_mb": self.storage_mb,
                "oldest_screenshot": self.oldest_screenshot,
                "newest_screenshot": self.newest_screenshot,
            },
        }
