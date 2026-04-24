#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CDE list page scraper — uses QWebEnginePage to scrape the CDE marketed drug list.

Must run on the main thread (Qt event loop requirement).
"""

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QUrl, QTimer, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from core.constants import (
    CDE_LIST_URL,
    CDE_PAGE_SIZE,
    CDE_PAGE_TIMEOUT,
)

logger = logging.getLogger(__name__)


class CdeListScraper(QObject):
    """Scrape CDE list pages using QWebEnginePage instances.

    Loads each list page URL in a real Chromium engine (bypasses Ruishu WAF),
    extracts table data via runJavaScript(), and supports pagination.
    """

    page_parsed = Signal(int, int, list)   # current_page, total_pages, rows
    scrape_complete = Signal(list)           # all_rows
    scrape_error = Signal(str)
    scrape_progress = Signal(int, int)       # current_page, total_pages
    detail_parsed = Signal(str, dict)        # detail_url, {pdf_urls: [...], meta: {...}}
    detail_error = Signal(str, str)         # detail_url, error_msg

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = QWebEngineProfile.defaultProfile()
        self._pending_pages: List[str] = []
        self._all_rows: List[dict] = []
        self._current_page = 0
        self._total_pages = 0
        self._total_records = 0
        self._scrape_all = False
        self._cancelled = False
        self._active_page: Optional[QWebEnginePage] = None
        self._page_timer: Optional[QTimer] = None
        self._detail_queue: List[str] = []
        self._detail_results: Dict[str, dict] = {}
        self._active_detail_pages: List[dict] = []

    def scrape(self, keyword: str = "", date_from: str = "", date_to: str = "",
               drug_type: str = "", apply_type: str = "", reg_class: str = "",
               scrape_all: bool = False):
        """Start scraping list pages.

        Args:
            keyword: 关键词搜索
            date_from: 承办日期起 (YYYY-MM-DD)
            date_to: 承办日期止 (YYYY-MM-DD)
            drug_type: 药品类型筛选值
            apply_type: 申请类型筛选值
            reg_class: 注册分类筛选值
            scrape_all: True = 自动爬取所有页；False = 只加载第1页
        """
        self._cancelled = False
        self._scrape_all = scrape_all
        self._all_rows = []
        self._current_page = 0
        self._total_pages = 0
        self._total_records = 0

        # Build first page URL with query params
        first_url = self._build_list_url(keyword, date_from, date_to,
                                          drug_type, apply_type, reg_class, page=1)
        logger.info("开始爬取CDE列表: %s", first_url)
        self._load_page(first_url)

    def cancel(self):
        """Abort all pending operations."""
        self._cancelled = True
        self._pending_pages.clear()
        if self._active_page:
            self._active_page.stop()
            self._active_page.deleteLater()
            self._active_page = None
        if self._page_timer:
            self._page_timer.stop()
        for entry in self._active_detail_pages:
            entry["page"].stop()
            entry["page"].deleteLater()
            entry["timer"].stop()
        self._active_detail_pages.clear()

    def _build_list_url(self, keyword: str, date_from: str, date_to: str,
                        drug_type: str, apply_type: str, reg_class: str,
                        page: int) -> str:
        """Build CDE list page URL with filter parameters."""
        params = []
        if keyword:
            params.append(f"searchValue={keyword}")
        if date_from:
            params.append(f"dateFrom={date_from}")
        if date_to:
            params.append(f"dateTo={date_to}")
        if drug_type:
            params.append(f"drugType={drug_type}")
        if apply_type:
            params.append(f"applyType={apply_type}")
        if reg_class:
            params.append(f"regClass={reg_class}")
        params.append(f"pageNum={page}")

        query = "&".join(params)
        return f"{CDE_LIST_URL}?{query}"

    def _load_page(self, url: str, _retry: int = 0):
        """Load a single list page URL in a hidden QWebEnginePage."""
        if self._cancelled:
            return

        if self._active_page:
            self._active_page.deleteLater()

        self._active_page = QWebEnginePage(self._profile, self)

        if self._page_timer:
            self._page_timer.deleteLater()
        self._page_timer = QTimer(self)
        self._page_timer.setSingleShot(True)

        def on_load_finished(ok):
            self._page_timer.stop()
            if self._cancelled:
                return
            if not ok:
                if _retry == 0:
                    logger.info("CDE列表页首次加载失败，重试: %s", url)
                    QTimer.singleShot(2000, lambda: self._load_page(url, _retry=1))
                    return
                logger.warning("CDE列表页加载失败(已重试): %s", url)
                self.scrape_error.emit(f"页面加载失败: {url}")
                return
            # Wait for JS to execute and DOM to render
            QTimer.singleShot(2000, lambda: self._extract_table(entry))

        def on_timeout():
            if _retry == 0:
                logger.info("CDE列表页首次加载超时，重试: %s", url)
                self._active_page.stop()
                QTimer.singleShot(2000, lambda: self._load_page(url, _retry=1))
                return
            logger.warning("CDE列表页加载超时(已重试): %s", url)
            self._active_page.stop()
            self.scrape_error.emit(f"页面加载超时: {url}")

        entry = {"url": url}
        self._page_timer.timeout.connect(on_timeout)
        self._page_timer.start(CDE_PAGE_TIMEOUT * 1000)
        self._active_page.loadFinished.connect(on_load_finished)
        self._active_page.load(QUrl(url))

    def _extract_table(self, entry: dict):
        """Extract table rows and pagination info from loaded page."""
        page = self._active_page
        url = entry["url"]

        js_code = """(function() {
            try {
                var totalEl = document.querySelector('.total, .page-total, [class*="total"]');
                var totalText = totalEl ? totalEl.textContent.trim() : '';

                var totalPages = 1;
                var pageMatch = totalText.match(/共\\s*(\\d+)\\s*页/);
                if (pageMatch) {
                    totalPages = parseInt(pageMatch[1], 10);
                }

                var currentPage = 1;
                var currentMatch = totalText.match(/第\\s*(\\d+)\\s*页/);
                if (currentMatch) {
                    currentPage = parseInt(currentMatch[1], 10);
                }

                var rows = [];
                var trs = document.querySelectorAll('table tbody tr, .list-body tr, [class*="list-item"]');
                trs.forEach(function(tr) {
                    var cells = tr.querySelectorAll('td, .cell');
                    if (cells.length >= 7) {
                        var link = tr.querySelector('a[href*="drugDetail"]');
                        rows.push({
                            accept_id: cells[0] ? cells[0].textContent.trim() : '',
                            drug_name: cells[1] ? cells[1].textContent.trim() : '',
                            drug_type: cells[2] ? cells[2].textContent.trim() : '',
                            apply_type: cells[3] ? cells[3].textContent.trim() : '',
                            reg_class: cells[4] ? cells[4].textContent.trim() : '',
                            company: cells[5] ? cells[5].textContent.trim() : '',
                            date: cells[6] ? cells[6].textContent.trim() : '',
                            detail_url: link ? link.getAttribute('href') || '' : ''
                        });
                    }
                });

                return JSON.stringify({
                    rows: rows,
                    total_pages: totalPages,
                    current_page: currentPage,
                    total_text: totalText
                });
            } catch(e) {
                return JSON.stringify({error: e.message});
            }
        })()"""

        def on_result(result_str):
            if self._cancelled:
                return
            if not result_str:
                self.scrape_error.emit("JS提取返回空")
                return
            import json
            try:
                data = json.loads(result_str)
            except json.JSONDecodeError:
                self.scrape_error.emit(f"JS结果JSON解析失败: {result_str[:100]}")
                return
            if "error" in data:
                self.scrape_error.emit(data["error"])
                return

            rows = self._extract_table_rows(data)
            self._all_rows.extend(rows)
            self._current_page = data.get("current_page", 1)
            self._total_pages = data.get("total_pages", 1)

            logger.info(
                "CDE列表页解析成功: 第%d/%d页, 新增 %d 条记录",
                self._current_page, self._total_pages, len(rows),
            )

            self.page_parsed.emit(self._current_page, self._total_pages, rows)
            self.scrape_progress.emit(self._current_page, self._total_pages)

            if self._cancelled:
                return

            if self._current_page < self._total_pages and self._scrape_all:
                import random
                delay = random.randint(2000, 4000)
                next_url = self._build_next_page_url(url, self._current_page + 1)
                QTimer.singleShot(delay, lambda: self._load_page(next_url))
            else:
                self.scrape_complete.emit(list(self._all_rows))

        page.runJavaScript(js_code, 0, on_result)

    def _extract_table_rows(self, data: dict) -> list:
        """Extract row dicts from JS result dict. Override in tests for mocking."""
        return data.get("rows", [])

    def _build_next_page_url(self, current_url: str, page: int) -> str:
        """Build next page URL by replacing or appending pageNum param."""
        import urllib.parse as parse
        parsed = parse.urlparse(current_url)
        params = parse.parse_qs(parsed.query)
        params["pageNum"] = [str(page)]
        new_query = parse.urlencode(params, doseq=True)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"

    # ─────────────────────────────────────────────────────────────
    # Detail page parsing
    # ─────────────────────────────────────────────────────────────

    def parse_detail_pages(self, detail_urls: List[str]):
        """Parse PDF links from CDE detail pages."""
        if not detail_urls:
            return

        self._cancelled = False
        self._detail_queue = list(detail_urls)
        self._detail_results = {}
        self._active_detail_pages = []

        logger.info("开始解析CDE详情页: %d 个", len(detail_urls))
        self._start_next_detail_batch()

    def _start_next_detail_batch(self):
        """Fill active detail page slots up to CDE_DETAIL_MAX_CONCURRENT."""
        from core.constants import CDE_DETAIL_MAX_CONCURRENT
        while (
            len(self._active_detail_pages) < CDE_DETAIL_MAX_CONCURRENT
            and self._detail_queue
            and not self._cancelled
        ):
            url = self._detail_queue.pop(0)
            self._load_detail_page(url)

    def _load_detail_page(self, url: str, _retry: int = 0):
        """Load a single detail page and extract PDF links."""
        from core.constants import CDE_PAGE_TIMEOUT

        page = QWebEnginePage(self._profile, self)
        timer = QTimer(self)
        timer.setSingleShot(True)

        entry = {"page": page, "url": url, "timer": timer}
        self._active_detail_pages.append(entry)

        def on_load_finished(ok):
            timer.stop()
            if self._cancelled:
                self._finish_detail_page(entry, None, "cancelled")
                return
            if not ok:
                if _retry == 0:
                    logger.info("CDE详情页首次加载失败，重试: %s", url)
                    self._active_detail_pages.remove(entry)
                    page.deleteLater()
                    QTimer.singleShot(2000, lambda: self._load_detail_page(url, _retry=1))
                    return
                logger.warning("CDE详情页加载失败(已重试): %s", url)
                self._finish_detail_page(entry, None, "load failed")
                return
            QTimer.singleShot(2000, lambda: self._extract_detail_pdf_links(entry))

        def on_timeout():
            if _retry == 0:
                logger.info("CDE详情页首次加载超时，重试: %s", url)
                page.stop()
                self._active_detail_pages.remove(entry)
                page.deleteLater()
                timer.stop()
                QTimer.singleShot(2000, lambda: self._load_detail_page(url, _retry=1))
                return
            logger.warning("CDE详情页加载超时(已重试): %s", url)
            page.stop()
            self._finish_detail_page(entry, None, "timeout")

        page.loadFinished.connect(on_load_finished)
        timer.timeout.connect(on_timeout)
        timer.start(CDE_PAGE_TIMEOUT * 1000)
        page.load(QUrl(url))

    def _extract_detail_pdf_links(self, entry: dict):
        """Extract 审评报告 and 说明书 PDF links from detail page."""
        page = entry["page"]
        url = entry["url"]

        js_code = """(function() {
            try {
                var pdfLinks = {};
                var allLinks = document.querySelectorAll('a[href*=".pdf"], a[href*=".PDF"]');
                allLinks.forEach(function(link) {
                    var href = link.getAttribute('href') || '';
                    var text = link.textContent.trim();
                    if (text.includes('审评报告') || text.includes('review')) {
                        pdfLinks.review_report = href;
                    }
                    if (text.includes('说明书') || text.includes('insert') || text.includes('label')) {
                        pdfLinks.instructions = href;
                    }
                });
                allLinks.forEach(function(link) {
                    var href = link.getAttribute('href') || '';
                    if (!pdfLinks.review_report && (href.includes('reviewReport') || href.includes('审评报告'))) {
                        pdfLinks.review_report = href;
                    }
                    if (!pdfLinks.instructions && (href.includes('instructions') || href.includes('说明书'))) {
                        pdfLinks.instructions = href;
                    }
                });
                return JSON.stringify(pdfLinks);
            } catch(e) {
                return JSON.stringify({error: e.message});
            }
        })()"""

        def on_result(result_str):
            if self._cancelled:
                self._finish_detail_page(entry, None, "cancelled")
                return
            import json
            try:
                data = json.loads(result_str)
            except json.JSONDecodeError:
                self._finish_detail_page(entry, None, "invalid JSON")
                return

            pdf_urls = [v for v in data.values() if v and isinstance(v, str)]
            self._finish_detail_page(entry, {"pdf_urls": pdf_urls, "meta": {}}, None)

        page.runJavaScript(js_code, 0, on_result)

    def _finish_detail_page(self, entry: dict, data: Optional[dict], error: Optional[str]):
        """Handle completion of a single detail page."""
        url = entry["url"]
        if error:
            logger.warning("CDE详情页解析失败: %s, 原因: %s", url, error)
            self.detail_error.emit(url, error)
        else:
            logger.info("CDE详情页解析成功: %s", url)
            self.detail_parsed.emit(url, data)

        self._detail_results[url] = data

        entry["page"].deleteLater()
        entry["timer"].stop()
        if entry in self._active_detail_pages:
            self._active_detail_pages.remove(entry)

        if not self._active_detail_pages and not self._detail_queue:
            logger.info("CDE详情页解析全部完成: %d 个", len(self._detail_results))
        else:
            self._start_next_detail_batch()