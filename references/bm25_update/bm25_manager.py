"""BM25 shared instance manager with background refresh.

This module provides a singleton BM25Search instance that is automatically
refreshed in the background at configurable intervals.
"""

import threading
import time
from typing import Any, Optional

from flashback.core.config import Config
from flashback.core.database import Database
from flashback.core.logger import get_logger
from flashback.search.bm25 import BM25Search


logger = get_logger("search.bm25_manager")


class BM25Manager:
    """Manages a shared BM25Search instance with background refresh.

    This ensures BM25 index is not rebuilt on every search request,
    while still periodically refreshing to include new screenshots.
    """

    _instance: Optional["BM25Manager"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "BM25Manager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[Config] = None, db: Optional[Database] = None):
        if self._initialized:
            return

        self.config = config or Config()
        self.db = db or Database(self.config.db_path)
        self._refresh_interval_seconds = self.config.get(
            "search.bm25.refresh_interval_seconds", 600
        )  # Default 10 minutes

        self._bm25_instance: Optional[BM25Search] = None
        self._last_refresh: float = 0
        self._refresh_lock = threading.RLock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._initialized = True

    def start_background_refresh(self) -> None:
        """Start the background refresh thread."""
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            logger.debug("[BM25 Manager] Background refresh already running")
            return

        self._stop_event.clear()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="BM25Refresh"
        )
        self._refresh_thread.start()
        logger.info(f"[BM25 Manager] Started BM25 background refresh (interval: {self._refresh_interval_seconds}s)")

    def stop_background_refresh(self) -> None:
        """Stop the background refresh thread."""
        self._stop_event.set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=5)
            logger.info("[BM25 Manager] Stopped BM25 background refresh")

    def _refresh_loop(self) -> None:
        """Background loop that periodically refreshes the BM25 instance."""
        while not self._stop_event.is_set():
            try:
                # Sleep in small increments to allow quick shutdown
                for _ in range(int(self._refresh_interval_seconds)):
                    if self._stop_event.is_set():
                        return
                    time.sleep(1)

                self._create_or_refresh_instance()

            except Exception as e:
                logger.exception(f"[BM25 Manager] Error in BM25 refresh loop: {e}")
                time.sleep(5)  # Back off on error

    def _create_or_refresh_instance(self) -> None:
        """Create a new BM25 instance and atomically swap it with the old one.

        This ensures queries can still use the old instance while the new one
        is being built, preventing any downtime.
        """

        start_time = time.time()

        try:
            logger.debug("[BM25 Manager] Acquiring lock for atomic operation..")
            with self._refresh_lock:
                if not self._bm25_instance:
                    logger.debug("[BM25 Manager] Starting BM25 instance creation...")
                    self._bm25_instance = BM25Search(self.config, self.db)
                    logger.debug("[BM25 Manager] BM25Search instance created in %s seconds" % (time.time() - start_time))
                else:
                    logger.debug("[BM25 Manager] Refreshing BM25 instance....")
                    self._bm25_instance.refresh()
                    logger.debug("[BM25 Manager] BM25 Instance refreshed in %s seconds" % (time.time() - start_time))
                self._last_refresh = time.time()
        except Exception as e:
            logger.exception(f"[BM25 Manager] Failed to refresh BM25 instance: {e}")
            raise

    def get_instance(self) -> Any:
        """Get the current BM25 instance, creating it if necessary.

        Returns:
            BM25Search instance (may be None if initialization failed)
        """
        # Fast path: instance already exists
        if self._bm25_instance is not None:
            return self._bm25_instance

        # Slow path: create initial instance
        with self._refresh_lock:
            if self._bm25_instance is None:
                self._create_or_refresh_instance()
                # Start background refresh after initial creation
                self.start_background_refresh()
            return self._bm25_instance

    def refresh_now(self) -> None:
        """Force an immediate refresh of the BM25 instance."""
        logger.info("[BM25 Manager] Forcing immediate BM25 refresh")
        self._create_or_refresh_instance()

    @property
    def last_refresh(self) -> float:
        """Timestamp of last successful refresh."""
        return self._last_refresh

    @property
    def age_seconds(self) -> float:
        """Age of current BM25 instance in seconds."""
        if self._last_refresh == 0:
            return float('inf')
        return time.time() - self._last_refresh


# Convenience function for getting the singleton instance
def get_bm25_manager(config: Optional[Config] = None, db: Optional[Database] = None) -> BM25Manager:
    """Get the singleton BM25Manager instance."""
    return BM25Manager(config, db)
