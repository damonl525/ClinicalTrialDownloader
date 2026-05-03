#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDA PDF downloader — uses QWebEngineProfile to download review PDFs.

Navigates to each PDF URL in a hidden QWebEnginePage with the built-in
PDF viewer disabled, which forces Chromium to offer the file as a download.
The downloadRequested signal is intercepted to save files to disk.

Must run on the main thread (Qt event loop requirement).
Shares the default QWebEngineProfile with FdaTocParser (same cookies).
"""

import logging
import os
import random
from typing import List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)

from service.fda_service import _make_download_filename

logger = logging.getLogger(__name__)

# Timeout per file download (seconds)
_DOWNLOAD_TIMEOUT = 150

# Base delay between downloads (ms). Random jitter added to look human-like.
_DOWNLOAD_DELAY_MIN = 8000   # 8 seconds
_DOWNLOAD_DELAY_MAX = 15000  # 15 seconds

# Cooldown after consecutive failures (ms)
_COOLDOWN_DELAY = 60000  # 60 seconds

# Max consecutive failures before triggering cooldown
_MAX_CONSECUTIVE_FAILURES = 2


class _SilentPage(QWebEnginePage):
    """QWebEnginePage that suppresses JavaScript console messages from stderr."""

    def javaScriptConsoleMessage(self, level, message, line, sourceId):
        logger.debug("JS [%s:%d] %s", sourceId, line, message)


class FdaPdfDownloader(QObject):
    """Download FDA review PDFs via Chromium browser engine.

    Uses the default QWebEngineProfile (shares cookies with FdaTocParser).
    Disables the built-in PDF viewer so that navigating to a PDF URL
    triggers a download instead of rendering.

    Rate-limiting strategy:
    - Random delay (8-15s) between downloads to mimic human behavior
    - Automatic cooldown (60s) after consecutive failures
    - Single retry on failure before marking as failed
    """

    download_progress = Signal(int, int, str)  # current, total, filename
    download_complete = Signal(dict)            # {success: [paths], failed: [{...}]}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = QWebEngineProfile.defaultProfile()
        # Disable PDF viewer so PDF URLs trigger downloads
        self._profile.settings().setAttribute(
            QWebEngineSettings.WebAttribute.PdfViewerEnabled, False
        )

        self._queue: List[dict] = []
        self._save_dir = ""
        self._results = {"success": [], "failed": []}
        self._total = 0
        self._current_idx = 0
        self._cancelled = False
        self._current_download: Optional[QWebEngineDownloadRequest] = None
        self._current_filename = ""
        self._current_url = ""
        self._page: Optional[QWebEnginePage] = None
        self._timeout_timer: Optional[QTimer] = None
        self._current_retry = 0
        self._consecutive_failures = 0

    def download(self, docs: List[dict], save_dir: str):
        """Start downloading PDFs sequentially.

        Args:
            docs: List of row dicts (must have doc_url, brand_name, etc.)
            save_dir: Target directory for downloads
        """
        os.makedirs(save_dir, exist_ok=True)

        self._queue = list(docs)
        self._save_dir = save_dir
        self._results = {"success": [], "failed": [], "skipped": []}
        self._total = len(docs)
        self._current_idx = 0
        self._current_retry = 0
        self._consecutive_failures = 0
        self._cancelled = False

        logger.info(
            "开始下载FDA审评文档: %d 个文件, 保存到 %s",
            self._total, save_dir,
        )

        # Connect download signal
        self._profile.downloadRequested.connect(self._on_download_requested)

        self._download_next()

    def cancel(self):
        """Cancel current download and stop queue."""
        self._cancelled = True
        if self._current_download:
            self._current_download.cancel()
        if self._timeout_timer:
            self._timeout_timer.stop()
        self._queue.clear()
        try:
            self._profile.downloadRequested.disconnect(self._on_download_requested)
        except RuntimeError:
            pass
        logger.info("FDA文档下载已取消: 已完成 %d/%d", self._current_idx, self._total)
        self.download_complete.emit(self._results)

    # ------------------------------------------------------------------
    # Internal: download queue
    # ------------------------------------------------------------------

    def _download_next(self, retry: int = 0):
        """Process next file in queue."""
        if self._cancelled:
            return

        if self._current_idx >= self._total:
            self._finish_all()
            return

        self._current_retry = retry

        doc = self._queue[self._current_idx]
        self._current_url = doc.get("doc_url", "")
        self._current_filename = _make_download_filename(
            brand_name=doc.get("brand_name", ""),
            submission_type=doc.get("submission_type", ""),
            date=doc.get("submission_status_date", ""),
            doc_type=doc.get("doc_type", ""),
        )

        filepath = os.path.join(self._save_dir, self._current_filename)

        # Skip if file already exists on disk
        if os.path.exists(filepath):
            logger.info("文件已存在，跳过: %s", self._current_filename)
            self._results["skipped"].append(filepath)
            self._advance()
            return

        # Clean up previous page
        if self._page:
            self._page.deleteLater()

        self._page = _SilentPage(self._profile, self)

        # Timeout timer
        if self._timeout_timer:
            self._timeout_timer.deleteLater()
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(_DOWNLOAD_TIMEOUT * 1000)

        logger.info(
            "开始加载 [%d/%d]: %s",
            self._current_idx + 1, self._total, self._current_filename,
        )
        self._page.load(QUrl(self._current_url))

    def _on_download_requested(self, download: QWebEngineDownloadRequest):
        """Handle download request from QWebEngineProfile."""
        if self._cancelled:
            download.cancel()
            return

        self._timeout_timer.stop()

        download.setDownloadDirectory(self._save_dir)
        download.setDownloadFileName(self._current_filename)

        self._current_download = download
        download.stateChanged.connect(self._on_state_changed)
        download.accept()

        logger.info("下载请求已接受: %s", self._current_filename)

    def _on_state_changed(self, state):
        """Handle download state changes."""
        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            filepath = os.path.join(self._save_dir, self._current_filename)
            self._results["success"].append(filepath)
            self._consecutive_failures = 0
            logger.info("下载完成: %s", self._current_filename)
            self._advance()
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            reason = self._current_download.interruptReason() if self._current_download else -1
            logger.warning(
                "下载中断: %s (reason=%s, retry=%d)",
                self._current_filename, reason, self._current_retry,
            )
            if self._current_retry == 0:
                delay = random.randint(5000, 10000)
                logger.info("将在 %.1f 秒后重试: %s", delay / 1000, self._current_filename)
                QTimer.singleShot(delay, self._retry_current)
            else:
                self._consecutive_failures += 1
                self._results["failed"].append({
                    "url": self._current_url,
                    "filename": self._current_filename,
                    "error": f"interrupted (reason: {reason})",
                })
                self._advance()

    def _on_timeout(self):
        """Handle download timeout."""
        logger.warning("下载超时(%ds): %s", _DOWNLOAD_TIMEOUT, self._current_url)
        if self._current_retry == 0:
            if self._current_download:
                self._current_download.cancel()
            delay = random.randint(5000, 10000)
            logger.info("将在 %.1f 秒后重试: %s", delay / 1000, self._current_filename)
            QTimer.singleShot(delay, self._retry_current)
        else:
            if self._current_download:
                self._current_download.cancel()
            self._consecutive_failures += 1
            self._results["failed"].append({
                "url": self._current_url,
                "filename": self._current_filename,
                "error": f"timeout ({_DOWNLOAD_TIMEOUT}s)",
            })
            self._advance()

    def _retry_current(self):
        """Retry current file download."""
        if self._cancelled:
            return
        # Clean up current page
        if self._page:
            self._page.deleteLater()
            self._page = None
        self._download_next(retry=1)

    def _advance(self):
        """Move to next file in queue."""
        self._current_idx += 1
        self.download_progress.emit(
            self._current_idx, self._total, self._current_filename
        )

        if self._cancelled:
            return

        if self._current_idx >= self._total:
            self._finish_all()
            return

        # Calculate delay: cooldown after consecutive failures, otherwise random
        if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            delay = _COOLDOWN_DELAY
            self._consecutive_failures = 0
            logger.warning(
                "连续 %d 次失败，冷却 %.0f 秒后继续...",
                _MAX_CONSECUTIVE_FAILURES, delay / 1000,
            )
        else:
            delay = random.randint(_DOWNLOAD_DELAY_MIN, _DOWNLOAD_DELAY_MAX)

        logger.info("等待 %.1f 秒后下载下一个文件...", delay / 1000)
        QTimer.singleShot(delay, self._download_next)

    def _finish_all(self):
        """Clean up and emit completion signal."""
        try:
            self._profile.downloadRequested.disconnect(self._on_download_requested)
        except RuntimeError:
            pass

        success_count = len(self._results["success"])
        skipped_count = len(self._results["skipped"])
        failed_count = len(self._results["failed"])
        logger.info(
            "FDA文档下载完成: %d 成功, %d 跳过, %d 失败",
            success_count, skipped_count, failed_count,
        )
        self.download_complete.emit(self._results)
