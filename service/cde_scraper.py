#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CDE list page scraper — uses QWebEnginePage to scrape the CDE marketed drug list.

Must run on the main thread (Qt event loop requirement).

Approach: Load the CDE list page in QWebEngine to pass Ruishu WAF, then call
the page's internal API endpoint via async XMLHttpRequest. The API endpoint is
POST /main/xxgk/getPostMarketList with params: pageSize, pageNum, acceptid, drugname, company.

runJavaScript() cannot resolve Promises, so we use async XHR + global variable polling.
"""

import json
import logging
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

logger = logging.getLogger(__name__)

# API endpoint discovered from page JS: defaultObj.methods.getListDrugInfoList
_API_PATH = "/main/xxgk/getPostMarketList"
_PAGE_SIZE = 10
_POLL_INTERVAL_MS = 200   # polling interval for async XHR result
_MAX_POLL_ATTEMPTS = 30   # 30 * 200ms = 6s max wait


class _SilentPage(QWebEnginePage):
    """QWebEnginePage that suppresses JavaScript console messages from stderr."""

    def javaScriptConsoleMessage(self, level, message, line, sourceId):
        logger.debug("JS [%s:%d] %s", sourceId, line, message)


class CdeListScraper(QObject):
    """Scrape CDE marketed drug list by calling the internal API via QWebEngine.

    Loads the CDE page to establish WAF cookies, then uses fetch() from within
    the page context to call the API endpoint directly.
    """

    page_parsed = Signal(int, int, list)   # current_page, total_pages, rows
    scrape_complete = Signal(list)           # all_rows
    scrape_error = Signal(str)
    scrape_progress = Signal(int, int)       # current_page, total_pages
    detail_parsed = Signal(str, dict)        # detail_url, {pdf_urls: [...], meta: {...}}
    detail_error = Signal(str, str)         # detail_url, error_msg
    detail_complete = Signal(dict)           # {url: data} results summary

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = QWebEngineProfile.defaultProfile()
        self._all_rows: List[dict] = []
        self._current_page = 0
        self._total_pages = 0
        self._cancelled = False
        self._active_page: Optional[QWebEnginePage] = None
        self._page_timer: Optional[QTimer] = None
        self._detail_queue: List[str] = []
        self._detail_results: Dict[str, dict] = {}
        self._active_detail_pages: List[dict] = []
        self._search_params: dict = {}
        self._date_from: str = ""
        self._date_to: str = ""
        self._drug_type: str = ""
        self._apply_type: str = ""
        self._reg_class: str = ""
        self._waf_settled = False
        self._load_attempts = 0

    def scrape(self, keyword: str = "", date_from: str = "", date_to: str = "",
               drug_type: str = "", apply_type: str = "", reg_class: str = ""):
        """Start scraping list pages. Always fetches all pages with early
        termination when date_from is set and all records are too old.

        Args:
            keyword: drug name keyword search
            date_from: start date filter (YYYY-MM-DD), applied client-side
            date_to: end date filter (YYYY-MM-DD), applied client-side
            drug_type: drug type filter, applied client-side
            apply_type: application type filter, applied client-side
            reg_class: registration class filter, applied client-side
        """
        from core.constants import CDE_LIST_URL

        self._cancelled = False
        self._all_rows = []
        self._current_page = 0
        self._total_pages = 0
        self._waf_settled = False
        self._load_attempts = 0

        # Map UI params to API params
        # The API accepts: acceptid, drugname, company
        self._search_params = {
            "drugname": keyword,
            "acceptid": "",
            "company": "",
        }

        # Client-side filters (API does not support these)
        self._date_from = date_from
        self._date_to = date_to
        self._drug_type = drug_type
        self._apply_type = apply_type
        self._reg_class = reg_class

        logger.info("Loading CDE page to establish WAF session: %s", CDE_LIST_URL)
        self._load_waf_page(CDE_LIST_URL)

    def cancel(self):
        """Abort all pending operations."""
        self._cancelled = True
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

    # ─────────────────────────────────────────────────────────────
    # WAF bypass: load page first to get cookies
    # ─────────────────────────────────────────────────────────────

    def _load_waf_page(self, url: str):
        """Load the CDE page to pass Ruishu WAF and establish session cookies."""
        if self._cancelled:
            return

        if self._active_page:
            self._active_page.deleteLater()

        self._active_page = _SilentPage(self._profile, self)

        if self._page_timer:
            self._page_timer.deleteLater()
        self._page_timer = QTimer(self)
        self._page_timer.setSingleShot(True)

        def on_load_finished(ok):
            self._page_timer.stop()
            if self._cancelled:
                return

            if not self._waf_settled:
                # First load might be WAF challenge; wait for re-render
                self._waf_settled = True
                QTimer.singleShot(5000, self._check_waf_and_search)
                return

        def on_timeout():
            logger.warning("CDE page load timeout")
            self.scrape_error.emit("页面加载超时")

        self._page_timer.timeout.connect(on_timeout)
        self._page_timer.start(40000)
        self._active_page.loadFinished.connect(on_load_finished)
        self._active_page.load(url)

    def _check_waf_and_search(self):
        """Verify page is loaded, then start API calls."""
        if self._cancelled:
            return

        # Check if defaultObj exists (indicates real page is loaded, not WAF challenge)
        js = "(function(){ return typeof defaultObj !== 'undefined'; })()"

        def on_check(result):
            if result is True:
                logger.info("CDE page loaded, WAF passed. Starting API search.")
                self._fetch_page(1)
            else:
                self._load_attempts += 1
                if self._load_attempts >= 3:
                    logger.error("CDE page failed to load after %d attempts", self._load_attempts)
                    self.scrape_error.emit("CDE页面加载失败，无法绕过WAF")
                    return
                logger.info("WAF not settled yet, retrying... (attempt %d)", self._load_attempts)
                # Reload page
                from core.constants import CDE_LIST_URL
                self._waf_settled = False
                self._load_waf_page(CDE_LIST_URL)

        self._active_page.runJavaScript(js, 0, on_check)

    # ─────────────────────────────────────────────────────────────
    # API calls via async XMLHttpRequest + polling
    # ─────────────────────────────────────────────────────────────

    def _fetch_page(self, page_num: int):
        """Call the CDE API via async XMLHttpRequest with result polling.

        runJavaScript() cannot resolve Promises, so fetch() is unusable.
        Synchronous XHR may be blocked by WAF. Instead, we use async XHR,
        store the result in window._cdeApiResponse, and poll for completion.
        """
        if self._cancelled:
            return

        params = {
            "pageSize": _PAGE_SIZE,
            "pageNum": page_num,
            "acceptid": self._search_params.get("acceptid", ""),
            "drugname": self._search_params.get("drugname", ""),
            "company": self._search_params.get("company", ""),
        }
        params_json = json.dumps(params, ensure_ascii=False)

        js_code = f"""(function() {{
            window._cdeApiResponse = null;
            window._cdeApiError = null;
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open("POST", "{_API_PATH}", true);
                xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
                xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
                xhr.onreadystatechange = function() {{
                    if (xhr.readyState === 4) {{
                        if (xhr.status === 200) {{
                            window._cdeApiResponse = xhr.responseText;
                        }} else {{
                            window._cdeApiError = "HTTP " + xhr.status + ": " + xhr.responseText.substring(0, 200);
                        }}
                    }}
                }};
                xhr.onerror = function() {{
                    window._cdeApiError = "XHR network error";
                }};
                var params = {params_json};
                var parts = [];
                for (var key in params) {{
                    parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(params[key]));
                }}
                xhr.send(parts.join("&"));
                return "sent";
            }} catch(e) {{
                window._cdeApiError = e.message;
                return "error: " + e.message;
            }}
        }})()"""

        def on_sent(result):
            if self._cancelled:
                return
            if result and result.startswith("error:"):
                self.scrape_error.emit(f"API请求发送失败: {result}")
                return
            # XHR sent, start polling
            QTimer.singleShot(_POLL_INTERVAL_MS, lambda: self._poll_api_result(page_num, 0))

        self._active_page.runJavaScript(js_code, 0, on_sent)

    def _poll_api_result(self, page_num: int, attempts: int):
        """Poll window._cdeApiResponse for the async XHR result."""
        if self._cancelled:
            return
        if attempts >= _MAX_POLL_ATTEMPTS:
            self.scrape_error.emit("API请求超时")
            return

        js = """(function() {
            if (window._cdeApiResponse !== null)
                return JSON.stringify({status: "ok", body: window._cdeApiResponse});
            if (window._cdeApiError !== null)
                return JSON.stringify({status: "error", error: window._cdeApiError});
            return JSON.stringify({status: "pending"});
        })()"""

        def on_poll(result_str):
            if self._cancelled:
                return
            try:
                poll_data = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                self.scrape_error.emit("轮询结果解析失败")
                return

            if poll_data.get("status") == "ok":
                self._handle_api_response(poll_data["body"], page_num)
            elif poll_data.get("status") == "error":
                self.scrape_error.emit(f"API请求失败: {poll_data['error']}")
            else:
                QTimer.singleShot(
                    _POLL_INTERVAL_MS,
                    lambda: self._poll_api_result(page_num, attempts + 1),
                )

        self._active_page.runJavaScript(js, 0, on_poll)

    def _handle_api_response(self, result_str: str, page_num: int):
        """Parse and process the API response text."""
        if not result_str:
            self.scrape_error.emit("API返回空")
            return

        try:
            data = json.loads(result_str)
        except json.JSONDecodeError:
            self.scrape_error.emit(f"API返回JSON解析失败: {result_str[:200]}")
            return

        if isinstance(data, dict) and data.get("error"):
            self.scrape_error.emit(data["error"])
            return

        if isinstance(data, dict) and data.get("code") != 200:
            self.scrape_error.emit(f"API错误: {data.get('msg', '未知错误')}")
            return

        self._process_api_response(data, page_num)

    def _process_api_response(self, data: dict, page_num: int):
        """Process the API response and emit signals."""
        api_data = data.get("data", {})
        records = api_data.get("records", [])
        total = api_data.get("total", 0)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE) if total > 0 else 0

        # Map API fields to our internal row format
        rows = []
        for rec in records:
            # Log raw createddate for first page to diagnose date format
            if page_num == 1 and rec == records[0]:
                logger.info("CDE API raw createddate sample: %r (type=%s)",
                            rec.get("createddate"), type(rec.get("createddate")).__name__)

            row = {
                "accept_id": rec.get("acceptid", ""),
                "drug_name": rec.get("drgnamecn", ""),
                "drug_type": rec.get("drugtype", ""),
                "apply_type": rec.get("applytype", ""),
                "reg_class": rec.get("registerkind", ""),
                "company": rec.get("companys", ""),
                "date": self._normalize_date(rec.get("createddate", "")),
                "detail_url": self._build_detail_url(rec.get("acceptidCODE", "")),
            }
            if self._row_matches_filters(row):
                rows.append(row)

        self._all_rows.extend(rows)
        self._current_page = page_num
        self._total_pages = total_pages

        logger.info(
            "CDE API返回成功: 第%d/%d页, 新增 %d 条记录 (总%d条)",
            page_num, total_pages, len(rows), total,
        )

        self.page_parsed.emit(self._current_page, self._total_pages, rows)
        self.scrape_progress.emit(self._current_page, self._total_pages)

        if self._cancelled:
            return

        # Early termination: if date_from is set and ALL records on this page
        # are older than date_from, stop crawling (results are newest-first).
        if self._date_from and records:
            all_too_old = all(
                self._normalize_date(rec.get("createddate", "")) < self._date_from
                for rec in records
            )
            if all_too_old:
                logger.info(
                    "CDE提前终止: 第%d页全部记录早于 %s，停止爬取",
                    page_num, self._date_from,
                )
                self.scrape_complete.emit(list(self._all_rows))
                return

        if self._current_page < self._total_pages:
            import random
            delay = random.randint(2000, 4000)
            next_page = self._current_page + 1
            QTimer.singleShot(delay, lambda: self._fetch_page(next_page))
        else:
            self.scrape_complete.emit(list(self._all_rows))

    @staticmethod
    def _normalize_date(value) -> str:
        """Normalize date value to 'YYYY-MM-DD' string.

        Handles: str with time component, int timestamps, empty/None.
        """
        if not value:
            return ""
        s = str(value).strip()
        if not s:
            return ""
        # Already in YYYY-MM-DD format (possibly with time)
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            return s[:10]
        # Try numeric timestamp (seconds or milliseconds)
        try:
            ts = int(float(s))
            if ts > 1e12:  # milliseconds
                ts = ts // 1000
            from datetime import datetime
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            pass
        return s[:10] if len(s) >= 10 else s

    def _row_matches_filters(self, row: dict) -> bool:
        """Check if a row matches all client-side filters.

        Date strings are in "YYYY-MM-DD" format, so lexicographic comparison works.
        """
        # Date range filter
        date_val = row.get("date", "")
        if self._date_from and date_val < self._date_from:
            return False
        if self._date_to and date_val > self._date_to:
            return False

        # Drug type filter
        if self._drug_type and row.get("drug_type", "") != self._drug_type:
            return False

        # Apply type filter
        if self._apply_type and row.get("apply_type", "") != self._apply_type:
            return False

        # Registration class filter
        if self._reg_class and row.get("reg_class", "") != self._reg_class:
            return False

        return True

    @staticmethod
    def _build_detail_url(acceptid_code: str) -> str:
        """Build detail page URL from acceptidCODE."""
        if not acceptid_code:
            return ""
        return f"https://www.cde.org.cn/main/xxgk/postmarketpage?acceptidCODE={acceptid_code}"

    def _extract_table_rows(self, data: dict) -> list:
        """Extract row dicts from API result. Kept for test compatibility."""
        if "rows" in data:
            return data.get("rows", [])
        return data.get("data", {}).get("records", [])

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

        page = _SilentPage(self._profile, self)
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
            QTimer.singleShot(5000, lambda: self._extract_detail_pdf_links(entry))

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
        page.load(url)

    def _extract_detail_pdf_links(self, entry: dict, _attempt: int = 0):
        """Extract review report and package insert PDF links from detail page.

        CDE detail page uses <a class="textLink"> elements with data-fileid,
        data-acceptid, data-filename attributes. The download URL is:
            {ctx}/xxgk/PostMarketDownload?attidCODE={data-fileid}&tableid={data-acceptid}
        where ctx is typically "https://www.cde.org.cn/main".

        Retries up to 3 times with 3s delay if no attachments found (AJAX loading).
        """
        page = entry["page"]
        url = entry["url"]

        js_code = """(function() {
            try {
                var results = [];
                var ctx = typeof window.ctx !== 'undefined' ? window.ctx : '/main';
                // Ensure absolute URL for Python-side QWebEnginePage.load()
                if (ctx.indexOf('http') !== 0) {
                    ctx = window.location.origin + ctx;
                }

                var links = document.querySelectorAll('a.textLink');
                links.forEach(function(a) {
                    var fileid = a.getAttribute('data-fileid') || '';
                    var acceptid = a.getAttribute('data-acceptid') || '';
                    var filename = a.getAttribute('data-filename') || '';
                    var text = a.textContent.trim();

                    if (!fileid) return;

                    var downloadUrl = ctx + '/xxgk/PostMarketDownload?attidCODE='
                        + encodeURIComponent(fileid) + '&tableid='
                        + encodeURIComponent(acceptid);

                    var docType = 'other';
                    if (text.indexOf('审评报告') >= 0 || filename.indexOf('审评报告') >= 0) {
                        docType = 'review_report';
                    } else if (text.indexOf('说明书') >= 0 || filename.indexOf('说明书') >= 0) {
                        docType = 'instructions';
                    }

                    results.push({
                        url: downloadUrl,
                        filename: filename,
                        doc_type: docType
                    });
                });
                return JSON.stringify(results);
            } catch(e) {
                return JSON.stringify({error: e.message});
            }
        })()"""

        def on_result(result_str):
            if self._cancelled:
                self._finish_detail_page(entry, None, "cancelled")
                return
            try:
                data = json.loads(result_str)
            except json.JSONDecodeError:
                self._finish_detail_page(entry, None, "invalid JSON")
                return

            if isinstance(data, dict) and data.get("error"):
                self._finish_detail_page(entry, None, data["error"])
                return

            # data is a list of {url, filename, doc_type}
            if not isinstance(data, list) or not data:
                if _attempt < 2:
                    logger.info(
                        "CDE详情页未找到附件(attempt=%d)，3s后重试: %s",
                        _attempt + 1, url,
                    )
                    QTimer.singleShot(
                        3000,
                        lambda: self._extract_detail_pdf_links(entry, _attempt + 1),
                    )
                    return
                logger.warning("CDE详情页未找到附件(已重试3次): %s", url)
                self._finish_detail_page(entry, None, "no attachments found")
                return

            logger.info("CDE详情页提取到 %d 个附件: %s", len(data),
                        [d.get("doc_type") for d in data])
            self._finish_detail_page(entry, {"attachments": data}, None)

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
            self.detail_complete.emit(dict(self._detail_results))
        else:
            self._start_next_detail_batch()
