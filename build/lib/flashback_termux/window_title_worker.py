"""
Termux Window Title Worker (Active App Detector)

Android app context detection using Termux-specific primitives.
Replaces PC window title detection with Android activity/app detection.
"""

import logging
import re
import subprocess
from typing import Dict, Optional, Tuple

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


def check_aapt_available() -> bool:
    """Check if aapt binary is available in PATH."""
    import shutil
    return shutil.which("aapt") is not None


def get_current_user() -> str:
    """Get the current non-root username for permission restoration."""
    result = subprocess.run(["whoami"], capture_output=True, text=True)
    return result.stdout.strip()


def fix_file_permissions(filepath: str, user: str) -> bool:
    """Change file ownership back to Termux user after su operation."""
    returncode, _, _ = run_su_command(f"chown {user}:{user} {filepath}")
    return returncode == 0


def get_active_app_info() -> Dict:
    """
    Get the currently focused app package name and activity on display 0.

    Returns:
        Dictionary with keys: package, activity, display
    """
    if not check_su_available():
        return {"package": "", "activity": "", "display": -1, "error": "su not available"}

    try:
        # Try dumpsys window first
        returncode, stdout, _ = run_su_command("dumpsys window | grep mCurrentFocus")

        if returncode == 0 and stdout:
            # Parse output like: mCurrentFocus=Window{12345678 u0 com.termux/com.termux.app.TermuxActivity}
            match = re.search(r'(\S+)/(\S+)}', stdout)
            if match:
                package = match.group(1)
                activity = match.group(2)
                if not activity.startswith('.'):
                    activity = f"{package}.{activity.split('.')[-1]}"
                return {
                    "package": package,
                    "activity": activity,
                    "display": 0
                }

        # Fallback to dumpsys activity
        returncode, stdout, _ = run_su_command("dumpsys activity activities | grep mResumedActivity")

        if returncode == 0 and stdout:
            # Parse output like: mResumedActivity: ActivityRecord{... com.termux/.app.TermuxActivity}
            match = re.search(r'(\S+)/(\.?\S+)', stdout)
            if match:
                package = match.group(1)
                activity_short = match.group(2)
                if activity_short.startswith('.'):
                    activity = f"{package}{activity_short}"
                else:
                    activity = activity_short
                return {
                    "package": package,
                    "activity": activity,
                    "display": 0
                }

        return {"package": "", "activity": "", "display": -1, "error": "parsing failed"}

    except Exception as e:
        return {"package": "", "activity": "", "display": -1, "error": str(e)}


def get_apk_name(apk_path: str) -> str:
    """
    Extract the application name from an APK file using aapt.

    Args:
        apk_path: Full path to the APK file

    Returns:
        String app name

    Raises:
        RuntimeError: If aapt not found or APK cannot be read
        ValueError: If application name not found in aapt output
    """
    import os
    import shutil
    import tempfile

    if not check_aapt_available():
        raise RuntimeError("aapt not found in PATH")

    aapt_path = shutil.which("aapt")
    user = get_current_user()

    # Wrap entire process in tempfile context manager
    with tempfile.TemporaryDirectory() as temp_dir:
        # Check if APK is readable by current user
        local_apk_path = apk_path
        needs_copy = False

        try:
            with open(apk_path, 'rb') as _:
                pass
        except (PermissionError, OSError):
            needs_copy = True

        if needs_copy:
            if not check_su_available():
                raise RuntimeError("apk in protected location and su not available")

            # Copy APK to temp directory using su
            temp_apk_path = os.path.join(temp_dir, "app.apk")
            returncode, _, stderr = run_su_command(f"cp {apk_path} {temp_apk_path}")
            if returncode != 0:
                raise RuntimeError(f"failed to copy apk: {stderr}")

            # Fix permissions so normal user can read
            returncode, _, stderr = run_su_command(f"chown {user}:{user} {temp_apk_path}")
            if returncode != 0:
                raise RuntimeError(f"failed to fix permissions: {stderr}")

            local_apk_path = temp_apk_path

        # Run aapt as normal user (NO su needed)
        result = subprocess.run(
            [aapt_path, "dump", "badging", local_apk_path],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"aapt failed: {result.stderr}")

        # Parse application-label
        label_match = re.search(r"application:\s*label='([^']*)'", result.stdout)
        if not label_match:
            label_match = re.search(r"application-label:'([^']*)'", result.stdout)

        if not label_match:
            raise ValueError("application label not found in aapt output")

        return label_match.group(1)


