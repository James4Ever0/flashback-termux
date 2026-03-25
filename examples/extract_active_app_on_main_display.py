#!/usr/bin/env python3
"""
Extract the foreground app for a specific display from the output of
'dumpsys window displays'.

The algorithm:
1. Split the output into lines.
2. Find all lines containing "mCurrentFocus".
3. For each such line, look within up to 5 lines above and below for a line
   that contains "displayId=" or "mDisplayId=". Use the first (nearest) match.
4. If a display ID is found, associate the app name (extracted from the
   mCurrentFocus line) with that display.
5. Return the app name for the requested display ID.

If no mCurrentFocus line is found, or the requested display is not found,
return None.
"""

import re
import sys


def extract_app_from_focus_line(line):
    """
    Extract the package/activity string from a line like:
    mCurrentFocus=Window{... u0 com.example.app/.MainActivity}
    Returns the string or None if parsing fails.
    """
    # Remove trailing newline
    line = line.rstrip('\n')
    # Split by spaces; the app name is the last token before the '}'
    tokens = line.split()
    if len(tokens) < 3:
        return None
    last_token = tokens[-1]
    # Remove the trailing '}' if present
    if last_token.endswith('}'):
        last_token = last_token[:-1]
    return last_token


def find_display_id_near_line(lines, line_idx, max_offset=5):
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
        # Match both formats: displayId=0 or mDisplayId=0
        match = re.search(r'(?:displayId|mDisplayId)=(\d+)', line)
        if match:
            return int(match.group(1))
    return None


def parse_dumpsys_for_foreground_app(dumpsys_str, target_display_id=0):
    """
    Parse the dumpsys output and return the foreground app for the given
    display ID.

    Returns:
        str: The package/activity string, or None if not found.
    """
    lines = dumpsys_str.splitlines()
    focus_lines = []
    # Find all lines containing 'mCurrentFocus'
    for idx, line in enumerate(lines):
        if 'mCurrentFocus' in line:
            focus_lines.append((idx, line))

    if not focus_lines:
        return None

    # For each found mCurrentFocus, try to associate it with a display
    app_by_display = {}
    for idx, line in focus_lines:
        display_id = find_display_id_near_line(lines, idx)
        if display_id is not None:
            app = extract_app_from_focus_line(line)
            if app:
                app_by_display[display_id] = app

    # Return the app for the requested display
    return app_by_display.get(target_display_id)


def test():
    """
    Read a sample dumpsys output from a file and test the parser.
    Expects a file named 'sample_dumpsys.txt' in the current directory.
    """
    filename = 'dumpsys_displays.txt'
    try:
        with open(filename, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Test file '{filename}' not found. Please create one with the output of 'adb shell dumpsys window displays'.")
        return

    print(f"Parsing file: {filename}")
    app = parse_dumpsys_for_foreground_app(content, target_display_id=0)
    if app:
        print(f"Foreground app on display 0: {app}")
        # Foreground app on display 0: fr.neamar.kiss/fr.neamar.kiss.MainActivity
        app_id = app.split("/")[0]
        print("App id:", app_id)
    else:
        print("No foreground app found for display 0.")


if __name__ == "__main__":
    test()
