#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File logger — persistent log output with daily rotation.

Log files are stored in %APPDATA%/ctrdata_downloader/logs/
with daily rotation and 30-day retention.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path


def get_log_dir() -> Path:
    """Return the log directory, creating it if needed."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    log_dir = Path(base) / "ctrdata_downloader" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file_path() -> Path:
    """Return today's log file path."""
    return get_log_dir() / f"{datetime.now().strftime('%Y-%m-%d')}.log"


class DailyFileHandler(logging.Handler):
    """Logging handler that writes to daily log files with rotation."""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self._current_date = ""
        self._fh = None

    def _get_or_create_file(self) -> logging.FileHandler:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._fh:
                self._fh.close()
            path = get_log_dir() / f"{today}.log"
            self._fh = logging.FileHandler(str(path), encoding="utf-8")
            self._current_date = today
        return self._fh

    def emit(self, record):
        try:
            fh = self._get_or_create_file()
            fh.emit(record)
            fh.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        if self._fh:
            self._fh.close()
        super().close()


def cleanup_old_logs(max_age_days: int = 30):
    """Delete log files older than max_age_days."""
    log_dir = get_log_dir()
    cutoff = time.time() - (max_age_days * 86400)
    for f in log_dir.glob("*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def setup_file_logging(level: int = logging.INFO) -> DailyFileHandler:
    """Set up file logging and return the handler for later removal."""
    cleanup_old_logs()

    handler = DailyFileHandler(level=level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    # Ensure root logger level allows file handler to capture messages
    if root_logger.level > level:
        root_logger.setLevel(level)

    return handler


def remove_file_logging(handler: DailyFileHandler):
    """Remove a previously added file logging handler."""
    if handler:
        logging.getLogger().removeHandler(handler)
        handler.close()
