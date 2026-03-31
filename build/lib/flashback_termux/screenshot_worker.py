"""
Termux Screenshot Worker

Android screenshot capture using Termux-specific primitives.
Requires root access (su) for screenshot capture on Android.
"""

import os
import re
import shutil
import subprocess
import tempfile
import logging
from datetime import datetime
from typing import Optional, Tuple

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


def take_screenshot(output_path: str) -> Tuple[bool, str]:
    """
    Capture screenshot of the current display.

    Args:
        output_path: Full path where screenshot should be saved

    Returns:
        Tuple (success: bool, message: str)
    """
    if not check_su_available():
        return False, "su not available"

    temp_path = "/data/local/tmp/screenshot_temp.png"
    user = get_current_user()

    try:
        # Use screencap via su to capture screenshot
        returncode, _, stderr = run_su_command(f"/system/bin/screencap -p {temp_path}")
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
        self.output_dir = os.path.expanduser(output_dir)
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
        if not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir, exist_ok=True)
                logger.info(f"Created output directory: {self.output_dir}")
            except OSError as e:
                raise RuntimeError(f"Failed to create output directory {self.output_dir}: {e}")

        # Test writability
        test_file = os.path.join(self.output_dir, ".write_test")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
        except OSError as e:
            raise RuntimeError(f"Output directory {self.output_dir} is not writable: {e}")

    def capture(self, filename: Optional[str] = None) -> Optional[str]:
        """
        Capture a screenshot and save it to the output directory.

        Args:
            filename: Optional filename for the screenshot.
                     If not provided, auto-generates with timestamp.

        Returns:
            Full path to the saved screenshot, or None if capture failed
        """
        if filename is None:
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

        # Ensure .png extension
        if not filename.endswith('.png'):
            filename += '.png'

        output_path = os.path.join(self.output_dir, filename)

        try:
            success, message = take_screenshot(output_path)

            if success:
                logger.debug(f"Screenshot saved: {output_path}")
                return output_path
            else:
                logger.error(f"Screenshot failed: {message}")
                return None

        except Exception as e:
            logger.error(f"Exception during screenshot capture: {e}")
            return None

    def capture_with_context(self, context: dict) -> Optional[str]:
        """
        Capture a screenshot with context information in filename.

        Args:
            context: Dict containing app context (app_name, app_id, etc.)

        Returns:
            Full path to the saved screenshot, or None if capture failed
        """
        display_title = context.get('display_title', 'unknown')
        # Sanitize for filename
        safe_title = "".join(c if c.isalnum() or c in '-_' else '_' for c in display_title)

        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_title}.png"
        return self.capture(filename)
