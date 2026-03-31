"""
Screenshot Worker for Flashback

Android screenshot capture using native Android tools via su.
Requires root access for screenshot capture on Android.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union

from flashback.workers.base import IntervalWorker

logger = logging.getLogger(__name__)


def run_su_command(command: str) -> Tuple[int, str, str]:
    """Execute a command with su privileges and return output."""
    result = subprocess.run(
        ["su", "-c", command],
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


def check_su_available() -> bool:
    """Check if su (superuser) binary is available and accessible."""
    try:
        returncode, _, _ = run_su_command("echo test")
        return returncode == 0
    except Exception:
        return False


def get_current_user() -> str:
    """Get the current non-root username for permission restoration."""
    result = subprocess.run(["whoami"], capture_output=True, text=True)
    return result.stdout.strip()


def fix_file_permissions(filepath: str, user: str) -> bool:
    """Change file ownership back to Termux user after su operation."""
    returncode, _, _ = run_su_command(f"chown {user}:{user} {filepath}")
    return returncode == 0


def take_screenshot(output_path: str, display_id: int) -> Tuple[bool, str]:
    """
    Capture screenshot of the current display.

    Args:
        output_path: Full path where screenshot should be saved
        display_id: The display id to capture

    Returns:
        Tuple (success: bool, message: str)
    """
    if not check_su_available():
        return False, "su not available"

    temp_path = "/data/local/tmp/screenshot_temp.png"
    user = get_current_user()

    try:
        # Use screencap via su to capture screenshot
        returncode, _, stderr = run_su_command(f"/system/bin/screencap -p -d {display_id} {temp_path}")
        if returncode != 0:
            return False, f"screencap failed: {stderr}"

        # Copy to output path
        returncode, _, stderr = run_su_command(f"cp {temp_path} {output_path}")
        if returncode != 0:
            return False, f"copy failed: {stderr}"

        # Fix permissions
        if not fix_file_permissions(output_path, user):
            return False, "failed to fix permissions"

        # Clean up temp file
        run_su_command(f"rm -f {temp_path}")

        return True, output_path

    except Exception as e:
        return False, f"exception: {str(e)}"


class ScreenshotWorker(IntervalWorker):
    """
    Screenshot capture worker for Termux/Android (runs in separate process).

    Uses Android's screencap binary via su to capture screenshots at regular intervals.
    Requires root access.
    """

    def __init__(self, config_path=None, db_path=None):
        # Don't initialize here - do it in _init_resources
        self._interval_seconds = None
        self._screenshot_dir = None
        self._quality = None
        super().__init__(interval_seconds=60, config_path=config_path, db_path=db_path)


    def get_target_display_id(self) -> int:
        # read config screenshot.target_display first.
        # if is "focused", then import necessary library.
        # if is "main", always return zero.
        # do lazy import.
        # fall back to 0 if cannot determine
        ret = 0
        if type(self._target_display) == int:
            ret = self._target_display
        else:
            # get current focused display id
            active_apps = self._get_active_apps_by_display()
            if not active_apps:
                current_focused_display_id = 0
            else:
                current_focused_display_id = active_apps[0]['display_id']
            ret = current_focused_display_id
        return ret

    def _read_target_display_config(self, target_display_config: Union[str, int]):
        if target_display_config == "focused":
            from flashback.workers.common.focused_display_and_apps import get_active_apps_by_display
            self._target_display = None  # Track focused display
            self._get_active_apps_by_display = get_active_apps_by_display
        elif target_display_config == "main":
            self._target_display = 0  # Track display 0
        else:
            try:
                self._target_display = int(target_display_config)
            except (ValueError, TypeError):
                raise RuntimeError("Cannot interpret screenshot.target_display config %s, must be either focused, main or an integer" % repr(target_display_config))

    def _init_resources(self):
        """Initialize resources in child process."""
        super()._init_resources()

        self._interval_seconds = self.config.get("screenshot.interval_seconds", 60)
        self.interval_seconds = self._interval_seconds
        self._quality = self.config.get("screenshot.quality", 85)
        self._screenshot_dir = self.config.screenshot_dir

        # Validate screenshot backend
        # TODO: enable scrcpy support.
        backend = self.config.get("screenshot.backend.enabled", "screencap")
        if backend != "screencap":
            raise RuntimeError(
                f"Unsupported screenshot backend: '{backend}'. "
                f"Only 'screencap' is supported on Android/Termux. "
                f"Please set screenshot.backend to 'screencap' in your config."
            )

        # Verify prerequisites
        if not check_su_available():
            raise RuntimeError(
                "Root access (su) is required for screenshot worker. "
                "Please ensure your device is rooted and su is available in PATH."
            )


        # Validate target_display compatibility with screencap backend
        # screencap can only capture display 0 (main display)
        if backend == "screencap":
            target_display_config = "main"
        elif backend == "scrcpy":
            target_display_config = self.config.get("screenshot.backend.scrcpy.target_display")
        else:
            raise RuntimeError("Unsupported screenshot backend: %s" % backend)
        self._read_target_display_config(target_display_config)
        # Ensure screenshot directory exists and is writable
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        test_file = self._screenshot_dir / ".write_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
        except OSError as e:
            raise RuntimeError(f"Screenshot directory {self._screenshot_dir} is not writable: {e}")

        self.logger.info(f"Screenshot worker initialized (interval: {self._interval_seconds}s)")

    def run_iteration(self):
        """Capture a screenshot and save to database."""
        timestamp = time.time()
        filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        output_path = self._screenshot_dir / filename

        try:
            display_id=self.get_target_display_id()
            self.logger.debug("Taking screenshot for display: %s" % display_id)
            success, message = take_screenshot(output_path=str(output_path), display_id=display_id)

            if success:
                # Insert into database
                self.db.insert_screenshot(timestamp, str(output_path))
                self.logger.debug(f"Screenshot saved: {output_path}")
            else:
                self.logger.error(f"Screenshot failed: {message}")

        except Exception as e:
            self.logger.exception(f"Exception during screenshot capture: {e}")


class TermuxScreenshotWorker:
    """
    Screenshot worker for Termux/Android environment.

    Uses Android's screencap binary via su to capture screenshots.
    Requires root access.
    """

    def __init__(self, output_dir: str):
        """
        Initialize the screenshot worker.

        Args:
            output_dir: Directory where screenshots will be saved

        Raises:
            RuntimeError: If su (root access) is not available
        """
        self.output_dir = Path(output_dir).expanduser()
        self._check_prerequisites()
        self._ensure_output_dir()

    def _check_prerequisites(self) -> None:
        """Verify that required prerequisites are met."""
        if not check_su_available():
            raise RuntimeError(
                "Root access (su) is required for Termux screenshot worker. "
                "Please ensure your device is rooted and su is available in PATH."
            )
        logger.info("Screenshot worker prerequisites met (su available)")

    def _ensure_output_dir(self) -> None:
        """Ensure output directory exists and is writable."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Test writability
        test_file = self.output_dir / ".write_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
        except OSError as e:
            raise RuntimeError(f"Output directory {self.output_dir} is not writable: {e}")

    def capture(self, filename: Optional[str] = None) -> Optional[Path]:
        """
        Capture a screenshot and save it to the output directory.

        Args:
            filename: Optional filename for the screenshot.
                     If not provided, auto-generates with timestamp.

        Returns:
            Path to the saved screenshot, or None if capture failed
        """
        if filename is None:
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

        # Ensure .png extension
        if not filename.endswith('.png'):
            filename += '.png'

        output_path = self.output_dir / filename

        try:
            success, message = take_screenshot(str(output_path))

            if success:
                logger.debug(f"Screenshot saved: {output_path}")
                return output_path
            else:
                logger.error(f"Screenshot failed: {message}")
                return None

        except Exception as e:
            logger.error(f"Exception during screenshot capture: {e}")
            return None

    def capture_with_context(self, context: dict) -> Optional[Path]:
        """
        Capture a screenshot with context information in filename.

        Args:
            context: Dict containing app context (app_name, app_id, etc.)

        Returns:
            Path to the saved screenshot, or None if capture failed
        """
        display_title = context.get('display_title', 'unknown')
        # Sanitize for filename
        safe_title = "".join(c if c.isalnum() or c in '-_' else '_' for c in display_title)

        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_title}.png"
        return self.capture(filename)
