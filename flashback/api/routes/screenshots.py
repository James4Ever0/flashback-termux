"""Screenshot endpoints."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, jsonify, send_file, request

from flashback.core.database import Database

bp = Blueprint('screenshots', __name__)


def _record_to_dict(record, include_full_text: bool = False) -> Dict[str, Any]:
    """Convert ScreenshotRecord to dict."""
    preview = ""
    if record.ocr_text:
        preview = record.ocr_text[:200] + "..." if len(record.ocr_text) > 200 else record.ocr_text

    result = {
        "id": record.id,
        "timestamp": record.timestamp,
        "timestamp_formatted": record.timestamp_formatted,
        "screenshot_path": record.screenshot_path,
        "screenshot_url": f"/screenshots/{Path(record.screenshot_path).name}",
        "window_title": record.window_title,
        "ocr_text_preview": preview,
        "has_embedding": record.embedding_path is not None,
    }

    if include_full_text and record.ocr_text:
        result["ocr_text_full"] = record.ocr_text

    return result


def _error_response(message: str, status_code: int = 400):
    """Create error response."""
    response = jsonify({"error": message})
    response.status_code = status_code
    return response


@bp.get("/screenshots")
def list_screenshots() -> Dict[str, Any]:
    """List screenshots with filtering."""
    db: Database = current_app.config['FLASHBACK_DB']

    # Parse query parameters
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    window_title = request.args.get('window_title')
    has_ocr = request.args.get('has_ocr')
    has_embedding = request.args.get('has_embedding')
    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))

    # Clamp limit to valid range
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    # Parse time range
    start_ts = None
    end_ts = None

    if from_date:
        try:
            start_ts = datetime.fromisoformat(from_date).timestamp()
        except ValueError:
            return _error_response(f"Invalid from date: {from_date}")

    if to_date:
        try:
            end_ts = datetime.fromisoformat(to_date).timestamp()
        except ValueError:
            return _error_response(f"Invalid to date: {to_date}")

    # Get records
    if start_ts or end_ts:
        start_ts = start_ts or 0
        end_ts = end_ts or datetime.now().timestamp()
        records = db.search_by_time_range(start_ts, end_ts, limit=limit + offset)
    else:
        # Get all screenshots (limited)
        records = db.get_unprocessed_ocr(limit=limit + offset)

    # Apply filters
    filtered = []
    for record in records:
        if window_title and (not record.window_title or window_title.lower() not in record.window_title.lower()):
            continue
        if has_ocr is not None:
            has_ocr_bool = has_ocr.lower() == 'true'
            has_ocr_data = record.ocr_path is not None
            if has_ocr_bool != has_ocr_data:
                continue
        if has_embedding is not None:
            has_emb_bool = has_embedding.lower() == 'true'
            has_emb_data = record.embedding_path is not None
            if has_emb_bool != has_emb_data:
                continue
        filtered.append(record)

    total = len(filtered)
    results = filtered[offset:offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": [_record_to_dict(r) for r in results],
    }


@bp.get("/screenshots/timeline")
def list_screenshots_timeline() -> Dict[str, Any]:
    """List screenshots ordered by time (most recent first) for timeline browsing."""
    db: Database = current_app.config['FLASHBACK_DB']

    # Parse query parameters
    before_time_str = request.args.get('before_time')
    around_time_str = request.args.get('around_time')
    window_title = request.args.get('window_title')
    limit = int(request.args.get('limit', 50))

    # Clamp limit to valid range
    limit = max(1, min(100, limit))

    before_time = float(before_time_str) if before_time_str else None
    around_time = float(around_time_str) if around_time_str else None

    if around_time:
        # Get screenshots centered around a specific time
        records = db.get_screenshots_around_time(around_time, count=limit)
        # Get total count for reference
        total = db.count_screenshots_after()
        # Determine the time range displayed
        if records:
            time_from = min(r.timestamp for r in records)
            time_to = max(r.timestamp for r in records)
        else:
            time_from = time_to = around_time
    elif before_time:
        # Get screenshots before a specific time (pagination)
        records = db.get_screenshots_ordered(before_time=before_time, limit=limit)
        total = db.count_screenshots_after()
        if records:
            time_from = min(r.timestamp for r in records)
            time_to = max(r.timestamp for r in records)
        else:
            time_from = time_to = before_time
    else:
        # Get most recent screenshots
        records = db.get_screenshots_ordered(limit=limit)
        total = db.count_screenshots_after()
        if records:
            time_from = min(r.timestamp for r in records)
            time_to = max(r.timestamp for r in records)
        else:
            time_from = time_to = None

    # Apply window title filter if provided
    if window_title:
        records = [r for r in records if r.window_title and window_title.lower() in r.window_title.lower()]

    # Get oldest timestamp for reference
    oldest_ts = db.get_oldest_timestamp()

    return {
        "total": total,
        "limit": limit,
        "time_from": time_from,
        "time_to": time_to,
        "oldest_timestamp": oldest_ts,
        "results": [_record_to_dict(r) for r in records],
    }


@bp.get("/screenshots/timeline/jump")
def jump_to_time() -> Dict[str, Any]:
    """Jump to a specific time point and get nearby screenshots."""
    db: Database = current_app.config['FLASHBACK_DB']

    # Parse query parameters
    time_str = request.args.get('time')
    count = int(request.args.get('count', 50))

    if not time_str:
        return _error_response("Time parameter is required")

    try:
        time_val = float(time_str)
    except ValueError:
        return _error_response(f"Invalid time: {time_str}")

    count = max(1, min(100, count))

    records = db.get_screenshots_around_time(time_val, count=count)

    if not records:
        return _error_response("No screenshots found near the specified time", 404)

    time_from = min(r.timestamp for r in records)
    time_to = max(r.timestamp for r in records)

    return {
        "jump_time": time_val,
        "count": len(records),
        "time_from": time_from,
        "time_to": time_to,
        "results": [_record_to_dict(r) for r in records],
    }


@bp.get("/screenshots/now")
def get_latest_screenshot():
    """Get the latest screenshot as a file response."""
    import time

    db: Database = current_app.config['FLASHBACK_DB']
    config = current_app.config['FLASHBACK_CONFIG']
    latest = db.get_latest()
    if not latest:
        return _error_response("No screenshots found", 404)

    # Check age limit
    age_limit_seconds = config.get("webui.latest_screenshot_age_limit_seconds", 120)
    age_seconds = time.time() - latest.timestamp
    if age_seconds > age_limit_seconds:
        return _error_response(
            f"Latest screenshot is {age_seconds:.0f}s old (limit: {age_limit_seconds}s)",
            404
        )

    return send_file(latest.screenshot_path)


@bp.get("/screenshots/by-id/<int:screenshot_id>")
def get_screenshot_by_id(screenshot_id: int) -> Dict[str, Any]:
    """Get a specific screenshot by ID."""
    db: Database = current_app.config['FLASHBACK_DB']
    record = db.get_by_id(screenshot_id)

    if not record:
        return _error_response("Screenshot not found", 404)

    return _record_to_dict(record, include_full_text=True)


@bp.get("/screenshots/by-id/<int:screenshot_id>/neighbors")
def get_neighbors_by_id(screenshot_id: int) -> Dict[str, Any]:
    """Get screenshots near a screenshot ID (timeline view)."""
    db: Database = current_app.config['FLASHBACK_DB']

    # Parse query parameters
    before = int(request.args.get('before', 5))
    after = int(request.args.get('after', 5))

    before = max(0, min(50, before))
    after = max(0, min(50, after))

    # Get center record
    center = db.get_by_id(screenshot_id)
    if not center:
        return _error_response("Screenshot not found", 404)

    # Get neighbors within window
    window_seconds = max(before, after) * 60 * 5  # Rough estimate: 5 min per screenshot
    all_neighbors = db.get_neighbors(center.timestamp, window_seconds=window_seconds)

    # Sort and separate
    all_neighbors.sort(key=lambda r: r.timestamp)

    center_idx = None
    for i, r in enumerate(all_neighbors):
        if r.id == screenshot_id:
            center_idx = i
            break

    if center_idx is None:
        center_idx = len(all_neighbors) // 2

    # Get before/after
    start_idx = max(0, center_idx - before)
    end_idx = min(len(all_neighbors), center_idx + after + 1)
    selected = all_neighbors[start_idx:end_idx]

    return {
        "center_id": screenshot_id,
        "screenshots": [
            {
                **_record_to_dict(r),
                "is_center": r.id == screenshot_id,
                "relative_minutes": round((r.timestamp - center.timestamp) / 60, 1),
            }
            for r in selected
        ],
    }


# Legacy timestamp-based endpoints (deprecated but kept for compatibility)
@bp.get("/screenshots/<float:timestamp>")
def get_screenshot(timestamp: float) -> Dict[str, Any]:
    """Get a specific screenshot by timestamp (deprecated, use /by-id/{id})."""
    db: Database = current_app.config['FLASHBACK_DB']
    record = db.get_by_timestamp(timestamp)

    if not record:
        return _error_response("Screenshot not found", 404)

    return _record_to_dict(record, include_full_text=True)


@bp.get("/screenshots/<float:timestamp>/image")
def preview_screenshot(timestamp: float):
    """Get screenshot preview image"""
    db: Database = current_app.config['FLASHBACK_DB']
    record = db.get_by_timestamp(timestamp)

    if not record:
        return _error_response("Screenshot not found", 404)

    if not record.screenshot_path:
        return _error_response("Screenshot image not found", 404)

    return send_file(record.screenshot_path)


@bp.get("/screenshots/<float:timestamp>/neighbors")
def get_neighbors(timestamp: float) -> Dict[str, Any]:
    """Get screenshots near a timestamp (timeline view)."""
    db: Database = current_app.config['FLASHBACK_DB']

    # Parse query parameters
    before = int(request.args.get('before', 5))
    after = int(request.args.get('after', 5))

    before = max(0, min(50, before))
    after = max(0, min(50, after))

    # Get center record
    center = db.get_by_timestamp(timestamp)
    if not center:
        return _error_response("Screenshot not found", 404)

    # Get neighbors within window
    window_seconds = max(before, after) * 60 * 5  # Rough estimate: 5 min per screenshot
    all_neighbors = db.get_neighbors(timestamp, window_seconds=window_seconds)

    # Sort and separate
    all_neighbors.sort(key=lambda r: r.timestamp)

    center_idx = None
    for i, r in enumerate(all_neighbors):
        if abs(r.timestamp - timestamp) < 1:
            center_idx = i
            break

    if center_idx is None:
        center_idx = len(all_neighbors) // 2

    # Get before/after
    start_idx = max(0, center_idx - before)
    end_idx = min(len(all_neighbors), center_idx + after + 1)
    selected = all_neighbors[start_idx:end_idx]

    return {
        "center_timestamp": timestamp,
        "screenshots": [
            {
                **_record_to_dict(r),
                "is_center": abs(r.timestamp - timestamp) < 1,
                "relative_minutes": round((r.timestamp - timestamp) / 60, 1),
            }
            for r in selected
        ],
    }


@bp.get("/screenshots/<float:timestamp>/ocr")
def get_ocr(timestamp: float) -> Any:
    """Get OCR text for a screenshot."""
    db: Database = current_app.config['FLASHBACK_DB']
    record = db.get_by_timestamp(timestamp)

    if not record:
        return _error_response("Screenshot not found", 404)

    fmt = request.args.get('format', 'json')

    if not record.ocr_text:
        if fmt == 'text':
            return ""
        return {"timestamp": timestamp, "text": "", "word_count": 0}

    if fmt == 'text':
        return record.ocr_text

    return {
        "timestamp": timestamp,
        "text": record.ocr_text,
        "word_count": len(record.ocr_text.split()),
    }


@bp.delete("/screenshots/<float:timestamp>")
def delete_screenshot(timestamp: float) -> Dict[str, str]:
    """Delete a screenshot."""
    db: Database = current_app.config['FLASHBACK_DB']
    record = db.get_by_timestamp(timestamp)

    if not record:
        return _error_response("Screenshot not found", 404)

    # Delete files
    for key in ["screenshot_path", "ocr_path", "embedding_path"]:
        path_str = getattr(record, key, None)
        if path_str:
            try:
                os.remove(path_str)
            except FileNotFoundError:
                pass

    # Delete database record
    db.delete_record(timestamp)

    return {"status": "deleted", "timestamp": str(timestamp)}
