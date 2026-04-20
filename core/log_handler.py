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

    Buffers recent log entries so the LogDialog can replay history when opened.
    """

    log_message = Signal(str, str)  # (level, formatted_message)
    _MAX_BUFFER = 2000

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        logging.Handler.__init__(self)
        self._buffer = []  # [(level, message), ...]

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = _LEVEL_MAP.get(record.levelno, "info")
            self._buffer.append((level, msg))
            if len(self._buffer) > self._MAX_BUFFER:
                self._buffer = self._buffer[-self._MAX_BUFFER:]
            self.log_message.emit(level, msg)
        except Exception:
            self.handleError(record)

    def get_buffered(self):
        """Return buffered log entries for replay."""
        return list(self._buffer)

    def clear_buffer(self):
        """Clear buffered entries."""
        self._buffer.clear()
