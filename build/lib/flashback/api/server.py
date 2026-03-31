"""Flask server for flashback web UI."""

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, request, jsonify, send_file, send_from_directory, render_template_string
from jinja2 import FileSystemLoader, Environment

from flashback.core.config import Config
from flashback.core.daemon import DaemonManager
from flashback.core.database import Database
from flashback.core.logger import get_logger

# Import routes
from flashback.api.routes import health, search, screenshots, config as config_route

logger = get_logger("api.server")


def create_app(config: Optional[Config] = None) -> Flask:
    """Create and configure the Flask application."""
    config = config or Config()

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'flashback-secret-key'

    # Store config and db in app
    app.config['FLASHBACK_CONFIG'] = config
    app.config['FLASHBACK_DB'] = Database(config.db_path, readonly=True)
    logger.info("Flask app created")

    # Initialize search index
    if app.config['FLASHBACK_CONFIG'].is_search_enabled("bm25"):
        from flashback.search.bm25_manager import get_bm25_manager
        bm25_manager = get_bm25_manager(app.config['FLASHBACK_CONFIG'], app.config['FLASHBACK_DB'])
        bm25_manager.get_instance()

    # Register blueprints
    app.register_blueprint(health.bp, url_prefix='/api/v1')
    app.register_blueprint(search.bp, url_prefix='/api/v1')
    app.register_blueprint(screenshots.bp, url_prefix='/api/v1')
    app.register_blueprint(config_route.bp, url_prefix='/api/v1')

    # Setup templates
    template_dir = Path(__file__).parent.parent / "web" / "templates"
    logger.debug(f"Template directory: {template_dir}")
    logger.debug(f"Template directory exists: {template_dir.exists()}")
    if template_dir.exists():
        app.jinja_loader = FileSystemLoader(str(template_dir))

    # Setup static files
    static_dir = Path(__file__).parent / "static"
    logger.debug(f"Static directory: {static_dir}")
    logger.debug(f"Static directory exists: {static_dir.exists()}")

    @app.route('/static/<path:filename>')
    def serve_static(filename):
        """Serve static files."""
        return send_from_directory(str(static_dir), filename)

    # Mount screenshot directory for serving
    screenshot_dir = config.screenshot_dir
    if screenshot_dir.exists():
        @app.route('/screenshots/<path:filename>')
        def serve_screenshot(filename):
            """Serve screenshot files."""
            return send_from_directory(str(screenshot_dir), filename)
    else:
        logger.warning(f"Screenshot directory not found: {screenshot_dir}")
        exit(1)

    @app.route('/healthcheck')
    def healthcheck():
        """Health check endpoint."""
        return "OK"

    @app.route("/timeline")
    def timeline():
        """Serve the timeline browsing page."""
        template_path = template_dir / "timeline.html"
        if template_path.exists():
            with open(template_path, 'r') as f:
                template_content = f.read()
            return render_template_string(template_content)
        return jsonify({"message": "Timeline page"})

    @app.route("/screenshot/<int:screenshot_id>")
    def screenshot_detail(screenshot_id: int):
        """Serve the screenshot detail page."""
        template_path = template_dir / "detail.html"
        if template_path.exists():
            with open(template_path, 'r') as f:
                template_content = f.read()
            return render_template_string(template_content, screenshot_id=screenshot_id)
        return jsonify({"message": "Screenshot detail page", "id": screenshot_id})

    @app.route("/")
    def index():
        """Serve the main web UI page."""
        search_methods = []
        if config.is_search_enabled("bm25"):
            search_methods.append({"id": "bm25_only", "name": "BM25 Text", "default": True})
        if config.is_search_enabled("embedding"):
            default = not (config.is_search_enabled("bm25") or config.is_search_enabled("image_embedding"))
            search_methods.append(
                {"id": "text_embedding_only", "name": "Text Embedding (Semantic)", "default": default}
            )
        if config.is_search_enabled("bm25") and config.is_search_enabled("embedding"):
            search_methods.append(
                {"id": "text_hybrid", "name": "Text Hybrid (BM25 + Embedding)", "default": False}
            )

        if config.is_search_enabled("image_embedding"):
            default = not (config.is_search_enabled("bm25") or config.is_search_enabled("embedding"))
            search_methods.append({
                "id": "image_embedding_only", "name": "Image Embedding (Visual)", "default": default
            })
            search_methods.append({
                "id": "text_to_image", "name": "Text to Image", "default": False
            })

        if config.is_search_enabled("image_embedding") and config.is_search_enabled("embedding"):
            search_methods.append(
                {"id": "text_and_image", "name": "Text and Image Search", "default": False}
            )

        if config.is_search_enabled("image_embedding") and config.is_search_enabled("embedding") and config.is_search_enabled("bm25"):
            search_methods.append(
                {"id": "comprehensive", "name": "Comprehensive Search", "default": False}
            )

        template_path = template_dir / "index.html"
        if template_path.exists():
            with open(template_path, 'r') as f:
                template_content = f.read()
            return render_template_string(template_content, search_methods=search_methods)
        return jsonify({"message": "Flashback API", "search_methods": search_methods})

    @app.route("/favicon.ico")
    def favicon():
        """Serve the favicon."""
        favicon_path = static_dir / "favicon.ico"
        if favicon_path.exists():
            return send_file(str(favicon_path))
        return jsonify({"error": "Favicon not found"}), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle generic exceptions."""
        logger.exception(f"Unhandled exception: {e}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500

    @app.errorhandler(404)
    def handle_not_found(e):
        """Handle 404 errors."""
        return jsonify({"error": "Not Found", "message": str(e)}), 404

    @app.before_request
    def log_request():
        """Log incoming requests."""
        request.start_time = time.time()
        logger.debug(
            f"REQUEST {request.method} {request.path} "
            f"from {request.remote_addr}"
        )

    @app.after_request
    def log_response(response):
        """Log outgoing responses."""
        process_time = time.time() - getattr(request, 'start_time', time.time())
        logger.debug(
            f"RESPONSE {request.method} {request.path} "
            f"status={response.status_code} time={process_time:.3f}s"
        )
        return response

    return app


def main():
    """Main entry point for the API server."""
    config = Config()

    # Check if backend is running
    backend_daemon = DaemonManager("backend")
    if not backend_daemon.is_running():
        logger.warning("Backend daemon is not running!")
        logger.info("Start it with: flashback serve --daemon")

    host = config.webui_host
    port = config.webui_port

    logger.info(f"Starting web UI on http://{host}:{port}")

    app = create_app(config)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
