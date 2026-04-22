#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDA Tab — standalone openFDA search and review document download.
No dependency on database, CtrdataBridge, or trial data.
"""

import logging
import os
import threading
import webbrowser

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
    QDateEdit,
    QMenu,
)
from PySide6.QtCore import Qt, Signal, QDate

from ui.widgets.card import CollapsibleCard
from ui.widgets.filter_table import FilterTableView
from ui.widgets.progress import ProgressPanel
from ui.theme import SPACING
from core.constants import (
    FDA_APPLICATION_TYPES,
    FDA_SEARCH_ROUTES,
    FDA_REVIEW_PRIORITIES,
    FDA_SUBMISSION_CLASSES,
    FDA_REVIEW_DOC_TYPES,
)

logger = logging.getLogger(__name__)


class FdaTab(QWidget):
    """Standalone FDA review document search and download tab."""

    # Signals for thread-safe communication
    _search_complete = Signal(dict)
    _search_error = Signal(str)
    _download_progress = Signal(int, int, str)
    _download_complete = Signal(dict)
    _download_error = Signal(str)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._service = None
        self._cancel_flag = False
        self._current_params = {}
        self._current_skip = 0
        self._current_total = 0
        self._all_rows = []

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING["md"])

        self._build_search_area(layout)
        self._build_result_table(layout)
        self._build_action_bar(layout)

        # Signal connections
        self._search_complete.connect(self._on_search_complete)
        self._search_error.connect(self._on_search_error)
        self._download_progress.connect(self._on_download_progress)
        self._download_complete.connect(self._on_download_complete)
        self._download_error.connect(self._on_download_error)

        # Right-click context menu on table
        self.table.context_menu_requested.connect(self._on_table_context_menu)

    # ================================================================
    # Search area
    # ================================================================

    @staticmethod
    def _make_date_edit():
        """Create QDateEdit with calendar popup and clear button.

        Uses minimum date (2000-01-01) as 'empty' sentinel.
        specialValueText makes it display blank when at minimum.
        """
        _EMPTY = QDate(2000, 1, 1)
        de = QDateEdit()
        de.setCalendarPopup(True)
        de.setDisplayFormat("yyyy-MM-dd")
        de.setMinimumDate(_EMPTY)
        de.setSpecialValueText(" ")
        de.setDate(_EMPTY)
        de.setFixedSize(120, 30)

        clear = QPushButton("\u00d7")
        clear.setFixedSize(22, 22)
        clear.setToolTip("清除日期")
        clear.clicked.connect(lambda: de.setDate(_EMPTY))

        return de, clear

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
        self.date_from, clear_from = self._make_date_edit()
        search_row.addWidget(self.date_from)
        search_row.addWidget(clear_from)

        search_row.addWidget(QLabel("到:"))
        self.date_to, clear_to = self._make_date_edit()
        search_row.addWidget(self.date_to)
        search_row.addWidget(clear_to)

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

        action_row.addWidget(QLabel("保存目录:"))
        self.save_dir_input = QLineEdit()
        self.save_dir_input.setPlaceholderText("选择保存目录")
        self.save_dir_input.setReadOnly(True)
        action_row.addWidget(self.save_dir_input, stretch=1)

        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.clicked.connect(self._browse_save_dir)
        action_row.addWidget(self.browse_btn)

        self.download_btn = QPushButton("批量下载")
        self.download_btn.setObjectName("primary")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._start_download)
        action_row.addWidget(self.download_btn)

        parent_layout.addLayout(action_row)

        # Progress panel
        self.progress = ProgressPanel()
        parent_layout.addWidget(self.progress)
        self.progress.cancelled.connect(self._cancel_download)

        # Load saved directory from QSettings
        self._load_save_dir()

    # ================================================================
    # Search logic
    # ================================================================

    def _collect_params(self) -> dict:
        """Gather search params from UI fields."""
        params = {"drug_name": self.drug_input.text().strip()}

        # Dates — only include if set (year > 2000 avoids the QDate() default)
        df = self.date_from.date()
        if df.isValid() and df.year() > 2000:
            params["date_from"] = df.toString("yyyy-MM-dd")
        dt = self.date_to.date()
        if dt.isValid() and dt.year() > 2000:
            params["date_to"] = dt.toString("yyyy-MM-dd")

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
        self.search_btn.setEnabled(True)
        rows = result.get("rows", [])
        self._current_total = result.get("total", 0)

        if not rows and self._current_total == 0:
            self.result_label.setText("未找到结果")
            self.table.set_data([], [])
            self._all_rows = []
            return
        elif not rows:
            self.result_label.setText("当前页无审评文档结果")
            self.table.set_data([], [])
            self._all_rows = []
            self._update_page_label()
            return

        # Map to table data
        columns = [
            "药物名", "通用名", "申请号", "厂商",
            "提交类型", "提交日期", "文档类型",
        ]
        data = []
        for r in rows:
            doc_type = r.get("doc_type", "")
            doc_type_cn = FDA_REVIEW_DOC_TYPES.get(doc_type, doc_type)
            data.append([
                r.get("brand_name", ""),
                r.get("generic_name", ""),
                r.get("application_number", ""),
                r.get("manufacturer_name", ""),
                r.get("submission_type", ""),
                r.get("submission_status_date", ""),
                doc_type_cn,
            ])

        self.table.set_data(columns, data)
        self._all_rows = rows  # store for download
        self._update_page_label()
        self.result_label.setText(f"共 {self._current_total} 条结果")

    def _on_search_error(self, error_msg):
        self.search_btn.setEnabled(True)
        self.result_label.setText("搜索失败")
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
        self.date_from.setDate(QDate(2000, 1, 1))
        self.date_to.setDate(QDate(2000, 1, 1))
        self.manufacturer_input.clear()
        self.pharm_class_input.clear()
        self.route_combo.setCurrentIndex(0)
        self.app_type_combo.setCurrentIndex(0)
        self.priority_combo.setCurrentIndex(0)
        self.submission_class_combo.setCurrentIndex(0)

    # ================================================================
    # Download logic
    # ================================================================

    def _update_selected_count(self):
        count = len(self.table.checked_rows())
        self.selected_label.setText(f"已选 {count} 条")
        self.download_btn.setEnabled(count > 0)

    def _browse_save_dir(self):
        from ui.app import get_settings
        current = self.save_dir_input.text()
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", current)
        if path:
            self.save_dir_input.setText(path)
            s = get_settings()
            s.setValue("fda/save_dir", path)

    def _load_save_dir(self):
        from ui.app import get_settings
        s = get_settings()
        saved = s.value("fda/save_dir", "")
        if saved and os.path.isdir(saved):
            self.save_dir_input.setText(saved)

    def _start_download(self):
        save_dir = self.save_dir_input.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "提示", "请先选择保存目录")
            return

        checked = self.table.checked_rows()
        if not checked:
            return

        docs = [self._all_rows[i] for i in checked if i < len(self._all_rows)]
        if not docs:
            return

        # Confirm
        msg = (
            f"即将下载 {len(docs)} 个审评文档。\n"
            f"保存到: {save_dir}\n\n确认开始下载？"
        )
        if QMessageBox.question(self, "确认下载", msg) != QMessageBox.Yes:
            return

        self._cancel_flag = False
        self.download_btn.setEnabled(False)
        self.progress.start(len(docs))
        self.progress.set_cancel_enabled(True)

        def _worker():
            try:
                from service.fda_service import FdaSearchService
                svc = FdaSearchService()
                result = svc.download_docs(
                    docs, save_dir,
                    on_progress=lambda c, t, n: self._download_progress.emit(c, t, n),
                    is_cancelled=lambda: self._cancel_flag,
                )
                self._download_complete.emit(result)
            except Exception as e:
                self._download_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_progress(self, current, total, filename):
        self.progress.update_progress(current, total, f"下载 {filename}")

    def _on_download_complete(self, result):
        success = result.get("success", [])
        failed = result.get("failed", [])
        self.progress.finish(
            success=len(success),
            failed=len(failed),
        )
        self.download_btn.setEnabled(True)

        if failed:
            msg = f"下载完成: 成功 {len(success)} 个，失败 {len(failed)} 个\n\n"
            for f in failed[:10]:
                msg += f"  - {f.get('filename', '未知')}: {f.get('error', '未知错误')}\n"
            if len(failed) > 10:
                msg += f"  ... 还有 {len(failed) - 10} 个失败"
            QMessageBox.warning(self, "下载完成（部分失败）", msg)
        else:
            self.app.status.showMessage(f"FDA审评资料下载完成: {len(success)} 个文件")

    def _on_download_error(self, error_msg):
        self.progress.reset()
        self.download_btn.setEnabled(True)
        QMessageBox.critical(self, "下载失败", error_msg)

    def _cancel_download(self):
        self._cancel_flag = True

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
