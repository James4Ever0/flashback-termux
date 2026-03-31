"""Base worker class for flashback."""

import logging
import multiprocessing
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from flashback.core.logger import get_logger


class BaseWorker(multiprocessing.Process, ABC):
    """Base class for all background workers (runs in separate process)."""

    def __init__(self, config_path: Optional[str] = None, db_path: Optional[str] = None):
        super().__init__(daemon=True)
        self.config_path = config_path
        self.db_path = db_path
        self._stop_event = multiprocessing.Event()
        self.worker_name = self.__class__.__name__

    def stop(self):
        """Signal the worker to stop."""
        self._stop_event.set()

    def should_stop(self, timeout: Optional[float] = None) -> bool:
        """Check if stop has been requested."""
        return self._stop_event.wait(timeout=timeout)

    def _init_resources(self):
        """Initialize resources that can't be pickled (called in child process)."""
        from flashback.core.config import Config
        from flashback.core.database import Database

        self.config = Config(config_path=self.config_path)
        self.db = Database(self.db_path or self.config.db_path)
        self.running = False
        self.logger = get_logger(f"workers.{self.worker_name.lower()}")

    @abstractmethod
    def run_iteration(self):
        """Perform one iteration of work. Override in subclasses."""
        pass

    def run(self):
        """Main worker loop (runs in child process)."""
        # Initialize resources in child process (can't pickle Config/Database)
        self._init_resources()

        self.running = True
        self.logger.info(f"Started {self.worker_name}")

        iteration = 0
        while self.running:
            if self._stop_event.is_set():
                break

            iteration += 1
            if iteration % 10 == 0:
                self.logger.debug(f"Running iteration {iteration}")

            try:
                self.run_iteration()
            except Exception as e:
                self.logger.exception(f"Error in iteration {iteration}: {e}")
                time.sleep(5)  # Back off on error

        self.logger.info(f"Stopped {self.worker_name}")

    def get_sleep_interval(self) -> float:
        """Get the sleep interval between iterations. Override in subclasses."""
        return 1.0


class IntervalWorker(BaseWorker, ABC):
    """Worker that runs at fixed intervals."""

    def __init__(self, interval_seconds: float, config_path: Optional[str] = None, db_path: Optional[str] = None):
        super().__init__(config_path=config_path, db_path=db_path)
        self.interval_seconds = interval_seconds

    def run(self):
        """Main worker loop with interval timing (runs in child process)."""
        # Initialize resources in child process
        self._init_resources()

        self.running = True
        self.logger.info(f"Started {self.worker_name} (interval: {self.interval_seconds}s)")

        iteration = 0
        while self.running:
            if self._stop_event.is_set():
                break

            iteration += 1
            start_time = time.time()

            try:
                if self.logger.isEnabledFor(logging.DEBUG) and iteration % 10 == 0:
                    self.logger.debug(f"Iteration {iteration}")
                self.run_iteration()
            except Exception as e:
                self.logger.exception(f"Error in iteration {iteration}: {e}")

            # Sleep until next interval
            elapsed = time.time() - start_time
            sleep_time = max(0, self.interval_seconds - elapsed)

            if sleep_time > 0 and self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Sleeping for {sleep_time:.2f}s")

            if self._stop_event.wait(timeout=sleep_time):
                break

        self.logger.info(f"Stopped {self.worker_name}")


class QueueWorker(BaseWorker, ABC):
    """Worker that processes items from a queue."""

    def __init__(self, poll_interval: float = 1.0, batch_size: int = 1, config_path: Optional[str] = None, db_path: Optional[str] = None):
        super().__init__(config_path=config_path, db_path=db_path)
        self.poll_interval = poll_interval
        self.batch_size = batch_size

    def run_iteration(self):
        """Not used by QueueWorker - it overrides run() instead."""
        # This dummy implementation satisfies the abstract base class requirement.
        # QueueWorker uses get_items() and process_item() instead.
        pass

    def run(self):
        """Main worker loop for queue processing (runs in child process)."""
        # Initialize resources in child process
        self._init_resources()

        self.running = True
        self.logger.info(f"Started {self.worker_name} (poll: {self.poll_interval}s, batch: {self.batch_size})")

        iteration = 0
        while self.running:
            if self._stop_event.is_set():
                break

            iteration += 1
            try:
                self.logger.debug(f"Fetching items (iteration {iteration})")
                items = self.get_items()

                if not items:
                    self.logger.debug("No items, waiting...")
                    if self._stop_event.wait(timeout=self.poll_interval):
                        break
                    continue

                self.logger.debug(f"Processing {len(items)} items")
                for i, item in enumerate(items[: self.batch_size]):
                    if self._stop_event.is_set():
                        break
                    try:
                        self.logger.debug(f"Processing item {i+1}/{min(len(items), self.batch_size)}")
                        self.process_item(item)
                    except Exception as e:
                        self.logger.exception(f"Failed to process item {i}: {e}")

            except Exception as e:
                self.logger.exception(f"Error in iteration {iteration}: {e}")
                time.sleep(5)

        self.logger.info(f"Stopped {self.worker_name}")

    @abstractmethod
    def get_items(self) -> list:
        """Get items to process. Override in subclasses."""
        return []

    @abstractmethod
    def process_item(self, item: Any):
        """Process a single item. Override in subclasses."""
        pass
