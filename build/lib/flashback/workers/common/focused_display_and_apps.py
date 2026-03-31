"""
Window Title Worker for Flashback (Active App Detector)

Android app context detection using native Android tools.
Replaces PC window title detection with Android activity/app detection.
Supports display-aware app tracking for multi-display scenarios.
"""

import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple

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


def check_aapt_available() -> bool:
    """Check if aapt binary is available in PATH."""
    import shutil
    return shutil.which("aapt") is not None


def get_current_user() -> str:
    """Get the current non-root username for permission restoration."""
    result = subprocess.run(["whoami"], capture_output=True, text=True)
    return result.stdout.strip()


def extract_app_from_focus_line(line: str) -> Optional[str]:
    """
    Extract the package/activity string from a line like:
    mCurrentFocus=Window{... u0 com.example.app/.MainActivity}
    Returns the string or None if parsing fails.
    """
    line = line.rstrip('\n')
    tokens = line.split()
    if len(tokens) < 3:
        return None
    last_token = tokens[-1]
    if last_token.endswith('}'):
        last_token = last_token[:-1]
    return last_token


def extract_app_from_focused_app_line(line: str) -> Optional[str]:
    """
    Extract the package/activity string from a line like:
    mFocusedApp=Window{... u0 com.example.app/.MainActivity}
    Returns the string or None if parsing fails.
    """
    line = line.rstrip('\n')
    tokens = line.split()
    if len(tokens) < 3:
        return None
    last_token = tokens[-2]
    if last_token.endswith('}'):
        last_token = last_token[:-1]
    return last_token


def find_display_id_near_line(lines: List[str], line_idx: int, max_offset: int = 5) -> Optional[int]:
    """
    Look for lines containing 'displayId=' or 'mDisplayId=' within
    line_idx ± max_offset. Return the first found display ID as an integer,
    or None if not found.
    """
    start = max(0, line_idx - max_offset)
    end = min(len(lines), line_idx + max_offset + 1)

    for i in range(start, end):
        if i == line_idx:
            continue
        line = lines[i]
        match = re.search(r'(?:displayId|mDisplayId)=(\d+)', line)
        if match:
            return int(match.group(1))
    return None


def get_active_apps_by_display() -> List[Dict]:
    """
    Get all active apps with their associated display IDs.
    Uses 'dumpsys window displays' to parse display-aware app information.

    Returns:
        List of dicts with keys: display_id, app (package/activity), focused
        The first entry (index 0) is typically the currently focused display.
    """
    if not check_su_available():
        return []

    try:
        # Get full dumpsys window output for parsing
        returncode, stdout, _ = run_su_command("dumpsys window displays")
        if returncode != 0 or not stdout:
            return []

        lines = stdout.splitlines()
        apps_by_display = []
        processed_display_ids = set()

        # First pass: find mCurrentFocus lines (these indicate focused apps)
        for idx, line in enumerate(lines):
            if 'mCurrentFocus' in line and 'null' not in line:
                display_id = find_display_id_near_line(lines, idx)
                if display_id is not None:
                    app = extract_app_from_focus_line(line)
                    if app and display_id not in processed_display_ids:
                        processed_display_ids.add(display_id)
                        apps_by_display.append({
                            "display_id": display_id,
                            "app": app,
                            "focused": True
                        })

        # Second pass: find mFocusedApp lines (these indicate other active apps)
        for idx, line in enumerate(lines):
            if 'mFocusedApp' in line and 'null' not in line:
                display_id = find_display_id_near_line(lines, idx)
                if display_id is not None and display_id not in processed_display_ids:
                    app = extract_app_from_focused_app_line(line)
                    if app:
                        processed_display_ids.add(display_id)
                        apps_by_display.append({
                            "display_id": display_id,
                            "app": app,
                            "focused": False
                        })

        # Sort: focused apps first, then by display_id
        apps_by_display.sort(key=lambda x: (not x["focused"], x["display_id"]))
        return apps_by_display

    except Exception as e:
        logger.warning(f"Error parsing dumpsys for active apps: {e}")
        return []


