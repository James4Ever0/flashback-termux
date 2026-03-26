"""Screen lock detection for Linux (Xorg) and Windows."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def is_screen_locked() -> bool:
    """Detect if the screen is locked.

    Returns:
        True if screen is locked, False otherwise (or if detection fails).
    """
    try:
        return _detect_screen_lock()
    except Exception as e:
        logger.debug(f"Screen lock detection failed: {e}")
        return False


def _detect_screen_lock() -> bool:
    """Platform-specific screen lock detection."""
    import sys

    if sys.platform == "linux":
        return _detect_linux_screen_lock()
    elif sys.platform == "win32":
        return _detect_windows_screen_lock()
    elif sys.platform == "darwin":
        # macOS not supported yet
        logger.debug("Screen lock detection not implemented for macOS")
        return False
    else:
        logger.debug(f"Screen lock detection not implemented for {sys.platform}")
        return False


def _detect_linux_screen_lock() -> bool:
    """Detect screen lock on Linux (Xorg).

    Checks multiple common screen savers/lockers.
    """
    import subprocess
    import os

    locked = False

    # Check if X11 is available
    if not os.environ.get("DISPLAY"):
        logger.debug("No DISPLAY environment variable, assuming wayland or no X")
        return False

    # Try xprintidle to detect screensaver (common method)
    try:
        result = subprocess.run(
            ["xprintidle"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            # xprintidle gives idle time in milliseconds
            idle_ms = int(result.stdout.strip())
            # If idle for more than 5 minutes, screen might be locked
            # This is a heuristic, not perfect
            if idle_ms > 300000:
                logger.debug(f"Screen possibly locked due to idle time: {idle_ms}ms")
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    # Check for gnome-screensaver
    try:
        result = subprocess.run(
            ["gnome-screensaver-command", "-q"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and "The screensaver is active" in result.stdout:
            locked = True
            logger.debug("Screen locked (gnome-screensaver)")
            return locked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Check for xscreensaver
    try:
        result = subprocess.run(
            ["xscreensaver-command", "-time"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and "screen locked" in result.stdout.lower():
            locked = True
            logger.debug("Screen locked (xscreensaver)")
            return locked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Check for i3lock or similar by looking for full-screen windows
    try:
        result = subprocess.run(
            ["xwininfo", "-root", "-tree"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            output = result.stdout.lower()
            # Common lock screen window names
            lock_indicators = [
                "i3lock", "slock", "xlock", "gnome-screensaver", "kscreenlocker",
                "cinnamon-screensaver", "mate-screensaver", "xfce4-screensaver",
                "light-locker", "xsecurelock"
            ]
            for indicator in lock_indicators:
                if indicator in output:
                    locked = True
                    logger.debug(f"Screen locked (detected: {indicator})")
                    return locked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Check for loginctl show-session (systemd)
    try:
        result = subprocess.run(
            ["loginctl", "show-session", "", "-p", "LockedHint"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and "yes" in result.stdout.lower():
            locked = True
            logger.debug("Screen locked (loginctl)")
            return locked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try dbus for GNOME/Unity screensaver
    try:
        result = subprocess.run(
            [
                "dbus-send", "--session", "--dest=org.gnome.ScreenSaver",
                "--type=method_call", "--print-reply=literal",
                "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive"
            ],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            locked = True
            logger.debug("Screen locked (GNOME ScreenSaver dbus)")
            return locked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try dbus for freedesktop screensaver (KDE, etc.)
    try:
        result = subprocess.run(
            [
                "dbus-send", "--session", "--dest=org.freedesktop.ScreenSaver",
                "--type=method_call", "--print-reply=literal",
                "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver.GetActive"
            ],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            locked = True
            logger.debug("Screen locked (freedesktop ScreenSaver dbus)")
            return locked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return locked


def _detect_windows_screen_lock() -> bool:
    """Detect screen lock on Windows."""
    try:
        import ctypes
        from ctypes import wintypes

        # Check if workstation is locked using Windows API
        # WTSQuerySessionInformation can check for locked state
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Get the current desktop name
        # If it's not "Default", the screen is likely locked
        DESKTOP_READOBJECTS = 0x0001
        DESKTOP_WRITEOBJECTS = 0x0080

        try:
            # Try to use the WTS API (more reliable)
            wtsapi32 = ctypes.windll.wtsapi32
            WTS_CURRENT_SERVER_HANDLE = None
            WTS_CURRENT_SESSION = -1
            WTS_SESSIONSTATE_LOCK = 0x7  # Not officially documented but commonly used

            # WTSQuerySessionInformation is complex, use alternative approach
            pass
        except Exception:
            pass

        # Alternative: Check if screensaver is running
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD)
            ]

        # Get last input time
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        user32.GetLastInputInfo(ctypes.byref(lii))

        tick_count = kernel32.GetTickCount()
        idle_time = tick_count - lii.dwTime

        # Check if screensaver is active (indicates possible lock)
        SPI_GETSCREENSAVERRUNNING = 0x0072
        screensaver_running = wintypes.BOOL()
        user32.SystemParametersInfoW(
            SPI_GETSCREENSAVERRUNNING, 0,
            ctypes.byref(screensaver_running), 0
        )

        if screensaver_running.value:
            logger.debug("Screen possibly locked (screensaver running)")
            return True

        # Check if workstation is locked using alternative method
        # Check for existence of LogonUI.exe (lock screen process)
        import subprocess
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq LogonUI.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=2,
                shell=True
            )
            if "LogonUI.exe" in result.stdout:
                logger.debug("Screen locked (LogonUI.exe running)")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return False

    except Exception as e:
        logger.debug(f"Windows screen lock detection failed: {e}")
        return False
