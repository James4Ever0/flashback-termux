"""Search endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, jsonify, request
from werkzeug.datastructures import FileStorage

from flashback.core.database import ScreenshotRecord
from flashback.search.bm25 import BM25Search
from flashback.search.embedding import (
    HybridEmbeddingSearch,
    ImageEmbeddingSearch,
    TextEmbeddingSearch,
)
from flashback.search.fusion import reciprocal_rank_fusion
from flashback.core.logger import get_logger

bp = Blueprint('search', __name__)

logger = get_logger("api.routes.search")


def _record_to_dict(record: ScreenshotRecord, include_full_text: bool = False) -> Dict[str, Any]:
    """Convert ScreenshotRecord to dict for API response."""
    preview = ""
    if record.ocr_text:
        preview = record.ocr_text[:200] + "..." if len(record.ocr_text) > 200 else record.ocr_text

    result = {
        "id": record.id,
        "timestamp": record.timestamp,
        "timestamp_formatted": record.timestamp_formatted,
        "screenshot_path": record.screenshot_path,
        "screenshot_url": f"/api/v1/screenshots/{record.timestamp}/image",
        "window_title": record.window_title,
        "ocr_text_preview": preview,
        "has_text_embedding": record.text_embedding_path is not None,
        "has_image_embedding": record.image_embedding_path is not None,
        "has_embedding": record.text_embedding_path is not None or record.image_embedding_path is not None,
    }

    if include_full_text and record.ocr_text:
        result["ocr_text_full"] = record.ocr_text

    return result


def _error_response(message: str, status_code: int = 400):
    """Create error response."""
    response = jsonify({"error": message})
    response.status_code = status_code
    return response


@bp.get("/search")
def search() -> Dict[str, Any]:
    """Search screenshots with configurable search mode."""
    logger.info("Search query: %s, search mode: %s" % (request.args.get('q'), request.args.get('search_mode')))
    config = current_app.config['FLASHBACK_CONFIG']
    db = current_app.config['FLASHBACK_DB']

    # Parse query parameters
    q = request.args.get('q', '')
    search_mode = request.args.get('search_mode')
    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    window_title = request.args.get('window_title')

    # Clamp limit
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    # Use default search mode if not specified
    if search_mode is None:
        search_mode = config.get_default_search_mode()
    logger.info("Resolved search mode: %s" % search_mode)

    # Get search mode config
    mode_config = config.get_search_mode_config(search_mode)
    logger.info("Mode config: %s" % mode_config)
    if not mode_config:
        return _error_response(f"Unknown search mode: {search_mode}")

    # Check if required methods are enabled
    methods = mode_config.get("methods", {})
    for method in methods.keys():
        if method == "bm25" and not config.is_search_enabled("bm25"):
            return _error_response("BM25 search is not enabled")
        if method == "text_embedding" and not config.is_search_enabled("text_embedding"):
            return _error_response("Text embedding search is not enabled")
        if method == "image_embedding" and not config.is_search_enabled("image_embedding"):
            return _error_response("Image embedding search is not enabled")

    # Parse time range
    start_ts: Optional[float] = None
    end_ts: Optional[float] = None

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

    # Perform search based on mode
    bm25_results: List[tuple] = []
    text_emb_results: List[tuple] = []
    image_emb_results: List[tuple] = []
    score_breakdown = {}

    try:
        if "bm25" in methods and config.is_search_enabled("bm25"):
            from flashback.search.bm25_manager import get_bm25_manager
            bm25_manager = get_bm25_manager(config, db)
            bm25 = bm25_manager.get_instance()
            if bm25:
                bm25_results = bm25.search(q, top_k=limit * 2)
                score_breakdown["bm25_count"] = len(bm25_results)
    except Exception as e:
        logger.error(f"[Search] BM25 error: {e}")
        score_breakdown["bm25_error"] = str(e)

    try:
        if "text_embedding" in methods and config.is_search_enabled("text_embedding"):
            text_search = TextEmbeddingSearch(config, db)
            text_emb_results = text_search.search(q, top_k=limit * 2)
            score_breakdown["text_embedding_count"] = len(text_emb_results)
    except Exception as e:
        logger.error(f"[Search] Text embedding error: {e}")
        score_breakdown["text_embedding_error"] = str(e)

    try:
        if "image_embedding" in methods and config.is_search_enabled("image_embedding"):
            image_search = ImageEmbeddingSearch(config, db)
            # For text_to_image mode, try to search by text using image embeddings
            if search_mode == "text_to_image":
                image_emb_results = image_search.search_by_text(q, top_k=limit * 2)
            score_breakdown["image_embedding_count"] = len(image_emb_results)
    except Exception as e:
        logger.error(f"[Search] Image embedding error: {e}")
        score_breakdown["image_embedding_error"] = str(e)

    # Fuse results based on fusion strategy
    fusion = mode_config.get("fusion", "reciprocal_rank")
    rrf_k = mode_config.get("rrf_k", 60)
    weights = {k: v.get("weight", 1.0) for k, v in methods.items()}

    if fusion == "reciprocal_rank":
        all_results = []
        if bm25_results:
            all_results.append(bm25_results)
        if text_emb_results:
            all_results.append(text_emb_results)
        if image_emb_results:
            all_results.append(image_emb_results)

        if all_results:
            merged = reciprocal_rank_fusion(*all_results, k=rrf_k, top_k=limit * 2)
        else:
            merged = []
    else:
        # Simple concatenation with deduplication (fallback)
        seen = set()
        merged = []
        for results in [bm25_results, text_emb_results, image_emb_results]:
            for doc_id, score in results:
                if doc_id not in seen:
                    seen.add(doc_id)
                    merged.append((doc_id, score))
        merged = merged[:limit * 2]

    # Fetch full records and filter
    results = []
    for doc_id, score in merged:
        record = db.get_by_id(doc_id)
        if not record:
            continue

        # Apply time filters
        if start_ts and record.timestamp < start_ts:
            continue
        if end_ts and record.timestamp > end_ts:
            continue

        # Apply window title filter
        if window_title and (not record.window_title or window_title.lower() not in record.window_title.lower()):
            continue

        result_dict = _record_to_dict(record)
        result_dict["score"] = score
        results.append(result_dict)

    # Apply offset and limit
    total = len(results)
    results = results[offset : offset + limit]

    return {
        "query": q,
        "search_mode": search_mode,
        "mode_description": mode_config.get("description", ""),
        "total": total,
        "offset": offset,
        "limit": limit,
        "score_breakdown": score_breakdown,
        "results": results,
    }


@bp.post("/search/image")
def search_by_image() -> Dict[str, Any]:
    """Search for screenshots visually similar to the uploaded image."""
    config = current_app.config['FLASHBACK_CONFIG']
    db = current_app.config['FLASHBACK_DB']

    if not config.is_search_enabled("image_embedding"):
        return _error_response("Image embedding search is not enabled")

    # Parse query parameters
    limit = int(request.args.get('limit', 20))
    search_mode = request.args.get('search_mode', 'image_embedding_only')

    limit = max(1, min(100, limit))

    # Get uploaded file
    if 'image' not in request.files:
        return _error_response("No image file provided")

    image_file: FileStorage = request.files['image']

    # Read image data
    try:
        image_data = image_file.read()
    except Exception as e:
        return _error_response(f"Failed to read image: {e}")

    # Perform image search
    try:
        image_search = ImageEmbeddingSearch(config, db)
        search_results = image_search.search_by_image(image_data, top_k=limit)

        formatted = []
        for doc_id, score in search_results:
            record = db.get_by_id(doc_id)
            if record:
                result_dict = _record_to_dict(record)
                result_dict["score"] = score
                formatted.append(result_dict)

        return {
            "search_mode": search_mode,
            "total": len(formatted),
            "results": formatted,
        }
    except Exception as e:
        return _error_response(f"Image search failed: {e}", 500)


@bp.post("/search/multi-modal")
def search_multi_modal() -> Dict[str, Any]:
    """Search with both text and image queries (multi-modal search).

    Combines text and image embeddings using Reciprocal Rank Fusion.
    """
    config = current_app.config['FLASHBACK_CONFIG']
    db = current_app.config['FLASHBACK_DB']

    # Parse query parameters
    limit = int(request.args.get('limit', 20))
    text_weight = float(request.args.get('text_weight', 0.5))
    image_weight = float(request.args.get('image_weight', 0.5))

    limit = max(1, min(100, limit))
    text_weight = max(0.0, min(1.0, text_weight))
    image_weight = max(0.0, min(1.0, image_weight))

    # Get form data
    q = request.form.get('q')

    # Get uploaded file
    image_data = None
    if 'image' in request.files:
        image_file: FileStorage = request.files['image']
        try:
            image_data = image_file.read()
        except Exception as e:
            return _error_response(f"Failed to read image: {e}")

    if not q and not image_data:
        return _error_response("Either text query (q) or image must be provided")

    # Perform hybrid search
    try:
        hybrid_search = HybridEmbeddingSearch(config, db)

        # Temporarily override weights
        original_weights = hybrid_search.weights.copy()
        hybrid_search.weights["text_weight"] = text_weight
        hybrid_search.weights["image_weight"] = image_weight

        results, metadata = hybrid_search.search_fused(
            text_query=q,
            image_query=image_data,
            top_k=limit,
        )

        # Restore original weights
        hybrid_search.weights = original_weights

        # Format results
        formatted = []
        for doc_id, score in results:
            record = db.get_by_id(doc_id)
            if record:
                result_dict = _record_to_dict(record)
                result_dict["score"] = score
                formatted.append(result_dict)

        return {
            "query": q,
            "has_image_query": image_data is not None,
            "text_weight": text_weight,
            "image_weight": image_weight,
            "metadata": metadata,
            "total": len(formatted),
            "results": formatted,
        }
    except Exception as e:
        return _error_response(f"Multi-modal search failed: {e}", 500)


@bp.get("/search/similar")
def search_similar() -> Dict[str, Any]:
    """Find screenshots similar to text description (legacy endpoint)."""
    config = current_app.config['FLASHBACK_CONFIG']
    db = current_app.config['FLASHBACK_DB']

    if not config.is_search_enabled("text_embedding"):
        return _error_response("Text embedding search is not enabled")

    text = request.args.get('text')
    limit = int(request.args.get('limit', 20))
    limit = max(1, min(100, limit))

    if not text:
        return _error_response("Text query required")

    try:
        embedding = TextEmbeddingSearch(config, db)
        results = embedding.search(text, top_k=limit)

        formatted = []
        for doc_id, score in results:
            record = db.get_by_id(doc_id)
            if record:
                result_dict = _record_to_dict(record)
                result_dict["score"] = score
                formatted.append(result_dict)

        return {"query": text, "mode": "text_embedding", "results": formatted}
    except Exception as e:
        return _error_response(str(e), 500)


@bp.get("/search/modes")
def get_search_modes() -> Dict[str, Any]:
    """Get available search modes and their descriptions."""
    config = current_app.config['FLASHBACK_CONFIG']
    modes_config = config.get("search.search_modes", {})

    modes = []
    for mode_id, mode_data in modes_config.items():
        modes.append({
            "id": mode_id,
            "name": mode_data.get("description", mode_id),
            "inputs": mode_data.get("inputs", ["text"]),
            "methods": list(mode_data.get("methods", {}).keys()),
        })

    return {
        "modes": modes,
        "default": config.get_default_search_mode(),
    }