def get_app_name_by_id(app_id: str) -> Optional[str]:
    """
    Get the application name by its package ID using pm path and aapt.

    Args:
        app_id: Package ID string (e.g., "com.android.chrome")

    Returns:
        String app name if successful, None otherwise
    """
    if not check_su_available():
        return None

    if not check_aapt_available():
        return None

    # Use pm path to get APK path for the app_id
    returncode, stdout, _ = run_su_command(f"pm path {app_id}")
    if returncode != 0 or not stdout.strip():
        return None

    # Output format: package:/path/to/apk
    line = stdout.strip().split('\n')[0]
    if not line.startswith("package:"):
        return None

    apk_path = line[len("package:"):]

    try:
        return get_apk_name(apk_path)
    except Exception:
        return None


class TermuxWindowTitleWorker:
    """
    Active app detector for Android/Termux.

    Detects the currently active Android app and provides context for screenshots.

    Fallback hierarchy for display title:
        1. Human-readable app name (from aapt)
        2. APK ID (package name, e.g., "com.android.chrome")
        3. "Unknown" (if all detection fails)
    """

    def __init__(self):
        """
        Initialize the window title worker.

        Raises:
            RuntimeError: If su (root access) is not available
        """
        self._check_prerequisites()
        self._app_name_cache: Dict[str, Optional[str]] = {}

    def _check_prerequisites(self) -> None:
        """Verify that required prerequisites are met."""
        if not check_su_available():
            raise RuntimeError(
                "Root access (su) is required for window title worker. "
                "Please ensure your device is rooted and su is available in PATH."
            )
        logger.info("Window title worker prerequisites met (su available)")

    def get_current_context(self) -> Dict:
        """
        Get the current active app context.

        Returns:
            Dict containing:
                - app_name: Human-readable app name or None
                - app_id: Package name (e.g., "com.android.chrome")
                - display_title: Final title to use (app_name > app_id > "Unknown")
                - activity: Full activity class name
        """
        app_info = get_active_app_info()

        app_id = app_info.get("package", "")
        activity = app_info.get("activity", "")

        # Handle case where we couldn't detect anything
        if not app_id:
            logger.warning("Failed to detect active app")
            return {
                "app_name": None,
                "app_id": None,
                "display_title": "Unknown",
                "activity": None
            }

        # Try to get human-readable app name
        app_name = self._get_app_name(app_id)

        # Determine display title using fallback hierarchy:
        # 1. App name (human-readable)
        # 2. App ID (package name)
        # 3. "Unknown"
        if app_name:
            display_title = app_name
        else:
            display_title = app_id  # Use package name as fallback

        logger.debug(f"Active app context: {app_id} -> {display_title}")

        return {
            "app_name": app_name,
            "app_id": app_id,
            "display_title": display_title,
            "activity": activity
        }

    def _get_app_name(self, app_id: str) -> Optional[str]:
        """
        Get human-readable app name from package ID.

        Uses cache to avoid repeated lookups via aapt.

        Args:
            app_id: Package name (e.g., "com.android.chrome")

        Returns:
            App name string or None if lookup fails
        """
        # Check cache first
        if app_id in self._app_name_cache:
            return self._app_name_cache[app_id]

        # Try to lookup app name using primitives
        try:
            app_name = get_app_name_by_id(app_id)
            self._app_name_cache[app_id] = app_name

            if app_name:
                logger.debug(f"Resolved {app_id} -> {app_name}")
            else:
                logger.debug(f"No app name found for {app_id}, using package name")

            return app_name

        except Exception as e:
            logger.warning(f"Failed to get app name for {app_id}: {e}")
            self._app_name_cache[app_id] = None
            return None

    def clear_cache(self) -> None:
        """Clear the app name cache."""
        self._app_name_cache.clear()
        logger.debug("App name cache cleared")

    def get_cached_apps(self) -> Dict[str, Optional[str]]:
        """
        Get the current app name cache.

        Returns:
            Dict mapping app_id to app_name (may contain None values)
        """
        return self._app_name_cache.copy()