def get_active_app_info(target_display: int = 0) -> Dict:
    """
    Get the active app package name and activity on the specified display.

    Args:
        target_display: Display ID to get app info for (default: 0)

    Returns:
        Dictionary with keys: package, activity, display, focused
    """
    if not check_su_available():
        return {"package": "", "activity": "", "display": -1, "focused": False, "error": "su not available"}

    try:
        apps = get_active_apps_by_display()

        # Find the app for the target display
        for app_info in apps:
            if app_info["display_id"] == target_display:
                app_str = app_info["app"]
                parts = app_str.split('/')
                package = parts[0]
                activity = parts[1] if len(parts) > 1 else ""

                # Handle short activity names
                if activity and not activity.startswith('.'):
                    activity = f"{package}.{activity.split('.')[-1]}"
                elif activity.startswith('.'):
                    activity = f"{package}{activity}"

                return {
                    "package": package,
                    "activity": activity,
                    "display": target_display,
                    "focused": app_info.get("focused", False)
                }

        # Fallback: if target display not found, return first available (usually focused)
        if apps:
            app_info = apps[0]
            app_str = app_info["app"]
            parts = app_str.split('/')
            package = parts[0]
            activity = parts[1] if len(parts) > 1 else ""

            if activity and not activity.startswith('.'):
                activity = f"{package}.{activity.split('.')[-1]}"
            elif activity.startswith('.'):
                activity = f"{package}{activity}"

            return {
                "package": package,
                "activity": activity,
                "display": app_info["display_id"],
                "focused": app_info.get("focused", False)
            }

        return {"package": "", "activity": "", "display": -1, "focused": False, "error": "no apps found"}

    except Exception as e:
        return {"package": "", "activity": "", "display": -1, "focused": False, "error": str(e)}


def get_current_focused_display() -> int:
    """
    Get the currently focused display ID.

    Returns:
        Display ID (int), or -1 if not found
    """
    apps = get_active_apps_by_display()
    if apps:
        # First app is typically the focused one (sorted by focused=True first)
        return apps[0].get("display_id", 0)
    return 0  # Default to display 0


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
    import shutil

    if not check_aapt_available():
        raise RuntimeError("aapt not found in PATH")

    aapt_path = shutil.which("aapt")
    user = get_current_user()

    with tempfile.TemporaryDirectory() as temp_dir:
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

            temp_apk_path = os.path.join(temp_dir, "app.apk")
            returncode, _, stderr = run_su_command(f"cp {apk_path} {temp_apk_path}")
            if returncode != 0:
                raise RuntimeError(f"failed to copy apk: {stderr}")

            returncode, _, stderr = run_su_command(f"chown {user}:{user} {temp_apk_path}")
            if returncode != 0:
                raise RuntimeError(f"failed to fix permissions: {stderr}")

            local_apk_path = temp_apk_path

        result = subprocess.run(
            [aapt_path, "dump", "badging", local_apk_path],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"aapt failed: {result.stderr}")

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

    returncode, stdout, _ = run_su_command(f"pm path {app_id}")
    if returncode != 0 or not stdout.strip():
        return None

    line = stdout.strip().split('\n')[0]
    if not line.startswith("package:"):
        return None

    apk_path = line[len("package:"):]

    try:
        return get_apk_name(apk_path)
    except Exception:
        return None


