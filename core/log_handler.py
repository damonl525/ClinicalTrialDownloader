#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qt log handler — bridges Python logging to Qt LogViewer via Signal.

Allows runtime log messages (ctrdata.*, service.*, etc.) to be displayed
in a GUI log viewer dialog without modifying existing logging calls.
"""

import logging

from PySide6.QtCore import QObject, Signal


# Map Python logging levels to LogViewer display levels
_LEVEL_MAP = {
    logging.DEBUG: "info",
    logging.INFO: "info",
    logging.WARNING: "warning",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class QtLogHandler(QObject, logging.Handler):
    """Python logging handler that emits Qt signals for each log record.

    Thread-safe: the signal is emitted from whatever thread calls
    logging.info/warning/error, and connected slots run on the main thread.
    """

    log_message = Signal(str, str)  # (level, formatted_message)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        logging.Handler.__init__(self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = _LEVEL_MAP.get(record.levelno, "info")
            self.log_message.emit(level, msg)
        except Exception:
            self.handleError(record)
