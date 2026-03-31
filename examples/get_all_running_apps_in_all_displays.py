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
import json
import subprocess

def extract_app_from_previous_focus_line(line):
    """
    Extract the package/activity string from a line like:
    mFocusedApp=Window{... u0 com.example.app/.MainActivity}
    Returns the string or None if parsing fails.
    """
    # Remove trailing newline
    line = line.rstrip('\n')
    # Split by spaces; the app name is the last token before the '}'
    tokens = line.split()
    if len(tokens) < 3:
        return None
    last_token = tokens[-2]
    # Remove the trailing '}' if present
    if last_token.endswith('}'):
        last_token = last_token[:-1]
    return last_token



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


def parse_dumpsys_for_foreground_app(dumpsys_str):
    """
    Parse the dumpsys output and return the foreground apps with associated display IDs.

    Returns:
        list[dict[str, str]]
    """
    lines = dumpsys_str.splitlines()
    focus_lines = []
    previous_focus_lines = []
    # Find all lines containing 'mCurrentFocus'
    for idx, line in enumerate(lines):
        if 'mCurrentFocus' in line:
            focus_lines.append((idx, line))
        if 'mFocusedApp' in line:
            previous_focus_lines.append((idx, line))

    if not focus_lines:
        return []

    # For each found mCurrentFocus, try to associate it with a display
    app_by_display = []
    processed_display_ids = set()
    for idx, line in focus_lines:
        display_id = find_display_id_near_line(lines, idx)
        if display_id is not None:
            app = extract_app_from_focus_line(line)
            if not app: continue
            if display_id in processed_display_ids:
                continue
            else:
                processed_display_ids.add(display_id)
            if app:
                app_by_display.append(dict(display_id=display_id, app=app, focused=True))
    for idx, line in previous_focus_lines:
        display_id = find_display_id_near_line(lines, idx)
        if display_id is not None:
            app = extract_app_from_previous_focus_line(line)
            if not app: continue
            if display_id in processed_display_ids:
                continue
            else:
                processed_display_ids.add(display_id)
            if app:
                app_by_display.append(dict(display_id=display_id, app=app, focused=False))
    return app_by_display


def test():
    """
    Run 'su -c dumpsys window displays' and parse the output.
    Prints the result of parse_dumpsys_for_foreground_app as JSON.
    """
    try:
        result = subprocess.run(
            ["su", "-c", "dumpsys window displays"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"Error running dumpsys: {result.stderr}", file=sys.stderr)
            return
        content = result.stdout
    except Exception as e:
        print(f"Failed to run dumpsys command: {e}", file=sys.stderr)
        return

    apps = parse_dumpsys_for_foreground_app(content)
    print(json.dumps(apps, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    test()
