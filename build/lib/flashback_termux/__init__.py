"""
Flashback Termux - Android Screenshot Timeline for Termux

An Android screenshot automation tool that captures screens with app context
and provides a web-based timeline interface.
"""

__version__ = "0.1.0"
__author__ = "james4ever0"

from .screenshot_worker import TermuxScreenshotWorker
from .window_title_worker import TermuxWindowTitleWorker

__all__ = ["TermuxScreenshotWorker", "TermuxWindowTitleWorker"]
