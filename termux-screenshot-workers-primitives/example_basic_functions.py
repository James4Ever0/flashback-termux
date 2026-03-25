#!/usr/bin/env python3
"""
Termux Screenshot Workers Primitives - Basic Functions Example

This module provides basic Android automation functions for Termux environment,
including screenshot capture, active app detection, screen lock state checking,
and APK name extraction using aapt.

All operations requiring root access use 'su' command.
"""

import os
import re
import shutil
import subprocess
import tempfile


def run_su_command(command):
    """
    Execute a command with su privileges and return output.

    Args:
        command: String command to execute (will be wrapped with su -c)

    Returns:
        Tuple (returncode: int, stdout: str, stderr: str)
    """
    result = subprocess.run(
        ["su", "-c", command],
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


def check_su_available():
    """
    Check if su (superuser) binary is available and accessible.

    Returns:
        Boolean indicating su availability
    """
    try:
        returncode, _, _ = run_su_command("echo test")
        return returncode == 0
    except Exception:
        return False


def get_current_user():
    """
    Get the current non-root username for permission restoration.

    Returns:
        String username (e.g., "u0_a123")
    """
    result = subprocess.run(["whoami"], capture_output=True, text=True)
    return result.stdout.strip()


def fix_file_permissions(filepath, user):
    """
    Change file ownership back to Termux user after su operation.

    Args:
        filepath: Path to file
        user: Username from get_current_user()

    Returns:
        Boolean success status
    """
    returncode, _, _ = run_su_command(f"chown {user}:{user} {filepath}")
    return returncode == 0


def check_aapt_available():
    """
    Check if aapt binary is available in PATH.

    Returns:
        Boolean indicating aapt availability
    """
    return shutil.which("aapt") is not None


def take_screenshot(output_path):
    """
    Capture screenshot of the current display.

    Prerequisites:
        check_su_available() must return True

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


def get_active_app_info():
    """
    Get the currently focused app package name and activity on display 0.

    Prerequisites:
        check_su_available() must return True

    Returns:
        Dictionary with keys:
            - package: Package name (e.g., "com.termux")
            - activity: Full activity name (e.g., "com.termux.app.TermuxActivity")
            - display: Display ID (should be 0)
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


def get_screen_lock_state(valid_states):
    """
    Get the Android display and lock state, validating against allowed states.

    Prerequisites:
        check_su_available() must return True

    Args:
        valid_states: List of strings representing allowed states
                     (e.g., ['off_unlocked'], ['on_unlocked', 'on_locked'])
                     NO DEFAULT VALUE - caller must always provide this parameter

    Returns:
        String state name if valid

    Raises:
        ValueError: If current state not in valid_states list
        RuntimeError: If su not available or dumpsys fails
    """
    if not check_su_available():
        raise RuntimeError("su not available")

    returncode, stdout, stderr = run_su_command("dumpsys power")

    if returncode != 0:
        raise RuntimeError(f"dumpsys power failed: {stderr}")

    # Parse mHoldingWakeLockSuspendBlocker and mHoldingDisplaySuspendBlocker
    wake_lock_match = re.search(r'mHoldingWakeLockSuspendBlocker=([^\s]+)', stdout)
    display_match = re.search(r'mHoldingDisplaySuspendBlocker=([^\s]+)', stdout)

    if not wake_lock_match or not display_match:
        raise RuntimeError("failed to parse dumpsys power output")

    wake_lock = wake_lock_match.group(1).lower() == "true"
    display = display_match.group(1).lower() == "true"

    # Determine state
    if wake_lock and display:
        state = "on_unlocked"
    elif wake_lock and not display:
        state = "on_locked"
    elif not wake_lock and display:
        state = "off_unlocked"
    elif not wake_lock and not display:
        state = "off_locked"
    else:
        state = "unknown"

    # Validate against valid_states
    if state not in valid_states:
        raise ValueError(f"current state '{state}' not in valid states: {valid_states}")

    return state


def get_apk_name(apk_path):
    """
    Extract the application name from an APK file using aapt.

    Prerequisites:
        check_aapt_available() must return True

    Args:
        apk_path: Full path to the APK file (may be in root-only location like /data/app/)

    Returns:
        String app name

    Raises:
        RuntimeError: If aapt not found or APK cannot be read
        ValueError: If application name not found in aapt output
    """
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
        # Look for: application: label='App Name' or application-label:'App Name'
        label_match = re.search(r"application:\s*label='([^']*)'", result.stdout)
        if not label_match:
            label_match = re.search(r"application-label:'([^']*)'", result.stdout)

        if not label_match:
            raise ValueError("application label not found in aapt output")

        return label_match.group(1)


def get_app_name_by_id(app_id):
    """
    Get the application name by its package ID using pm path and aapt.

    Prerequisites:
        check_su_available() must return True
        check_aapt_available() must return True

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


if __name__ == "__main__":
    """Test function for all basic functions."""

    print("=" * 60)
    print("Termux Screenshot Workers Primitives - Basic Functions Test")
    print("=" * 60)

    test_results = {}

    # Step 2: Check prerequisites
    print("\n[1] Checking su availability...")
    if not check_su_available():
        print("ERROR: su not available. Root access required.")
        exit(1)
    print("OK: su is available")
    test_results["su_available"] = True

    # Step 3: Get current user
    print("\n[2] Getting current user...")
    user = get_current_user()
    print(f"OK: Current user is '{user}'")
    test_results["get_current_user"] = True

    # Step 4: Test screenshot function
    print("\n[3] Testing screenshot function...")
    output_path = f"/data/data/com.termux/files/home/test_screenshot.png"
    success, message = take_screenshot(output_path)
    if success:
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"OK: Screenshot saved to {message} ({size} bytes)")
            test_results["take_screenshot"] = True
        else:
            print(f"WARNING: Screenshot reported success but file not found")
            test_results["take_screenshot"] = False
    else:
        print(f"FAILED: {message}")
        test_results["take_screenshot"] = False

    # Step 5: Test active app detection
    print("\n[4] Testing active app detection...")
    app_info = get_active_app_info()
    if app_info.get("error"):
        print(f"FAILED: {app_info['error']}")
        test_results["get_active_app_info"] = False
    elif app_info.get("package") and app_info.get("activity"):
        print(f"OK: Package={app_info['package']}, Activity={app_info['activity']}")
        test_results["get_active_app_info"] = True
    else:
        print(f"FAILED: Empty package or activity")
        test_results["get_active_app_info"] = False

    # Step 6: Test screen lock state function
    print("\n[5] Testing screen lock state function...")
    try:
        state = get_screen_lock_state(['off_unlocked'])
        print(f"OK: Current state is '{state}'")
        test_results["get_screen_lock_state"] = True
    except ValueError as e:
        print(f"OK (state not in valid list): {e}")
        test_results["get_screen_lock_state"] = True
    except Exception as e:
        print(f"FAILED: {e}")
        test_results["get_screen_lock_state"] = False

    # Step 7: Test APK name extraction function
    print("\n[6] Testing APK name extraction function...")
    app_name = get_app_name_by_id("com.android.chrome")
    if app_name:
        print(f"OK: App name is '{app_name}' (for com.android.chrome)")
        test_results["get_apk_name"] = True
    else:
        print("FAILED: Could not get app name for com.android.chrome")
        test_results["get_apk_name"] = False

    # Step 8: Cleanup
    print("\n[7] Cleanup...")
    if os.path.exists(output_path):
        os.remove(output_path)
        print(f"OK: Removed test screenshot")

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for test_name, result in test_results.items():
        status = "PASS" if result == True else ("SKIP" if result is None else "FAIL")
        print(f"  {test_name}: {status}")

    # Exit with appropriate code
    if all(r == True for r in test_results.values() if r is not None):
        print("\nAll tests passed!")
        exit(0)
    else:
        print("\nSome tests failed!")
        exit(1)
