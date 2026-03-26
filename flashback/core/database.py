"""SQLite database operations for flashback."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ScreenshotRecord:
    """Represents a screenshot record."""

    id: int
    timestamp: float
    screenshot_path: str
    ocr_path: Optional[str] = None
    embedding_path: Optional[str] = None  # Deprecated: use text_embedding_path or image_embedding_path
    window_title: Optional[str] = None
    ocr_text: Optional[str] = None
    created_at: Optional[float] = None
    text_embedding_path: Optional[str] = None
    image_embedding_path: Optional[str] = None

    @property
    def timestamp_dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp)

    @property
    def timestamp_formatted(self) -> str:
        return self.timestamp_dt.isoformat()


class Database:
    """SQLite database for screenshot metadata."""

    def __init__(self, db_path: Path, readonly:bool=False):
        self.readonly=readonly
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        """Create database connection."""
        if self.readonly:
            conn = sqlite3.connect("file:"+str(self.db_path)+"?mode=ro", uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(self.db_path, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initialize database schema."""
        with self._connect() as conn:
            # Main screenshots table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS screenshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    screenshot_path TEXT NOT NULL,
                    ocr_path TEXT,
                    embedding_path TEXT,  -- Legacy: deprecated, kept for compatibility
                    window_title TEXT,
                    ocr_text TEXT,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    text_embedding_path TEXT,
                    image_embedding_path TEXT,
                    UNIQUE(timestamp)
                )
            """
            )

            # Indexes
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON screenshots(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ocr_text ON screenshots(ocr_text)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_window_title ON screenshots(window_title)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_text_emb ON screenshots(text_embedding_path)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_image_emb ON screenshots(image_embedding_path)"
            )

            # Stats table for tracking
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0,
                    updated_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """
            )

            conn.commit()

    def insert_screenshot(self, timestamp: float, screenshot_path: str) -> int:
        """Insert a new screenshot record."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO screenshots (timestamp, screenshot_path)
                VALUES (?, ?)
                """,
                (timestamp, screenshot_path),
            )
            conn.commit()
            return cursor.lastrowid or self.get_by_timestamp(timestamp).id

    def update_ocr(self, timestamp: float, ocr_path: str, ocr_text: str):
        """Update OCR data for a screenshot."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE screenshots
                SET ocr_path = ?, ocr_text = ?
                WHERE timestamp = ?
                """,
                (ocr_path, ocr_text, timestamp),
            )
            conn.commit()

    def update_embedding(self, timestamp: float, embedding_path: str):
        """Update embedding path for a screenshot."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE screenshots
                SET embedding_path = ?
                WHERE timestamp = ?
                """,
                (embedding_path, timestamp),
            )
            conn.commit()

    def update_text_embedding(self, timestamp: float, embedding_path: Optional[str]):
        """Update text embedding path for a screenshot."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE screenshots
                SET text_embedding_path = ?
                WHERE timestamp = ?
                """,
                (embedding_path, timestamp),
            )
            conn.commit()

    def update_image_embedding(self, timestamp: float, embedding_path: Optional[str]):
        """Update image embedding path for a screenshot."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE screenshots
                SET image_embedding_path = ?
                WHERE timestamp = ?
                """,
                (embedding_path, timestamp),
            )
            conn.commit()

    def update_window_title(self, timestamp: float, window_title: str):
        """Update window title for a screenshot."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE screenshots
                SET window_title = ?
                WHERE timestamp = ?
                """,
                (window_title, timestamp),
            )
            conn.commit()

    def get_latest_without_window_title(self) -> Optional[ScreenshotRecord]:
        """Get the most recent screenshot that doesn't have a window title."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE window_title IS NULL
                ORDER BY timestamp DESC
                LIMIT 1
                """
            ).fetchone()
            return self._row_to_record(row) if row else None
    
    def get_latest(self) -> Optional[ScreenshotRecord]:
        """Get the most recent screenshot."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM screenshots
                ORDER BY timestamp DESC
                LIMIT 1
                """
            ).fetchone()
            return self._row_to_record(row) if row else None

    def get_by_timestamp(self, timestamp: float) -> Optional[ScreenshotRecord]:
        """Get screenshot by timestamp."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM screenshots WHERE timestamp = ?", (timestamp,)
            ).fetchone()
            return self._row_to_record(row) if row else None

    def get_by_id(self, record_id: int) -> Optional[ScreenshotRecord]:
        """Get screenshot by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM screenshots WHERE id = ?", (record_id,)
            ).fetchone()
            return self._row_to_record(row) if row else None

    def get_unprocessed_ocr(self, limit: int = 10) -> List[ScreenshotRecord]:
        """Get screenshots without OCR."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE ocr_path IS NULL
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_unprocessed_embeddings(self, limit: int = 10) -> List[ScreenshotRecord]:
        """Get screenshots without embeddings (for hybrid mode)."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE (text_embedding_path IS NULL OR image_embedding_path IS NULL)
                AND screenshot_path IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_unprocessed_text_embeddings(self, limit: int = 10) -> List[ScreenshotRecord]:
        """Get screenshots without text embeddings."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE text_embedding_path IS NULL
                AND ocr_text IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_unprocessed_image_embeddings(self, limit: int = 10) -> List[ScreenshotRecord]:
        """Get screenshots without image embeddings."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE image_embedding_path IS NULL
                AND screenshot_path IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_older_than(self, days: int) -> List[ScreenshotRecord]:
        """Get screenshots older than specified days."""
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM screenshots WHERE timestamp < ?", (cutoff,)
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_neighbors(
        self, timestamp: float, window_seconds: int = 300
    ) -> List[ScreenshotRecord]:
        """Get screenshots within time window of timestamp."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp
                """,
                (timestamp - window_seconds, timestamp + window_seconds),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def count_screenshots_after(self, timestamp: Optional[float] = None) -> int:
        """Count screenshots after a given timestamp (or total if None)."""
        with self._connect() as conn:
            if timestamp:
                row = conn.execute(
                    "SELECT COUNT(*) as count FROM screenshots WHERE timestamp > ?",
                    (timestamp,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as count FROM screenshots"
                ).fetchone()
            return row["count"] if row else 0

    def get_oldest_timestamp(self) -> Optional[float]:
        """Get the oldest screenshot timestamp."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(timestamp) as ts FROM screenshots"
            ).fetchone()
            return row["ts"] if row else None

    def search_by_time_range(self, start: float, end: float, limit: int = 1000):
        """Get screenshots within time range."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (start, end, limit),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_screenshots_ordered(
        self, before_time: Optional[float] = None, limit: int = 50
    ) -> List[ScreenshotRecord]:
        """Get screenshots ordered by timestamp (most recent first).

        Args:
            before_time: If provided, get screenshots before this timestamp
            limit: Maximum number of screenshots to return
        """
        with self._connect() as conn:
            if before_time:
                cursor = conn.execute(
                    """
                    SELECT * FROM screenshots
                    WHERE timestamp < ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (before_time, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM screenshots
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_screenshots_around_time(
        self, timestamp: float, count: int = 50
    ) -> List[ScreenshotRecord]:
        """Get screenshots centered around a specific timestamp.

        Returns approximately count/2 screenshots before and count/2 after.
        """
        with self._connect() as conn:
            # First try to get an equal number before and after
            half_count = count // 2

            # Get screenshots before (most recent first among those before)
            before_cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE timestamp < ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (timestamp, half_count),
            )
            before_records = [self._row_to_record(row) for row in before_cursor.fetchall()]
            before_records.reverse()  # Now in ascending order

            # Get the center screenshot (closest to timestamp)
            center_cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT 1
                """,
                (timestamp,),
            )
            center_row = center_cursor.fetchone()
            center_record = self._row_to_record(center_row) if center_row else None

            # Get screenshots after
            after_limit = half_count if center_record else count - len(before_records)
            after_cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE timestamp > ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (timestamp, after_limit),
            )
            after_records = [self._row_to_record(row) for row in after_cursor.fetchall()]

            # Combine: before + center + after
            result = before_records
            if center_record:
                result.append(center_record)
            result.extend(after_records)

            return result

    def get_all_ocr_text(self) -> List[Tuple[int, str]]:
        """Get all OCR text for indexing."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, ocr_text FROM screenshots WHERE ocr_text IS NOT NULL"
            )
            return [(row["id"], row["ocr_text"]) for row in cursor.fetchall()]

    def get_all_with_text_embeddings(self) -> List[ScreenshotRecord]:
        """Get all screenshots with text embeddings."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE text_embedding_path IS NOT NULL
                ORDER BY timestamp DESC
                """
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_all_with_image_embeddings(self) -> List[ScreenshotRecord]:
        """Get all screenshots with image embeddings."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE image_embedding_path IS NOT NULL
                ORDER BY timestamp DESC
                """
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def delete_record(self, timestamp: float):
        """Delete a screenshot record."""
        with self._connect() as conn:
            conn.execute("DELETE FROM screenshots WHERE timestamp = ?", (timestamp,))
            conn.commit()

    def get_count(self) -> int:
        """Get total screenshot count."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as count FROM screenshots").fetchone()
            return row["count"] if row else 0

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._connect() as conn:
            stats = {}

            # Total count
            row = conn.execute("SELECT COUNT(*) as count FROM screenshots").fetchone()
            stats["total"] = row["count"] if row else 0

            # With OCR
            row = conn.execute(
                "SELECT COUNT(*) as count FROM screenshots WHERE ocr_path IS NOT NULL"
            ).fetchone()
            stats["with_ocr"] = row["count"] if row else 0

            # With embeddings (legacy)
            row = conn.execute(
                "SELECT COUNT(*) as count FROM screenshots WHERE embedding_path IS NOT NULL"
            ).fetchone()
            stats["with_embedding"] = row["count"] if row else 0

            # With text embeddings
            row = conn.execute(
                "SELECT COUNT(*) as count FROM screenshots WHERE text_embedding_path IS NOT NULL"
            ).fetchone()
            stats["with_text_embedding"] = row["count"] if row else 0

            # With image embeddings
            row = conn.execute(
                "SELECT COUNT(*) as count FROM screenshots WHERE image_embedding_path IS NOT NULL"
            ).fetchone()
            stats["with_image_embedding"] = row["count"] if row else 0

            # With window title
            row = conn.execute(
                "SELECT COUNT(*) as count FROM screenshots WHERE window_title IS NOT NULL"
            ).fetchone()
            stats["with_window_title"] = row["count"] if row else 0

            # Time range
            row = conn.execute(
                "SELECT MIN(timestamp) as oldest, MAX(timestamp) as newest FROM screenshots"
            ).fetchone()
            stats["oldest_timestamp"] = row["oldest"] if row else None
            stats["newest_timestamp"] = row["newest"] if row else None

            return stats

    def search_by_window_title(
        self, title_pattern: str, limit: int = 100
    ) -> List[ScreenshotRecord]:
        """Search by window title substring."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM screenshots
                WHERE window_title LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (f"%{title_pattern}%", limit),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def _row_to_record(self, row: sqlite3.Row) -> ScreenshotRecord:
        """Convert database row to ScreenshotRecord."""
        return ScreenshotRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            screenshot_path=row["screenshot_path"],
            ocr_path=row["ocr_path"],
            embedding_path=row["embedding_path"],
            window_title=row["window_title"],
            ocr_text=row["ocr_text"],
            created_at=row["created_at"],
            text_embedding_path=row["text_embedding_path"] if "text_embedding_path" in row.keys() else None,
            image_embedding_path=row["image_embedding_path"] if "image_embedding_path" in row.keys() else None,
        )
