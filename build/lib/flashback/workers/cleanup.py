"""Cleanup worker for flashback."""

import os
from pathlib import Path

from flashback.workers.base import IntervalWorker


class CleanupWorker(IntervalWorker):
    """Removes old screenshots and database entries (runs in separate process)."""

    def __init__(self, config_path=None, db_path=None):
        super().__init__(interval_seconds=3600, config_path=config_path, db_path=db_path)

    def _init_resources(self):
        """Initialize resources in child process."""
        super()._init_resources()
        self.retention_days = self.config.retention_days
        self.check_interval = self.config.get(
            "workers.cleanup.check_interval_seconds", 3600
        )
        self.interval_seconds = self.check_interval

    def run_iteration(self):
        """Clean up old records."""
        print(f"[{self.name}] Running cleanup (retention: {self.retention_days} days)")
        old_records = self.db.get_older_than(self.retention_days)

        deleted_count = 0
        for record in old_records:
            try:
                # Delete files
                for key in ["screenshot_path", "ocr_path", "embedding_path"]:
                    path_str = getattr(record, key, None)
                    if path_str:
                        path = Path(path_str)
                        if path.exists():
                            os.remove(path)
                            print(f"[{self.name}] Deleted: {path}")

                # Delete database record
                self.db.delete_record(record.timestamp)
                deleted_count += 1

            except Exception as e:
                print(f"[{self.name}] Failed to delete record {record.timestamp}: {e}")

        print(f"[{self.name}] Cleaned {deleted_count} old records")
