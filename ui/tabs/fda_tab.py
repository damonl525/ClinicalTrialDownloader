#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDA Tab — standalone openFDA search and review document browsing/downloading.
No dependency on database, CtrdataBridge, or trial data.
Documents can be downloaded directly via QWebEngine (bypasses FDA bot detection)
or opened in the user's browser.
"""

import logging
import os
import threading
import webbrowser

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QMessageBox,
    QFileDialog,
    QMenu,
)
from PySide6.QtCore import Qt, Signal

from ui.widgets.card import CollapsibleCard
from ui.widgets.date_edit import DateEdit
from ui.widgets.filter_table import FilterTableView
from ui.widgets.progress import ProgressPanel
from ui.theme import SPACING
from ui.app import get_settings, get_recent_db
from core.constants import (
    DEFAULT_DB_NAME,
    FDA_APPLICATION_TYPES,
    FDA_SEARCH_ROUTES,
    FDA_REVIEW_PRIORITIES,
    FDA_SUBMISSION_CLASSES,
)

logger = logging.getLogger(__name__)


class FdaTab(QWidget):
    """Standalone FDA review document search and browsing tab."""

    # Signals for thread-safe communication
    _search_complete = Signal(dict)
    _search_error = Signal(str)
    _toc_parse_complete = Signal(dict)  # {toc_url: TocPageData | None}
    _toc_parse_error = Signal(str)
    _download_complete = Signal(dict)   # {success: [paths], failed: [{...}]}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._current_params = {}
        self._current_skip = 0
        self._current_total = 0
        self._all_rows = []
        self._downloader = None

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING["md"])

        self._build_search_area(layout)
        self._build_result_table(layout)
        self._build_action_bar(layout)

        # Signal connections
        self._search_complete.connect(self._on_search_complete)
        self._search_error.connect(self._on_search_error)
        self._toc_parse_complete.connect(self._on_toc_parse_complete)
        self._toc_parse_error.connect(self._on_toc_parse_error)
        self._download_complete.connect(self._on_download_complete)

        # Right-click context menu on table
        self.table.context_menu_requested.connect(self._on_table_context_menu)

    # ================================================================
    # Search area
    # ================================================================

    def _build_search_area(self, parent_layout):
        # Main search row
        search_row = QHBoxLayout()
        search_row.setSpacing(SPACING["sm"])

        search_row.addWidget(QLabel("通用名/商品名:"))
        self.drug_input = QLineEdit()
        self.drug_input.setPlaceholderText("输入药物通用名或商品名")
        self.drug_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.drug_input, stretch=2)

        search_row.addWidget(QLabel("日期从:"))
        self.date_from = DateEdit()
        search_row.addWidget(self.date_from)

        search_row.addWidget(QLabel("到:"))
        self.date_to = DateEdit()
        search_row.addWidget(self.date_to)

        self.search_btn = QPushButton("搜索")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self.search_btn)

        self.reset_btn = QPushButton("重置")
        self.reset_btn.clicked.connect(self._do_reset)
        search_row.addWidget(self.reset_btn)

        parent_layout.addLayout(search_row)

        # Advanced filters (collapsible)
        self.advanced_card = CollapsibleCard("高级条件", expanded=False)
        adv_layout = QGridLayout()
        adv_layout.setSpacing(SPACING["sm"])

        adv_layout.addWidget(QLabel("厂商名称:"), 0, 0)
        self.manufacturer_input = QLineEdit()
        self.manufacturer_input.setPlaceholderText("如: Merck")
        adv_layout.addWidget(self.manufacturer_input, 0, 1)

        adv_layout.addWidget(QLabel("给药途径:"), 0, 2)
        self.route_combo = QComboBox()
        for label, val in FDA_SEARCH_ROUTES.items():
            self.route_combo.addItem(label, val)
        adv_layout.addWidget(self.route_combo, 0, 3)

        adv_layout.addWidget(QLabel("药学分类:"), 1, 0)
        self.pharm_class_input = QLineEdit()
        self.pharm_class_input.setPlaceholderText("如: Kinase Inhibitor")
        adv_layout.addWidget(self.pharm_class_input, 1, 1)

        adv_layout.addWidget(QLabel("申请类型:"), 1, 2)
        self.app_type_combo = QComboBox()
        for label, val in FDA_APPLICATION_TYPES.items():
            self.app_type_combo.addItem(label, val)
        adv_layout.addWidget(self.app_type_combo, 1, 3)

        adv_layout.addWidget(QLabel("审评优先级:"), 2, 0)
        self.priority_combo = QComboBox()
        for label, val in FDA_REVIEW_PRIORITIES.items():
            self.priority_combo.addItem(label, val)
        adv_layout.addWidget(self.priority_combo, 2, 1)

        adv_layout.addWidget(QLabel("提交类别:"), 2, 2)
        self.submission_class_combo = QComboBox()
        for label, val in FDA_SUBMISSION_CLASSES.items():
            self.submission_class_combo.addItem(label, val)
        adv_layout.addWidget(self.submission_class_combo, 2, 3)

        self.advanced_card.set_body_layout(adv_layout)
        parent_layout.addWidget(self.advanced_card)

    # ================================================================
    # Result table
    # ================================================================

    def _build_result_table(self, parent_layout):
        self.result_label = QLabel("输入药物名称搜索 FDA 审评资料")
        self.result_label.setStyleSheet("color: #64748B;")
        parent_layout.addWidget(self.result_label)

        self.table = FilterTableView()
        parent_layout.addWidget(self.table, stretch=1)

        # Pagination row
        page_row = QHBoxLayout()
        self.page_label = QLabel("")
        self.page_label.setStyleSheet("color: #64748B;")
        page_row.addWidget(self.page_label)
        page_row.addStretch()
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._prev_page)
        page_row.addWidget(self.prev_btn)
        self.next_btn = QPushButton("下一页")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._next_page)
        page_row.addWidget(self.next_btn)
        parent_layout.addLayout(page_row)

    # ================================================================
    # Action bar
    # ================================================================

    def _build_action_bar(self, parent_layout):
        # Save path row
        path_row = QHBoxLayout()
        path_row.setSpacing(SPACING["sm"])

        path_row.addWidget(QLabel("保存到:"))
        default_dir = self._get_default_save_dir()
        self.save_path_input = QLineEdit(default_dir)
        path_row.addWidget(self.save_path_input)

        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.setObjectName("secondary")
        self.browse_btn.clicked.connect(self._browse_save_path)
        path_row.addWidget(self.browse_btn)

        parent_layout.addLayout(path_row)

        # Action buttons row
        action_row = QHBoxLayout()
        action_row.setSpacing(SPACING["sm"])

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.table.check_all)
        action_row.addWidget(self.select_all_btn)

        self.unselect_all_btn = QPushButton("取消全选")
        self.unselect_all_btn.clicked.connect(self.table.uncheck_all)
        action_row.addWidget(self.unselect_all_btn)

        self.selected_label = QLabel("已选 0 条")
        self.selected_label.setStyleSheet("color: #64748B;")
        action_row.addWidget(self.selected_label)
        self.table.checked_changed.connect(self._update_selected_count)

        action_row.addStretch()

        self.download_btn = QPushButton("批量下载")
        self.download_btn.setObjectName("primary")
        self.download_btn.setEnabled(False)
        self.download_btn.setToolTip("下载选中的审评文档 PDF")
        self.download_btn.clicked.connect(self._do_download)
        action_row.addWidget(self.download_btn)

        parent_layout.addLayout(action_row)

        # Progress panel
        self.download_progress = ProgressPanel()
        parent_layout.addWidget(self.download_progress)

    # ================================================================
    # Search logic
    # ================================================================

    def _collect_params(self) -> dict:
        """Gather search params from UI fields."""
        params = {"drug_name": self.drug_input.text().strip()}

        # Dates
        df = self.date_from.date_str()
        if df:
            params["date_from"] = df
        dt = self.date_to.date_str()
        if dt:
            params["date_to"] = dt

        # Advanced
        mfr = self.manufacturer_input.text().strip()
        if mfr:
            params["manufacturer"] = mfr

        route = self.route_combo.currentData()
        if route:
            params["route"] = route

        pc = self.pharm_class_input.text().strip()
        if pc:
            params["pharm_class"] = pc

        app_type = self.app_type_combo.currentData()
        if app_type:
            params["application_type"] = app_type

        priority = self.priority_combo.currentData()
        if priority:
            params["review_priority"] = priority

        sub_class = self.submission_class_combo.currentData()
        if sub_class:
            params["submission_class"] = sub_class

        return params

    def _do_search(self):
        params = self._collect_params()
        if not params.get("drug_name"):
            QMessageBox.warning(self, "提示", "请输入药物通用名或商品名")
            return

        self._current_params = params
        self._current_skip = 0
        self.search_btn.setEnabled(False)
        self.result_label.setText("正在搜索...")
        logger.info("FDA搜索请求: %s", params.get("drug_name", ""))

        def _worker():
            try:
                from service.fda_service import FdaSearchService
                svc = FdaSearchService()
                result = svc.search(params, skip=0)
                self._search_complete.emit(result)
            except Exception as e:
                self._search_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_search_complete(self, result):
        rows = result.get("rows", [])
        self._current_total = result.get("total", 0)

        if not rows and self._current_total == 0:
            self.search_btn.setEnabled(True)
            self.result_label.setText("未找到结果")
            self.table.set_data([], [])
            self._all_rows = []
            return
        elif not rows:
            self.search_btn.setEnabled(True)
            self.result_label.setText("当前页无审评文档结果")
            self.table.set_data([], [])
            self._all_rows = []
            self._update_page_label()
            return

        # Check if any TOC URLs need parsing
        toc_urls = list({
            r["doc_url"] for r in rows
            if r.get("doc_url", "").lower().endswith((".html", ".cfm"))
        })

        logger.info(
            "FDA搜索结果: %d 条API结果, 其中 %d 条含TOC目录",
            self._current_total, len(toc_urls),
        )

        if not toc_urls:
            # No TOC rows — show directly
            self._populate_table(rows)
            self.search_btn.setEnabled(True)
            self.result_label.setText(f"共 {self._current_total} 条结果")
            return

        # Parse TOC pages to determine which PDFs exist
        self.result_label.setText(f"正在解析审评文档目录 (0/{len(toc_urls)})...")
        self._toc_urls = toc_urls
        self._toc_raw_rows = rows

        try:
            from service.fda_toc_parser import FdaTocParser
            self._toc_parser = FdaTocParser(self)
            self._toc_parser.parse_progress.connect(self._on_toc_parse_progress)
            self._toc_parser.parse_complete.connect(self._toc_parse_complete.emit)
            self._toc_parser.parse_error.connect(self._toc_parse_error.emit)
            self._toc_parser.parse(toc_urls)
        except ImportError:
            logger.warning("PySide6-WebEngineWidgets 不可用，使用降级展开")
            self._fallback_expand(rows)

    def _on_toc_parse_progress(self, done, total):
        self.result_label.setText(f"正在解析审评文档目录 ({done}/{total})...")

    def _on_toc_parse_complete(self, toc_data):
        self.search_btn.setEnabled(True)
        from service.fda_service import FdaSearchService
        svc = FdaSearchService()
        expanded = svc.expand_from_pdffiles(self._toc_raw_rows, toc_data)
        shown = self._populate_table(expanded)

        success = sum(1 for v in toc_data.values() if v is not None)
        if shown != self._current_total:
            self.result_label.setText(
                f"共 {self._current_total} 条API结果，解析后 {shown} 条确认文档"
            )
        else:
            self.result_label.setText(f"共 {shown} 条结果")
        logger.info("FDA目录解析完成: 展开为 %d 条确认文档", shown)

    def _on_toc_parse_error(self, error_msg):
        self.search_btn.setEnabled(True)
        logger.warning("FDA目录解析失败: %s", error_msg)
        self._fallback_expand(self._toc_raw_rows)

    def _fallback_expand(self, rows):
        """Fall back to blind 7-suffix expansion when TOC parsing fails."""
        from service.fda_service import FdaSearchService
        svc = FdaSearchService()
        expanded = svc.expand_toc_urls(rows)
        shown = self._populate_table(expanded)
        self.search_btn.setEnabled(True)
        if shown:
            self.result_label.setText(
                f"目录解析失败，已展示 {shown} 条可能的审评文档（部分链接可能不存在）"
            )
        else:
            self.result_label.setText("未找到审评文档")

    def _populate_table(self, rows) -> int:
        """Map row dicts to table data and display. Returns row count."""
        columns = [
            "药物名", "通用名", "申请号", "厂商",
            "提交类型", "提交日期", "文档类型",
        ]
        data = []
        for r in rows:
            data.append([
                r.get("brand_name", ""),
                r.get("generic_name", ""),
                r.get("application_number", ""),
                r.get("manufacturer_name", ""),
                r.get("submission_type", ""),
                r.get("submission_status_date", ""),
                r.get("doc_type", ""),
            ])

        self.table.set_data(columns, data)
        self._all_rows = rows
        self._update_page_label()
        return len(rows)

    def _on_search_error(self, error_msg):
        self.search_btn.setEnabled(True)
        self.result_label.setText("搜索失败")
        logger.error("FDA搜索失败: %s", error_msg)
        QMessageBox.critical(self, "搜索失败", error_msg)

    # -- Pagination --

    def _update_page_label(self):
        shown = self.table.row_count()
        start = self._current_skip + 1
        end = self._current_skip + shown
        self.page_label.setText(
            f"第 {start}-{end} 条，共 {self._current_total} 条"
        )
        self.prev_btn.setEnabled(self._current_skip > 0)
        self.next_btn.setEnabled(end < self._current_total)

    def _prev_page(self):
        if self._current_skip >= 100:
            self._current_skip -= 100
        else:
            self._current_skip = 0
        self._fetch_page()

    def _next_page(self):
        self._current_skip += 100
        self._fetch_page()

    def _fetch_page(self):
        self.search_btn.setEnabled(False)
        self.result_label.setText("正在加载...")
        self.table.uncheck_all()  # Clear selections from previous page

        def _worker():
            try:
                from service.fda_service import FdaSearchService
                svc = FdaSearchService()
                result = svc.search(self._current_params, skip=self._current_skip)
                self._search_complete.emit(result)
            except Exception as e:
                self._search_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    # -- Reset --

    def _do_reset(self):
        self.drug_input.clear()
        self.date_from.clear()
        self.date_to.clear()
        self.manufacturer_input.clear()
        self.pharm_class_input.clear()
        self.route_combo.setCurrentIndex(0)
        self.app_type_combo.setCurrentIndex(0)
        self.priority_combo.setCurrentIndex(0)
        self.submission_class_combo.setCurrentIndex(0)

    # ================================================================
    # Action logic
    # ================================================================

    def _update_selected_count(self):
        count = len(self.table.checked_rows())
        self.selected_label.setText(f"已选 {count} 条")
        self.download_btn.setEnabled(count > 0)

    def _open_in_browser(self):
        """Open selected document URLs in browser tabs."""
        checked = self.table.checked_rows()
        if not checked:
            return

        docs = [self._all_rows[i] for i in checked if i < len(self._all_rows)]
        urls = [d.get("doc_url", "") for d in docs if d.get("doc_url")]
        if not urls:
            QMessageBox.information(self, "提示", "选中的文档没有可用的链接")
            return

        # Confirm before opening many tabs
        if len(urls) > 3:
            msg = (
                f"即将在浏览器中打开 {len(urls)} 个标签页。\n\n"
                f"提示: FDA 审评文档为 PDF 格式，可在浏览器中直接保存。\n\n确认打开？"
            )
            if QMessageBox.question(self, "确认打开", msg) != QMessageBox.Yes:
                return

        opened = 0
        for url in urls:
            if webbrowser.open(url):
                opened += 1

        logger.info("FDA: 在浏览器中打开 %d 个审评文档", opened)
        self.app.status.showMessage(f"已在浏览器中打开 {opened} 个审评文档")

    # ================================================================
    # Download logic
    # ================================================================

    def _get_default_save_dir(self) -> str:
        """Get default download directory: QSettings > DB directory."""
        settings = get_settings()
        saved = settings.value("fda/download_path", "")
        if saved and os.path.isdir(saved):
            return saved
        db_path = get_recent_db() or DEFAULT_DB_NAME
        return os.path.dirname(os.path.abspath(db_path))

    def _do_download(self):
        """Start downloading selected documents."""
        checked = self.table.checked_rows()
        if not checked:
            return

        docs = [self._all_rows[i] for i in checked if i < len(self._all_rows)]
        docs = [d for d in docs if d.get("doc_url", "")]
        if not docs:
            QMessageBox.information(self, "提示", "选中的文档没有可用的链接")
            return

        save_dir = self.save_path_input.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "提示", "请先设置保存路径")
            return

        # Confirm
        msg = (
            f"即将下载 {len(docs)} 个审评文档 PDF。\n"
            f"保存到: {save_dir}\n\n确认开始下载？"
        )
        if QMessageBox.question(self, "确认下载", msg) != QMessageBox.Yes:
            return

        # Save to QSettings for next time
        get_settings().setValue("fda/download_path", save_dir)

        # Start download
        self.download_btn.setEnabled(False)
        self.search_btn.setEnabled(False)

        self.download_progress.start(len(docs))
        self.download_progress.set_cancel_enabled(True)
        self.download_progress.cancelled.connect(self._cancel_download)
        self._download_start_time = None

        import time
        self._download_start_time = time.time()

        try:
            from service.fda_pdf_downloader import FdaPdfDownloader
            self._downloader = FdaPdfDownloader(self)
            self._downloader.download_progress.connect(self._on_download_progress)
            self._downloader.download_complete.connect(self._download_complete.emit)
            self._downloader.download(docs, save_dir)
            logger.info("开始下载FDA审评文档: %d 个文件", len(docs))
        except ImportError:
            logger.warning("PySide6-WebEngineWidgets 不可用，无法下载")
            self.download_btn.setEnabled(True)
            self.search_btn.setEnabled(True)
            self.download_progress.reset()
            QMessageBox.critical(
                self, "下载失败",
                "PySide6-WebEngineWidgets 未安装，无法下载 FDA 文档。\n"
                "请安装: pip install PySide6-WebEngineWidgets",
            )

    def _browse_save_path(self):
        """Browse for save directory."""
        current = self.save_path_input.text().strip() or self._get_default_save_dir()
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", current)
        if path:
            self.save_path_input.setText(path)

    def _cancel_download(self):
        """Cancel active download."""
        self.download_progress.set_cancel_enabled(False)
        self.download_progress.update_progress(0, 0, "正在取消...")
        if self._downloader:
            self._downloader.cancel()

    def _on_download_progress(self, current: int, total: int, filename: str):
        self.download_progress.update_progress(
            current, total, f"正在下载 {filename} ({current}/{total})"
        )
        # Show ETA after 2+ items
        if current >= 2 and self._download_start_time:
            import time
            elapsed = time.time() - self._download_start_time
            per_item = elapsed / current
            remaining = per_item * (total - current)
            self.download_progress.update_eta(elapsed, remaining)

        logger.info("FDA文档下载进度: %d/%d - %s", current, total, filename)

    def _on_download_complete(self, results: dict):
        self.download_btn.setEnabled(True)
        self.search_btn.setEnabled(True)

        # Disconnect cancel signal
        try:
            self.download_progress.cancelled.disconnect(self._cancel_download)
        except RuntimeError:
            pass

        success = results.get("success", [])
        failed = results.get("failed", [])
        skipped = sum(1 for s in success if "(跳过)" in s or os.path.exists(s))

        self.download_progress.finish(
            success=len(success), failed=len(failed),
        )

        if not failed:
            self.result_label.setText(
                f"下载完成: {len(success)} 个文件已保存"
            )
            self.app.status.showMessage(f"已下载 {len(success)} 个 FDA 审评文档")
        else:
            self.result_label.setText(
                f"下载完成: {len(success)} 成功, {len(failed)} 失败"
            )
            errors = "\n".join(
                f"• {f.get('filename', '未知')}: {f.get('error', '未知错误')}"
                for f in failed[:10]
            )
            QMessageBox.warning(
                self, "部分下载失败",
                f"成功: {len(success)} 个\n"
                f"失败: {len(failed)} 个\n\n"
                f"失败详情:\n{errors}",
            )

    # ================================================================
    # Right-click context menu
    # ================================================================

    def _on_table_context_menu(self, source_row: int, global_pos):
        """Show context menu for right-clicked row."""
        if source_row >= len(self._all_rows):
            return

        row_data = self._all_rows[source_row]
        url = row_data.get("doc_url", "")

        menu = QMenu(self)

        # Open in browser
        open_action = menu.addAction("在浏览器中打开")
        open_action.setEnabled(bool(url))

        # Check/uncheck row
        is_checked = source_row in self.table.checked_rows()
        toggle_text = "取消勾选" if is_checked else "勾选此行"
        toggle_action = menu.addAction(toggle_text)

        chosen = menu.exec(global_pos)
        if chosen == open_action and url:
            webbrowser.open(url)
        elif chosen == toggle_action:
            self.table.set_check_state(source_row, not is_checked)