class WindowTitleWorker(IntervalWorker):
    """
    Active app detector for Android/Termux (runs in separate process).

    Polls for the currently active Android apps on all displays and associates
    them with recently captured screenshots. Supports display-aware tracking
    and historical app name inference for display 0.

    Fallback hierarchy for display title:
        1. Human-readable app name (from aapt)
        2. Historical app name from cache (for display 0)
        3. APK ID (package name, e.g., "com.android.chrome")
        4. "Unknown" (if all detection fails)
    """

    def __init__(self, config_path=None, db_path=None):
        self._poll_interval = None
        self._max_screenshot_age = None
        self._target_display = None  # None = use focused display, 0+ = specific display
        self._app_name_cache: Dict[str, Optional[str]] = {}
        self._display_app_history: Dict[int, Dict[str, str]] = {}  # display_id -> {app_id -> app_name}
        self._last_context = None
        super().__init__(interval_seconds=1, config_path=config_path, db_path=db_path)

    def _init_resources(self):
        """Initialize resources in child process."""
        super()._init_resources()

        self._poll_interval = self.config.get("workers.window_title.poll_interval_seconds", 1)
        self._max_screenshot_age = self.config.get(
            "workers.window_title.max_screenshot_age_seconds", 30
        )
        self.interval_seconds = self._poll_interval

        # Config for screenshot target display
        # Options: "focused" (current focused display), "main" (display 0) or specific number (e.g., 0)
        # TODO: add option "all" to capture all displays, and sync with screenshot worker as well with this option.
        target_display_config = self.config.get("screenshot.target_display", "focused")
        if target_display_config == "focused":
            self._target_display = None  # Track focused display
        elif target_display_config == "main":
            self._target_display = 0  # Track display 0
        else:
            try:
                self._target_display = int(target_display_config)
            except (ValueError, TypeError):
                raise RuntimeError("Cannot interpret screenshot.target_display config %s, must be either focused, main or an integer" % repr(target_display_config))

        if not check_su_available():
            raise RuntimeError(
                "Root access (su) is required for window title worker. "
                "Please ensure your device is rooted and su is available in PATH."
            )

        self.logger.info(
            f"Window title worker initialized "
            f"(interval: {self._poll_interval}s, max_age: {self._max_screenshot_age}s, "
            f"target_display: {target_display_config})"
        )

    def run_iteration(self):
        """Get current app context and associate with recent screenshot."""
        try:
            # Get all active apps by display
            apps_by_display = get_active_apps_by_display()

            if not apps_by_display:
                self.logger.debug("No active apps detected")
                return

            # Determine which display(s) to track
            if self._target_display == -1:
                # Track all displays
                displays_to_track = [app["display_id"] for app in apps_by_display]
            elif self._target_display is None:
                # Track focused display (first in sorted list)
                displays_to_track = [apps_by_display[0]["display_id"]]
            else:
                # Track specific display if it has an active app
                displays_to_track = [self._target_display] if any(
                    app["display_id"] == self._target_display for app in apps_by_display
                ) else [apps_by_display[0]["display_id"]]

            # Process each target display
            for display_id in displays_to_track:
                self._process_display(display_id, apps_by_display)

        except Exception as e:
            self.logger.exception(f"Error in window title worker: {e}")

    def _process_display(self, display_id: int, apps_by_display: List[Dict]):
        """Process a specific display and update screenshot metadata."""
        # Find app for this display
        app_info = None
        for app in apps_by_display:
            if app["display_id"] == display_id:
                app_info = app
                break

        if not app_info:
            return

        # Parse app string (package/activity)
        app_str = app_info["app"]
        parts = app_str.split('/')
        app_id = parts[0]

        # Get context with historical inference for display 0
        context = self._get_context_for_app(app_id, display_id)
        self._last_context = context

        display_title = context.get("display_title", "Unknown")

        # Find recent screenshots without window title
        recent_screenshot = self.db.get_latest_without_window_title()

        if not recent_screenshot:
            return

        # Check if screenshot is within the time window
        age_seconds = time.time() - recent_screenshot.timestamp
        if age_seconds > self._max_screenshot_age:
            self.logger.debug(
                f"Screenshot too old ({age_seconds:.1f}s), skipping window title update"
            )
            return

        # Update the screenshot with window title
        self.db.update_window_title(recent_screenshot.timestamp, display_title)
        self.logger.info(
            f"Updated screenshot {recent_screenshot.timestamp} with window title: {display_title} "
            f"(display: {display_id})"
        )

    def _get_context_for_app(self, app_id: str, display_id: int) -> Dict:
        """
        Get context for an app, with historical inference for display 0.

        Args:
            app_id: Package ID
            display_id: Display ID

        Returns:
            Dict with app context including display_title
        """
        activity = ""  # We don't have separate activity info in this flow

        if not app_id:
            return {
                "app_name": None,
                "app_id": None,
                "display_title": "Unknown",
                "activity": None,
                "display_id": display_id
            }

        # Try to get human-readable app name
        app_name = self._get_app_name(app_id)

        # For display 0: update historical cache and use it for inference
        if display_id == 0:
            if app_name:
                # Update historical cache when we have a valid app name
                if display_id not in self._display_app_history:
                    self._display_app_history[display_id] = {}
                self._display_app_history[display_id][app_id] = app_name
                self.logger.debug(f"Updated historical cache for display 0: {app_id} -> {app_name}")
            else:
                # Try to infer from historical cache
                if display_id in self._display_app_history:
                    historical_name = self._display_app_history[display_id].get(app_id)
                    if historical_name:
                        app_name = historical_name
                        self.logger.debug(f"Inferred app name for display 0 from history: {app_id} -> {app_name}")

        # Determine display title using fallback hierarchy:
        # 1. App name (human-readable or historical for display 0)
        # 2. App ID (package name)
        # 3. "Unknown"
        if app_name:
            display_title = app_name
        else:
            display_title = app_id

        self.logger.debug(f"Active app context (display {display_id}): {app_id} -> {display_title}")

        return {
            "app_name": app_name,
            "app_id": app_id,
            "display_title": display_title,
            "activity": activity,
            "display_id": display_id
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
        if app_id in self._app_name_cache:
            return self._app_name_cache[app_id]

        try:
            app_name = get_app_name_by_id(app_id)
            self._app_name_cache[app_id] = app_name

            if app_name:
                self.logger.debug(f"Resolved {app_id} -> {app_name}")
            else:
                self.logger.debug(f"No app name found for {app_id}, using package name")

            return app_name

        except Exception as e:
            self.logger.warning(f"Failed to get app name for {app_id}: {e}")
            self._app_name_cache[app_id] = None
            return None

    def clear_cache(self) -> None:
        """Clear the app name cache."""
        self._app_name_cache.clear()
        self._display_app_history.clear()
        self.logger.debug("App name cache and display history cleared")

    def get_cached_apps(self) -> Dict[str, Optional[str]]:
        """
        Get the current app name cache.

        Returns:
            Dict mapping app_id to app_name (may contain None values)
        """
        return self._app_name_cache.copy()

    def get_display_history(self) -> Dict[int, Dict[str, str]]:
        """
        Get the display app history.

        Returns:
            Dict mapping display_id to {app_id: app_name}
        """
        return {k: v.copy() for k, v in self._display_app_history.items()}


class TermuxWindowTitleWorker:
    """
    Active app detector for Android/Termux.

    Detects the currently active Android app and provides context for screenshots.

    Fallback hierarchy for display title:
        1. Human-readable app name (from aapt)
        2. Historical app name from cache (for display 0)
        3. APK ID (package name, e.g., "com.android.chrome")
        4. "Unknown" (if all detection fails)
    """

    def __init__(self):
        self._check_prerequisites()
        self._app_name_cache: Dict[str, Optional[str]] = {}
        self._display_app_history: Dict[int, Dict[str, str]] = {}

    def _check_prerequisites(self) -> None:
        """Verify that required prerequisites are met."""
        if not check_su_available():
            raise RuntimeError(
                "Root access (su) is required for window title worker. "
                "Please ensure your device is rooted and su is available in PATH."
            )
        logger.info("Window title worker prerequisites met (su available)")

    def get_current_context(self, target_display: int = 0) -> Dict:
        """
        Get the current active app context for a specific display.

        Args:
            target_display: Display ID to get context for (default: 0)

        Returns:
            Dict containing:
                - app_name: Human-readable app name or None
                - app_id: Package name (e.g., "com.android.chrome")
                - display_title: Final title to use
                - activity: Full activity class name
                - display_id: Display ID
        """
        app_info = get_active_app_info(target_display)

        app_id = app_info.get("package", "")
        activity = app_info.get("activity", "")
        display_id = app_info.get("display", target_display)

        if not app_id:
            logger.warning(f"Failed to detect active app on display {target_display}")
            return {
                "app_name": None,
                "app_id": None,
                "display_title": "Unknown",
                "activity": None,
                "display_id": display_id
            }

        app_name = self._get_app_name(app_id)

        # For display 0: update historical cache and use it for inference
        if display_id == 0:
            if app_name:
                if display_id not in self._display_app_history:
                    self._display_app_history[display_id] = {}
                self._display_app_history[display_id][app_id] = app_name
            else:
                if display_id in self._display_app_history:
                    historical_name = self._display_app_history[display_id].get(app_id)
                    if historical_name:
                        app_name = historical_name

        if app_name:
            display_title = app_name
        else:
            display_title = app_id

        logger.debug(f"Active app context (display {display_id}): {app_id} -> {display_title}")

        return {
            "app_name": app_name,
            "app_id": app_id,
            "display_title": display_title,
            "activity": activity,
            "display_id": display_id
        }

    def _get_app_name(self, app_id: str) -> Optional[str]:
        """Get human-readable app name from package ID."""
        if app_id in self._app_name_cache:
            return self._app_name_cache[app_id]

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

    def get_active_apps_all_displays(self) -> List[Dict]:
        """
        Get active apps on all displays.

        Returns:
            List of dicts with display_id, app, focused status
        """
        return get_active_apps_by_display()

    def get_current_focused_display(self) -> int:
        """Get the currently focused display ID."""
        return get_current_focused_display()

    def clear_cache(self) -> None:
        """Clear the app name cache."""
        self._app_name_cache.clear()
        self._display_app_history.clear()
        logger.debug("App name cache and display history cleared")

    def get_cached_apps(self) -> Dict[str, Optional[str]]:
        """Get the current app name cache."""
        return self._app_name_cache.copy()
