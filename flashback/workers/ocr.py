"""OCR worker for flashback."""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Set

from PIL import Image

from flashback.core.logger import get_logger

logger = get_logger(__name__)

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    pytesseract = None  # type: ignore

from flashback.core.database import ScreenshotRecord
from flashback.core.logger import timed
from flashback.workers.base import QueueWorker


def _check_tesseract_in_path() -> bool:
    """Check if tesseract is in PATH (handles Windows .exe suffix)."""
    tesseract_cmd = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    return shutil.which(tesseract_cmd) is not None


def _get_tesseract_languages() -> Set[str]:
    """Get set of supported languages from tesseract."""
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return set()

        # Parse output: skip first line (header), take first word of each line
        lines = result.stdout.strip().split("\n")
        languages = set()
        for line in lines[1:]:  # Skip header line
            lang = line.strip().split()[0] if line.strip() else ""
            if lang:
                languages.add(lang)
        return languages
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()


def validate_ocr_config(config) -> None:
    """Validate OCR configuration before starting worker.

    Raises:
        RuntimeError: If tesseract is not found, no languages configured,
                     or configured languages are not supported.
    """
    # Check if tesseract is in PATH
    if not _check_tesseract_in_path():
        raise RuntimeError(
            "Tesseract not installed, please install and include it in PATH. "
            "See: https://tesseract-ocr.github.io/tessdoc/Installation.html"
        )

    # Check if languages are configured
    languages = config.get_ocr_languages()
    if not languages:
        config_path = getattr(config, '_config_path', 'unknown')
        raise RuntimeError(
            f"No language configured at config path: {config_path}. "
            "Add languages to config, e.g., workers.ocr.languages: ['eng']"
        )

    # Get supported languages from tesseract
    supported = _get_tesseract_languages()
    logger.debug(f"Tesseract supported languages: {supported}")
    if not supported:
        raise RuntimeError(
            "Could not retrieve supported languages from tesseract. "
            "Ensure tesseract is properly installed."
        )

    # Check if all configured languages are supported
    unsupported = []
    for lang in languages:
        # Handle combined languages (e.g., "chi_sim+eng" style)
        for sub_lang in lang.split("+"):
            if sub_lang and sub_lang not in supported:
                unsupported.append(sub_lang)

    if unsupported:
        unsupported_str = ", ".join(f"'{l}'" for l in unsupported)
        supported_str = ", ".join(sorted(supported))
        raise RuntimeError(
            f"Unsupported OCR language(s): {unsupported_str}. "
            f"Install language packs with: sudo apt-get install tesseract-ocr-<lang> "
            f"(Ubuntu/Debian) or see tesseract docs. "
            f"Supported languages: {supported_str}"
        )

class OCRWorker(QueueWorker):
    """Performs OCR on screenshots using Tesseract (runs in separate process)."""

    def __init__(self, config_path=None, db_path=None):
        self._languages = None
        super().__init__(config_path=config_path, db_path=db_path)

    def _init_resources(self):
        """Initialize resources in child process."""
        super()._init_resources()

        self.poll_interval = self.config.get("workers.ocr.work_interval_seconds", 1)
        self.batch_size = self.config.get("workers.ocr.batch_size", 5)

        # Validate OCR configuration
        validate_ocr_config(self.config)

        self._languages = "+".join(self.config.get_ocr_languages())

        if not HAS_TESSERACT:
            raise RuntimeError(
                "pytesseract not installed. Run: pip install pytesseract"
            )

        self.logger.info(f"OCR worker initialized (languages: {self._languages})")

    def get_items(self) -> list:
        """Get screenshots without OCR."""
        items = self.db.get_unprocessed_ocr(limit=self.batch_size * 2)
        self.logger.debug(f"Found {len(items)} items needing OCR")
        return items

    @timed("workers.ocr")
    def process_item(self, item: ScreenshotRecord):
        """Process a single screenshot with OCR."""
        screenshot_path = item.screenshot_path
        timestamp = item.timestamp
        ocr_filename = Path(screenshot_path).stem + ".txt"

        self.logger.info(f"Processing: {ocr_filename}")
        self.logger.debug(f"Timestamp: {timestamp}, Languages: {self._languages}")

        try:
            # Perform OCR with configured languages
            image = Image.open(screenshot_path)
            text = pytesseract.image_to_string(image, lang=self._languages)

            text_preview = text[:100].replace('\n', ' ') if text else "(empty)"
            self.logger.debug(f"OCR result preview: {text_preview}...")

            # Save OCR result
            ocr_path = self.config.ocr_dir / ocr_filename
            ocr_path.write_text(text, encoding="utf-8")

            # Update database
            self.db.update_ocr(timestamp, str(ocr_path), text)
            self.logger.info(f"Processed: {ocr_filename} ({len(text)} chars)")

        except Exception as e:
            self.logger.exception(f"Failed to process {screenshot_path}: {e}")
