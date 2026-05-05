#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CDE PDF downloader — uses QWebEngineProfile to download 审评报告 and 说明书 PDFs.

Navigates to each PDF URL in a hidden QWebEnginePage with the built-in
PDF viewer disabled, which forces Chromium to offer the file as a download.
The downloadRequested signal is intercepted to save files to disk.

Must run on the main thread (Qt event loop requirement).
Shares the default QWebEngineProfile with CdeListScraper (same cookies).
"""

import logging
import os
import random
import re
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)

logger = logging.getLogger(__name__)

from core.constants import (
    CDE_DOWNLOAD_TIMEOUT,
    CDE_DOWNLOAD_DELAY_MIN,
    CDE_DOWNLOAD_DELAY_MAX,
)

# Timeout per file download (seconds)
_DOWNLOAD_TIMEOUT = CDE_DOWNLOAD_TIMEOUT

# Base delay between downloads (ms). Random jitter added.
_DOWNLOAD_DELAY_MIN = CDE_DOWNLOAD_DELAY_MIN * 1000   # seconds → ms
_DOWNLOAD_DELAY_MAX = CDE_DOWNLOAD_DELAY_MAX * 1000    # seconds → ms

# Cooldown after consecutive failures (ms)
_COOLDOWN_DELAY = 60000  # 60 seconds

# Max consecutive failures before triggering cooldown
_MAX_CONSECUTIVE_FAILURES = 2


def _make_download_filename(drug_name: str, accept_id: str, doc_type: str) -> str:
    """Generate filename: {drug_name}_{accept_id}_{doc_type}.pdf

    Args:
        drug_name: 药品名称
        accept_id: 受理号
        doc_type: "审评报告" or "说明书"
    """
    def sanitize(s):
        return re.sub(r'[\\/:*?"<>|]', '', s).replace(' ', '_')

    prefix = sanitize(drug_name) if drug_name else sanitize(doc_type)
    return f"{prefix}_{accept_id}_{doc_type}.pdf"


class _SilentPage(QWebEnginePage):
    """QWebEnginePage that suppresses JavaScript console messages from stderr."""

    def javaScriptConsoleMessage(self, level, message, line, sourceId):
        logger.debug("JS [%s:%d] %s", sourceId, line, message)


class CdePdfDownloader(QObject):
    """Download CDE 审评报告/说明书 PDFs via Chromium browser engine.

    Uses the default QWebEngineProfile (shares cookies with CdeListScraper).
    Disables the built-in PDF viewer so that navigating to a PDF URL
    triggers a download instead of rendering.

    Reuses a single QWebEnginePage for all downloads to maintain WAF session.

    Rate-limiting strategy:
    - Random delay (5-10s) between downloads to mimic human behavior
    - Automatic cooldown (60s) after consecutive failures
    - Single retry on failure before marking as failed
    """

    download_progress = Signal(int, int, str)  # current, total, filename
    download_complete = Signal(dict)            # {success: [paths], failed: [{...}]}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = QWebEngineProfile.defaultProfile()
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
        # Track active downloads by download object to avoid state confusion
        self._active_downloads: Dict[int, str] = {}  # id(download) -> filename

    def download(self, docs: List[dict], save_dir: str):
        """Start downloading PDFs sequentially.

        Pre-scans save_dir for existing files and skips them immediately,
        avoiding the per-file delay for already-downloaded docs.

        Args:
            docs: List of row dicts with keys: url, drug_name, accept_id, doc_type
            save_dir: Target directory for downloads
        """
        os.makedirs(save_dir, exist_ok=True)

        # Pre-scan: separate already-existing files from download queue
        to_download = []
        skipped = []
        for doc in docs:
            filename = _make_download_filename(
                drug_name=doc.get("drug_name", ""),
                accept_id=doc.get("accept_id", ""),
                doc_type=doc.get("doc_type", ""),
            )
            filepath = os.path.join(save_dir, filename)
            if os.path.exists(filepath):
                skipped.append(filepath)
            else:
                to_download.append(doc)

        self._queue = to_download
        self._save_dir = save_dir
        self._results = {"success": [], "failed": [], "skipped": skipped}
        self._total = len(to_download)
        self._current_idx = 0
        self._current_retry = 0
        self._consecutive_failures = 0
        self._cancelled = False
        self._active_downloads = {}

        if skipped:
            logger.info(
                "CDE下载预扫描: 跳过 %d 个已存在文件，需下载 %d 个",
                len(skipped), len(to_download),
            )

        if not to_download:
            logger.info("CDE下载: 所有文件已存在，无需下载")
            self.download_complete.emit(self._results)
            return

        # Create a single reusable page
        if self._page:
            self._page.deleteLater()
        self._page = _SilentPage(self._profile, self)

        logger.info(
            "开始下载CDE审评文档: %d 个文件, 保存到 %s",
            self._total, save_dir,
        )

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
        logger.info("CDE文档下载已取消: 已完成 %d/%d", self._current_idx, self._total)
        self.download_complete.emit(self._results)

    # ─────────────────────────────────────────────────────────────
    # Internal: download queue
    # ─────────────────────────────────────────────────────────────

    def _download_next(self, retry: int = 0):
        """Process next file in queue."""
        if self._cancelled:
            return

        if self._current_idx >= self._total:
            self._finish_all()
            return

        self._current_retry = retry

        doc = self._queue[self._current_idx]
        self._current_url = doc.get("url", "")
        self._current_filename = _make_download_filename(
            drug_name=doc.get("drug_name", ""),
            accept_id=doc.get("accept_id", ""),
            doc_type=doc.get("doc_type", ""),
        )

        filepath = os.path.join(self._save_dir, self._current_filename)

        # Reset timeout timer
        if self._timeout_timer:
            self._timeout_timer.stop()
        else:
            self._timeout_timer = QTimer(self)
            self._timeout_timer.setSingleShot(True)
            self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(_DOWNLOAD_TIMEOUT * 1000)

        logger.info(
            "开始加载 [%d/%d]: %s → %s",
            self._current_idx + 1, self._total, self._current_filename,
            self._current_url,
        )

        # Reuse the same page — navigate to download URL
        self._page.load(QUrl(self._current_url))

    def _on_download_requested(self, download: QWebEngineDownloadRequest):
        """Handle download request from QWebEngineProfile."""
        if self._cancelled:
            download.cancel()
            return

        # Ignore stale download requests from previous navigations
        download_id = id(download)

        self._timeout_timer.stop()

        download.setDownloadDirectory(self._save_dir)
        download.setDownloadFileName(self._current_filename)

        self._current_download = download
        self._active_downloads[download_id] = self._current_filename
        download.stateChanged.connect(
            lambda state, did=download_id: self._on_state_changed(state, did)
        )
        download.accept()

        logger.info("下载请求已接受: %s (id=%s)", self._current_filename, download_id)

    def _on_state_changed(self, state, download_id: int):
        """Handle download state changes."""
        filename = self._active_downloads.get(download_id, self._current_filename)

        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            filepath = os.path.join(self._save_dir, filename)
            self._results["success"].append(filepath)
            self._consecutive_failures = 0
            self._active_downloads.pop(download_id, None)
            logger.info("下载完成: %s → %s", filename, filepath)
            self._advance()
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            reason = self._current_download.interruptReason() if self._current_download else -1
            self._active_downloads.pop(download_id, None)
            logger.warning(
                "下载中断: %s (reason=%s, retry=%d)",
                filename, reason, self._current_retry,
            )
            if self._current_retry == 0:
                delay = random.randint(5000, 10000)
                logger.info("将在 %.1f 秒后重试: %s", delay / 1000, filename)
                QTimer.singleShot(delay, self._retry_current)
            else:
                self._consecutive_failures += 1
                self._results["failed"].append({
                    "url": self._current_url,
                    "filename": filename,
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

        if self._page:
            self._page.deleteLater()
            self._page = None

        success_count = len(self._results["success"])
        skipped_count = len(self._results["skipped"])
        failed_count = len(self._results["failed"])
        logger.info(
            "CDE文档下载完成: %d 成功, %d 跳过, %d 失败",
            success_count, skipped_count, failed_count,
        )
        self.download_complete.emit(self._results)
