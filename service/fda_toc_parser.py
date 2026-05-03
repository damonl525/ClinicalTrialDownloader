#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDA TOC page parser — uses QWebEnginePage to load TOC.html pages,
extract the pdfFiles JavaScript object, and return confirmed PDF lists.

Must run on the main thread (Qt event loop requirement).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QUrl, QTimer, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

logger = logging.getLogger(__name__)

# Timeout for each TOC page load (seconds)
_PAGE_TIMEOUT = 40

# Max concurrent page loads (limit Chromium memory)
_MAX_CONCURRENT = 3


@dataclass
class TocPageData:
    """Parsed data from a single FDA TOC page."""

    pdf_files: Dict[str, int] = field(default_factory=dict)
    pdf_base_name: str = ""
    drug_name: Optional[str] = None
    company_name: Optional[str] = None
    approval_date: Optional[str] = None


class _SilentPage(QWebEnginePage):
    """QWebEnginePage that suppresses JavaScript console messages from stderr."""

    def javaScriptConsoleMessage(self, level, message, line, sourceId):
        logger.debug("JS [%s:%d] %s", sourceId, line, message)


class FdaTocParser(QObject):
    """Parse FDA TOC pages using hidden QWebEnginePage instances.

    Loads each TOC URL in a real Chromium engine (bypasses FDA bot detection),
    extracts the pdfFiles JavaScript object to determine which PDFs exist.
    """

    parse_complete = Signal(dict)      # {toc_url: TocPageData | None}
    parse_progress = Signal(int, int)  # completed_count, total_count
    parse_error = Signal(str)          # fatal error (e.g. WebEngine unavailable)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: Dict[str, Optional[TocPageData]] = {}
        self._pending_urls: List[str] = []
        self._total = 0
        self._completed = 0
        self._active_pages: List[dict] = []  # {page, url, timer}
        self._cancelled = False

    def parse(self, toc_urls: List[str]):
        """Start async parsing of TOC URLs. Emits parse_complete when all done."""
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for url in toc_urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        if not unique:
            self.parse_complete.emit({})
            return

        self._results = {}
        self._pending_urls = unique
        self._total = len(unique)
        self._completed = 0
        self._cancelled = False
        self._active_pages = []

        logger.info("开始解析FDA审评目录: %d 个TOC页面", self._total)

        # Start initial batch
        self._start_next_batch()

    def cancel(self):
        """Abort all pending page loads."""
        self._cancelled = True
        self._pending_urls.clear()
        for entry in self._active_pages:
            entry["page"].stop()
            entry["timer"].stop()
        self._active_pages.clear()

    def _start_next_batch(self):
        """Fill active slots up to _MAX_CONCURRENT."""
        while (
            len(self._active_pages) < _MAX_CONCURRENT
            and self._pending_urls
            and not self._cancelled
        ):
            url = self._pending_urls.pop(0)
            self._load_page(url)

    def _load_page(self, url: str, _retry: int = 0):
        """Load a single TOC URL in a hidden QWebEnginePage."""
        page = _SilentPage(self)

        # Timer for timeout
        timer = QTimer(self)
        timer.setSingleShot(True)

        entry = {"page": page, "url": url, "timer": timer}
        self._active_pages.append(entry)

        def on_load_finished(ok):
            timer.stop()
            if self._cancelled:
                self._finish_page(entry, None, "cancelled")
                return
            if not ok:
                if _retry == 0:
                    logger.info("TOC页面首次加载失败，重试: %s", url)
                    # Clean up current page before retry
                    if entry in self._active_pages:
                        self._active_pages.remove(entry)
                    page.deleteLater()
                    QTimer.singleShot(1000, lambda: self._load_page(url, _retry=1))
                    return
                logger.warning("TOC页面加载失败(已重试): %s", url)
                self._finish_page(entry, None, "load failed")
                return
            # Wait a moment for JavaScript to execute, then extract
            QTimer.singleShot(1500, lambda: self._extract_js(entry))

        def on_timeout():
            if _retry == 0:
                logger.info("TOC页面首次加载超时，重试: %s", url)
                page.stop()
                # Clean up current page before retry
                if entry in self._active_pages:
                    self._active_pages.remove(entry)
                page.deleteLater()
                timer.stop()
                QTimer.singleShot(1000, lambda: self._load_page(url, _retry=1))
                return
            logger.warning("TOC页面加载超时(已重试): %s", url)
            page.stop()
            self._finish_page(entry, None, "timeout")

        page.loadFinished.connect(on_load_finished)
        timer.timeout.connect(on_timeout)
        timer.start(_PAGE_TIMEOUT * 1000)

        page.load(QUrl(url))

    def _extract_js(self, entry: dict):
        """Extract pdfFiles and related variables from loaded page."""
        page = entry["page"]
        url = entry["url"]

        js_code = """(function() {
            try {
                if (typeof pdfFiles === 'undefined') return JSON.stringify({error: 'no pdfFiles'});
                return JSON.stringify({
                    f: pdfFiles,
                    b: typeof pdfBaseName !== 'undefined' ? pdfBaseName : null,
                    d: typeof drugName !== 'undefined' ? drugName : null,
                    c: typeof companyName !== 'undefined' ? companyName : null,
                    a: typeof approvalDate !== 'undefined' ? approvalDate : null
                });
            } catch(e) {
                return JSON.stringify({error: e.message});
            }
        })()"""

        def on_result(result_str):
            if self._cancelled:
                self._finish_page(entry, None, "cancelled")
                return

            if not result_str:
                logger.warning("TOC页面JS提取返回空: %s", url)
                self._finish_page(entry, None, "empty JS result")
                return

            try:
                data = json.loads(result_str)
            except json.JSONDecodeError:
                logger.warning("TOC页面JS提取JSON解析失败: %s", url)
                self._finish_page(entry, None, "invalid JSON")
                return

            if "error" in data:
                logger.warning("TOC页面无pdfFiles变量: %s", url)
                self._finish_page(entry, None, data["error"])
                return

            toc_data = TocPageData(
                pdf_files=data.get("f", {}),
                pdf_base_name=data.get("b", ""),
                drug_name=data.get("d"),
                company_name=data.get("c"),
                approval_date=data.get("a"),
            )

            active_count = sum(1 for v in toc_data.pdf_files.values() if v == 1)
            logger.info(
                "TOC页面解析成功: %s → 发现 %d 个可用文档",
                url.split("/")[-1], active_count,
            )
            self._finish_page(entry, toc_data, None)

        page.runJavaScript(js_code, 0, on_result)

    def _finish_page(self, entry: dict, data: Optional[TocPageData], error: Optional[str]):
        """Handle completion of a single page load."""
        if error:
            logger.warning("TOC页面解析失败: %s, 原因: %s", entry["url"], error)

        self._results[entry["url"]] = data
        self._completed += 1

        # Clean up
        entry["page"].deleteLater()
        entry["timer"].stop()
        if entry in self._active_pages:
            self._active_pages.remove(entry)

        self.parse_progress.emit(self._completed, self._total)

        # Check if all done
        if self._completed >= self._total:
            success = sum(1 for v in self._results.values() if v is not None)
            logger.info(
                "FDA审评目录解析完成: %d/%d 成功",
                success, self._total,
            )
            self.parse_complete.emit(dict(self._results))
        else:
            # Start next queued URL
            self._start_next_batch()
