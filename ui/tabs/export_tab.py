#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 3: Extract & Export — extract with f.* functions, filter, preview, export CSV, download docs.
"""

import os
import re
import threading
import time
import webbrowser
import logging

import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QFrame, QFileDialog,
    QSizePolicy, QComboBox, QHeaderView, QMessageBox, QMenu,
    QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont

from ui.theme import get_font, SPACING

logger = logging.getLogger(__name__)
from ui.widgets.card import CollapsibleCard
from ui.widgets.date_edit import DateEdit
from ui.widgets.progress import ProgressPanel
from ui.widgets.table_model import PandasTableModel
from core.constants import (
    CONCEPT_FUNCTIONS, DEFAULT_CONCEPTS, TREEVIEW_DISPLAY_LIMIT,
    DOC_TYPE_OPTIONS, FILTER_PHASES, FILTER_STATUSES,
)
from service.extract_service import ExtractService

try:
    from PySide6.QtWidgets import QTableView
except ImportError:
    pass


class DocResultDialog(QMessageBox):
    """Document download result dialog with collapsible details."""

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文档下载完成")

        success = result.get("success", [])
        if isinstance(success, str): success = [success]
        failed = result.get("failed", {})
        skipped = result.get("skipped", {})
        fail_count = len(failed) if isinstance(failed, dict) else 0
        skip_count = len(skipped) if isinstance(skipped, dict) else 0
        total = len(success) + skip_count + fail_count

        if not success and fail_count > 0:
            self.setIcon(QMessageBox.Critical)
        elif fail_count > 0 or skip_count > 0:
            self.setIcon(QMessageBox.Warning)
        else:
            self.setIcon(QMessageBox.Information)

        # Summary
        summary_parts = [f"处理试验: {total} 个", f"成功下载: {len(success)} 个"]
        if skip_count:
            summary_parts.append(f"跳过: {skip_count} 个")
        if fail_count:
            summary_parts.append(f"失败: {fail_count} 个")
        self.setText("本次下载:\n  " + "\n  ".join(summary_parts))

        # Detail sections
        details = []

        # Success list
        if success:
            lines = [f"成功下载的试验 ({len(success)} 个):"]
            for tid in success[:50]:
                lines.append(f"  {tid}")
            if len(success) > 50:
                lines.append(f"  ... 及其他 {len(success) - 50} 个")
            details.append("\n".join(lines))

        # Skipped
        if isinstance(skipped, dict) and skipped:
            lines = ["以下试验文档已存在，跳过下载:"]
            for tid, reason in list(skipped.items())[:50]:
                lines.append(f"  {tid}: {reason}")
            if len(skipped) > 50:
                lines.append(f"  ... 及其他 {len(skipped) - 50} 个")
            details.append("\n".join(lines))

        # Failed
        if isinstance(failed, dict) and failed:
            lines = ["以下试验下载失败:"]
            for tid, err in list(failed.items())[:50]:
                lines.append(f"  {tid}: {err}")
            if len(failed) > 50:
                lines.append(f"  ... 及其他 {len(failed) - 50} 个")
            details.append("\n".join(lines))

        if details:
            self.setDetailedText("\n\n".join(details))
            # Auto-expand details
            self.addButton(QMessageBox.Ok)

    def showEvent(self, event):
        super().showEvent(event)
        # Auto-click the "Show Details" button
        for btn in self.buttons():
            text = btn.text().lower()
            if "detail" in text or "显示" in text or "详情" in text:
                btn.click()
                break


class ExportTab(QWidget):
    """Extract, filter, preview, and export tab."""

    # Thread-safe signals
    _extract_complete = Signal(object)  # DataFrame
    _extract_error = Signal(str)
    _doc_progress = Signal(int, int, str, str, str)  # current, total, trial_id, status, detail
    _doc_complete = Signal(dict)
    _doc_error = Signal(str)
    _fields_loaded = Signal(list)   # loaded field names from background thread
    _log_signal = Signal(str, str)  # level, message

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.app = main_window
        self._full_df: pd.DataFrame = None
        self._current_page = 1
        self._total_pages = 1
        self._last_docs_regexp = None
        self._is_extracting = False
        self._doc_start_time = None
        self._setup_ui()

        # Connect signals
        self._extract_complete.connect(self._on_extract_complete)
        self._extract_error.connect(self._on_extract_error)
        self._doc_progress.connect(self._on_doc_progress)
        self._doc_complete.connect(self._on_doc_complete)
        self._doc_error.connect(self._on_doc_error)
        self._fields_loaded.connect(self._on_fields_loaded)
        self._log_signal.connect(self._on_log_signal)

    def _make_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        return frame

    def _setup_ui(self):
        # Wrap entire tab content in a QScrollArea so expanding
        # collapsible panels pushes content down / makes it scrollable
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(SPACING["md"])

        # ── Data scope selector ──
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("数据范围:"))
        self.scope_current_rb = QCheckBox("仅本次搜索结果")
        self.scope_current_rb.setChecked(True)
        self.scope_current_rb.toggled.connect(self._on_current_scope_toggled)
        scope_row.addWidget(self.scope_current_rb)
        self.scope_count_label = QLabel("(0 条)")
        self.scope_count_label.setStyleSheet("color: #64748B;")
        scope_row.addWidget(self.scope_count_label)

        self.scope_all_rb = QCheckBox("全部数据库")
        self.scope_all_rb.toggled.connect(self._on_all_scope_toggled)
        scope_row.addWidget(self.scope_all_rb)
        self.scope_db_count_label = QLabel("(0 条)")
        self.scope_db_count_label.setStyleSheet("color: #64748B;")
        scope_row.addWidget(self.scope_db_count_label)
        scope_row.addStretch()
        layout.addLayout(scope_row)

        # ── Card: Advanced options (concept functions + fields) ──
        self._adv_card = CollapsibleCard("高级选项（标准化函数、数据库字段）", expanded=False)
        adv_layout = QVBoxLayout()

        # Concept functions
        adv_layout.addWidget(QLabel("标准化函数 (f.*):"))
        concepts_row = QHBoxLayout()
        concepts_row.setSpacing(SPACING["sm"])
        self.concept_checks = {}
        for func_key, info in CONCEPT_FUNCTIONS.items():
            label = info[0] if isinstance(info, tuple) else info
            cb = QCheckBox(label)
            cb.setChecked(func_key in DEFAULT_CONCEPTS)
            cb.setToolTip(
                f"{func_key}\n"
                "ctrdata 提供的标准化函数，将不同注册中心的字段映射为统一格式。"
            )
            self.concept_checks[func_key] = cb
            concepts_row.addWidget(cb)
        concepts_row.addStretch()
        adv_layout.addLayout(concepts_row)

        # DB fields
        fields_row = QHBoxLayout()
        fields_row.setSpacing(SPACING["sm"])
        fields_row.addWidget(QLabel("数据库字段:"))
        self.fields_btn = QPushButton("刷新字段列表")
        self.fields_btn.setObjectName("secondary")
        self.fields_btn.clicked.connect(self._refresh_fields)
        fields_row.addWidget(self.fields_btn)
        self.fields_status = QLabel("请先连接数据库")
        self.fields_status.setStyleSheet("color: #64748B;")
        fields_row.addWidget(self.fields_status)
        fields_row.addStretch()
        adv_layout.addLayout(fields_row)

        self._fields_container = QVBoxLayout()
        adv_layout.addLayout(self._fields_container)

        self._adv_card.set_body_layout(adv_layout)
        layout.addWidget(self._adv_card)

        # ── Collapsible filter panel ──
        self._filter_card = CollapsibleCard("过滤条件（可选，点击展开）", expanded=False)
        filter_layout = QVBoxLayout()

        f_row1 = QHBoxLayout()
        f_row1.setSpacing(SPACING["sm"])
        f_row1.addWidget(QLabel("注册中心:"))
        self.register_combo = QComboBox()
        self.register_combo.addItem("全部")
        from core.constants import SUPPORTED_REGISTERS
        for key, name in SUPPORTED_REGISTERS.items():
            self.register_combo.addItem(key)
        f_row1.addWidget(self.register_combo)
        f_row1.addSpacing(20)
        f_row1.addWidget(QLabel("阶段:"))
        self.phase_combo = QComboBox()
        for label in FILTER_PHASES:
            self.phase_combo.addItem(label)
        f_row1.addWidget(self.phase_combo)
        f_row1.addSpacing(20)
        f_row1.addWidget(QLabel("招募状态:"))
        self.status_combo = QComboBox()
        for label in FILTER_STATUSES:
            self.status_combo.addItem(label)
        f_row1.addWidget(self.status_combo)
        f_row1.addStretch()
        filter_layout.addLayout(f_row1)

        f_row2 = QHBoxLayout()
        f_row2.setSpacing(SPACING["sm"])
        f_row2.addWidget(QLabel("开始日期:"))
        self.date_start_input = DateEdit()
        f_row2.addWidget(self.date_start_input)
        f_row2.addWidget(QLabel("~"))
        self.date_end_input = DateEdit()
        f_row2.addWidget(self.date_end_input)
        f_row2.addSpacing(20)
        f_row2.addWidget(QLabel("适应症:"))
        self.condition_input = QLineEdit()
        self.condition_input.setMaximumWidth(120)
        f_row2.addWidget(self.condition_input)
        f_row2.addSpacing(20)
        f_row2.addWidget(QLabel("干预措施:"))
        self.intervention_input = QLineEdit()
        self.intervention_input.setMaximumWidth(120)
        f_row2.addWidget(self.intervention_input)
        f_row2.addStretch()
        filter_layout.addLayout(f_row2)

        self.dedup_check = QCheckBox("跨注册中心去重")
        self.dedup_check.setChecked(True)
        self.dedup_check.setToolTip(
            "同一试验可能在多个注册中心注册，勾选后将只保留一条记录。"
        )
        filter_layout.addWidget(self.dedup_check)

        self.protocol_only_check = QCheckBox("仅含Protocol文档")
        self.protocol_only_check.setToolTip(
            "提取后仅保留有Protocol（研究方案）文档的试验。\n"
            "基于数据库中的文档元数据过滤，无需额外网络请求。"
        )
        filter_layout.addWidget(self.protocol_only_check)

        self._filter_card.set_body_layout(filter_layout)
        layout.addWidget(self._filter_card)

        # ── Extract buttons ──
        extract_row = QHBoxLayout()
        self.extract_btn = QPushButton("提取数据")
        self.extract_btn.setObjectName("primary")
        self.extract_btn.clicked.connect(self._extract)
        extract_row.addWidget(self.extract_btn)
        self.export_btn = QPushButton("导出 CSV")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self._export_csv)
        extract_row.addWidget(self.export_btn)
        self.extract_info = QLabel("就绪")
        self.extract_info.setStyleSheet("color: #3B82F6;")
        extract_row.addWidget(self.extract_info)
        extract_row.addStretch()
        layout.addLayout(extract_row)

        # ── Extraction progress (below extract row) ──
        self.extract_progress = ProgressPanel()
        layout.addWidget(self.extract_progress)

        # ── Data preview table ──
        preview_card = self._make_card()
        preview_layout = QVBoxLayout(preview_card)

        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("数据预览"))
        preview_header.addStretch()
        self._page_label = QLabel("")
        self._page_label.setStyleSheet("color: #64748B;")
        preview_header.addWidget(self._page_label)
        self._prev_page_btn = QPushButton("◀ 上一页")
        self._prev_page_btn.setObjectName("secondary")
        self._prev_page_btn.setEnabled(False)
        self._prev_page_btn.clicked.connect(self._prev_page)
        preview_header.addWidget(self._prev_page_btn)
        self._next_page_btn = QPushButton("下一页 ▶")
        self._next_page_btn.setObjectName("secondary")
        self._next_page_btn.setEnabled(False)
        self._next_page_btn.clicked.connect(self._next_page)
        preview_header.addWidget(self._next_page_btn)
        preview_layout.addLayout(preview_header)

        from PySide6.QtWidgets import QTableView
        self.table_view = QTableView()
        self.table_view.setMinimumHeight(150)
        self.table_model = PandasTableModel()
        self.table_view.setModel(self.table_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table_view.doubleClicked.connect(self._on_table_double_click)
        preview_layout.addWidget(self.table_view)

        layout.addWidget(preview_card)

        # ── Card: Document download ──
        doc_card = self._make_card()
        doc_layout = QVBoxLayout(doc_card)
        doc_layout.setSpacing(SPACING["sm"])

        doc_layout.addWidget(QLabel("文档下载"))

        # Save path
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("保存到:"))
        from ui.app import get_settings
        _default_doc_path = get_settings().value("doc/default_path", "./documents")
        self.doc_path_input = QLineEdit(_default_doc_path)
        path_row.addWidget(self.doc_path_input)
        self.doc_browse_btn = QPushButton("浏览...")
        self.doc_browse_btn.setObjectName("secondary")
        self.doc_browse_btn.clicked.connect(self._browse_doc_path)
        path_row.addWidget(self.doc_browse_btn)
        doc_layout.addLayout(path_row)

        # Quick buttons
        doc_btn_row = QHBoxLayout()
        self.doc_protocol_btn = QPushButton("下载 Protocol")
        self.doc_protocol_btn.setObjectName("secondary")
        self.doc_protocol_btn.setToolTip("Protocol: 研究方案文档")
        self.doc_protocol_btn.clicked.connect(lambda: self._quick_download("prot"))
        self.doc_protocol_btn.setEnabled(False)
        doc_btn_row.addWidget(self.doc_protocol_btn)

        self.doc_sap_btn = QPushButton("下载 SAP")
        self.doc_sap_btn.setObjectName("secondary")
        self.doc_sap_btn.setToolTip("SAP: 统计分析计划文档")
        self.doc_sap_btn.clicked.connect(lambda: self._quick_download("sap_|statist"))
        self.doc_sap_btn.setEnabled(False)
        doc_btn_row.addWidget(self.doc_sap_btn)

        self.doc_both_btn = QPushButton("Protocol + SAP")
        self.doc_both_btn.setObjectName("secondary")
        self.doc_both_btn.setToolTip("同时下载研究方案和统计分析计划")
        self.doc_both_btn.clicked.connect(lambda: self._quick_download("prot|sap_|statist"))
        self.doc_both_btn.setEnabled(False)
        doc_btn_row.addWidget(self.doc_both_btn)

        self.doc_all_btn = QPushButton("全部文档")
        self.doc_all_btn.setObjectName("secondary")
        self.doc_all_btn.setToolTip("下载所有可用文档（包含知情同意书等）")
        self.doc_all_btn.clicked.connect(lambda: self._quick_download(None))
        self.doc_all_btn.setEnabled(False)
        doc_btn_row.addWidget(self.doc_all_btn)

        doc_layout.addLayout(doc_btn_row)

        self.doc_progress = ProgressPanel()
        doc_layout.addWidget(self.doc_progress)

        self.doc_status = QLabel("请先提取数据")
        self.doc_status.setStyleSheet("color: #64748B;")
        doc_layout.addWidget(self.doc_status)

        layout.addWidget(doc_card)
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

        # Initial scope update
        self.refresh_scope_counts()

    # ── Scope ──

    def _on_current_scope_toggled(self, checked):
        if checked:
            self.scope_all_rb.blockSignals(True)
            self.scope_all_rb.setChecked(False)
            self.scope_all_rb.blockSignals(False)
            self.refresh_scope_counts()
        else:
            # Prevent deselecting both — at least one must stay checked
            if not self.scope_all_rb.isChecked():
                self.scope_current_rb.blockSignals(True)
                self.scope_current_rb.setChecked(True)
                self.scope_current_rb.blockSignals(False)

    def _on_all_scope_toggled(self, checked):
        if checked:
            self.scope_current_rb.blockSignals(True)
            self.scope_current_rb.setChecked(False)
            self.scope_current_rb.blockSignals(False)
            self.refresh_scope_counts()
        else:
            if not self.scope_current_rb.isChecked():
                self.scope_all_rb.blockSignals(True)
                self.scope_all_rb.setChecked(True)
                self.scope_all_rb.blockSignals(False)

    def refresh_scope_counts(self):
        """Update scope count labels — called on tab switch and after download."""
        search_ids = getattr(self.app, 'current_search_ids', None)
        count = len(search_ids) if search_ids else 0
        self.scope_count_label.setText(f"({count} 条)")

        db_count = getattr(self.app, 'db_total_records', "?")
        self.scope_db_count_label.setText(f"({db_count} 条)")

    def _get_scope_ids(self):
        if self.scope_current_rb.isChecked():
            return getattr(self.app, 'current_search_ids', None)
        return None

    # ── Field discovery ──

    def _refresh_fields(self):
        if not self.app.bridge or not self.app.bridge.db_path:
            QMessageBox.warning(self, "提示", "请先连接数据库")
            return
        self.fields_btn.setEnabled(False)
        self.fields_status.setText("加载中...")

        def _worker():
            try:
                fields = self.app.bridge.find_fields(".*")
                self._fields_loaded.emit(fields)
            except Exception:
                self._fields_loaded.emit([])

        threading.Thread(target=_worker, daemon=True).start()

    def _on_fields_loaded(self, fields):
        self.fields_btn.setEnabled(True)
        # Clear old checkboxes
        while self._fields_container.count():
            item = self._fields_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                pass

        if fields:
            row = QHBoxLayout()
            self._field_checks = {}
            for f in sorted(fields)[:30]:  # Limit display
                cb = QCheckBox(f[:50])
                cb.setToolTip(f)
                self._field_checks[f] = cb
                row.addWidget(cb)
            row.addStretch()
            self._fields_container.addLayout(row)
            self.fields_status.setText(f"共 {len(fields)} 个字段 (显示前30)")
        else:
            self.fields_status.setText("无可用字段")

    def _get_selected_fields(self) -> list:
        checks = getattr(self, '_field_checks', {})
        return [f for f, cb in checks.items() if cb.isChecked()]

    # ── Data extraction ──

    def _extract(self):
        if self._is_extracting:
            return
        if not self.app.bridge or not self.app.bridge.db_path:
            QMessageBox.critical(self, "错误", "请先连接数据库")
            return

        scope = "current_search" if self.scope_current_rb.isChecked() else "all"
        if scope == "current_search" and not getattr(self.app, 'current_search_ids', None):
            QMessageBox.warning(
                self, "提示",
                "没有本次搜索结果。请先下载数据，或切换到「全部数据库」。"
            )
            return

        selected_fields = self._get_selected_fields()
        selected_concepts = [k for k, cb in self.concept_checks.items() if cb.isChecked()]

        if not selected_fields and not selected_concepts:
            QMessageBox.warning(
                self, "提示",
                "请至少选择一个标准化函数或数据库字段"
            )
            return

        # Get date values
        ds = self.date_start_input.date_str()
        de = self.date_end_input.date_str()

        dedup = self.dedup_check.isChecked()
        protocol_filter = self.protocol_only_check.isChecked()
        filter_phase = FILTER_PHASES.get(self.phase_combo.currentText(), "")
        filter_status = FILTER_STATUSES.get(self.status_combo.currentText(), "")
        filter_condition = self.condition_input.text().strip()
        filter_intervention = self.intervention_input.text().strip()
        filter_register = self.register_combo.currentText()
        if filter_register == "全部":
            filter_register = ""

        scope_ids = self._get_scope_ids()

        self._is_extracting = True
        self.extract_btn.setEnabled(False)
        self.extract_progress.set_indeterminate()
        self.extract_progress.set_cancel_enabled(True)
        self.extract_progress.cancelled.connect(self._cancel_extract)
        self.extract_progress.update_detail("正在准备提取..." if not protocol_filter else "正在查询 Protocol 文档...")

        def _worker():
            try:
                effective_scope = scope_ids
                # Protocol pre-filter in background thread
                if protocol_filter:
                    self._log_signal.emit("info", "Protocol 预过滤: 查询数据库...")
                    protocol_ids = self.app.bridge.get_protocol_trial_ids(scope_ids)
                    before = len(scope_ids) if scope_ids else int(getattr(self.app, 'db_total_records', 0))
                    self._log_signal.emit("info",
                        f"Protocol过滤: {len(protocol_ids)} 条有文档 (跳过 {before - len(protocol_ids)})")
                    effective_scope = protocol_ids
                    if not effective_scope:
                        self._extract_complete.emit(pd.DataFrame())
                        return

                svc = ExtractService(self.app.bridge)
                df = svc.extract(
                    fields=selected_fields if selected_fields else None,
                    concepts=selected_concepts if selected_concepts else None,
                    deduplicate=dedup,
                    filter_phase=filter_phase,
                    filter_status=filter_status,
                    filter_date_start=ds,
                    filter_date_end=de,
                    filter_condition=filter_condition,
                    filter_intervention=filter_intervention,
                    filter_register=filter_register,
                    scope_ids=effective_scope,
                )
                self._extract_complete.emit(df)
            except Exception as e:
                self._extract_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _cancel_extract(self):
        self.extract_progress.set_cancel_enabled(False)
        self.extract_progress.update_detail("正在取消...")
        self._log("用户取消数据提取")
        self.app.bridge.cancel()
        self._is_extracting = False
        self.extract_progress.reset()
        self.extract_btn.setEnabled(True)
        self.extract_info.setText("已取消")
        self.app.status.showMessage("数据提取已取消")
        try:
            self.extract_progress.cancelled.disconnect(self._cancel_extract)
        except RuntimeError:
            pass

    def auto_extract(self, search_ids: list):
        """Auto-trigger extraction after search download (called by MainWindow)."""
        if self._is_extracting:
            return
        # Set scope to current search results
        self.scope_current_rb.setChecked(True)
        # Propagate Protocol filter from Search Tab
        protocol_requested = getattr(self.app, 'protocol_filter_requested', False)
        if protocol_requested:
            self.protocol_only_check.setChecked(True)
            self._filter_card.header.setChecked(True)
        # Trigger extract with current settings
        self._extract()

    def _on_extract_complete(self, df):
        # If extraction was cancelled, UI is already reset by _cancel_extract
        if not self._is_extracting:
            return
        self._is_extracting = False
        self.extract_progress.finish(success=len(df) if df is not None else 0)
        try:
            self.extract_progress.cancelled.disconnect(self._cancel_extract)
        except RuntimeError:
            pass
        self.extract_btn.setEnabled(True)

        # Handle empty result (e.g., Protocol filter found no matches)
        if df is None or len(df) == 0:
            self.app.current_data = pd.DataFrame()
            self.app.filtered_ids = []
            self.table_model.update_data(pd.DataFrame())
            self._full_df = pd.DataFrame()
            self.extract_info.setText("Protocol 过滤: 没有符合条件的试验")
            self._log("Protocol 过滤: 没有符合条件的试验")
            self.app.status.showMessage("没有含 Protocol 文档的试验")
            self._enable_doc_buttons(False)
            self.doc_status.setText("没有可下载的数据")
            return

        self.app.current_data = df
        try:
            self.extract_progress.cancelled.disconnect(self._cancel_extract)
        except RuntimeError:
            pass
        self.extract_btn.setEnabled(True)

        self.app.current_data = df

        if "_id" in df.columns:
            self.app.filtered_ids = df["_id"].tolist()
        else:
            self.app.filtered_ids = list(range(len(df)))

        # Update table model
        self.table_model.update_data(df)
        self._full_df = df
        self._apply_column_widths(df)
        self._total_pages = max(1, -(-len(df) // TREEVIEW_DISPLAY_LIMIT))
        self._current_page = 1
        self._update_page_controls()

        dedup = self.dedup_check.isChecked()
        info = f"提取完成: {len(df)} 行 × {len(df.columns)} 列"
        if dedup:
            info += " (已去重)"
        self.extract_info.setText(info)
        self._log(info)
        self.app.status.showMessage(f"数据提取成功: {len(df)} 行")
        self.app.update_db_status()

        # Enable doc buttons
        ids = self.app.filtered_ids
        if ids:
            self._enable_doc_buttons(True)
            self.doc_status.setText(f"可为 {len(ids)} 条试验下载文档")
        else:
            self._enable_doc_buttons(False)
            self.doc_status.setText("没有可下载的数据")

    def _on_extract_error(self, error_msg):
        if not self._is_extracting:
            return
        self._is_extracting = False
        self.extract_progress.reset()
        try:
            self.extract_progress.cancelled.disconnect(self._cancel_extract)
        except RuntimeError:
            pass
        self.extract_btn.setEnabled(True)
        self.extract_info.setText("提取失败")
        self._log(f"提取失败: {error_msg}")
        QMessageBox.critical(self, "提取失败", error_msg)

    # ── Pagination ──

    def _update_page_controls(self):
        total = self._total_pages
        current = self._current_page
        self._page_label.setText(f"第 {current} 页 / 共 {total} 页 (共 {len(self._full_df) if self._full_df is not None else 0} 行)")
        self._prev_page_btn.setEnabled(current > 1)
        self._next_page_btn.setEnabled(current < total)

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._render_page()

    def _next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._render_page()

    def _render_page(self):
        if self._full_df is None:
            return
        start = (self._current_page - 1) * TREEVIEW_DISPLAY_LIMIT
        end = start + TREEVIEW_DISPLAY_LIMIT
        page_df = self._full_df.iloc[start:end]
        self.table_model.update_data(page_df)
        self._update_page_controls()

    # ── Double-click trial → browser ──

    def _on_table_double_click(self, index):
        row = index.row()
        model = self.table_view.model()
        trial_id = str(model.data(model.index(row, 0), Qt.DisplayRole)).strip()
        if not trial_id:
            return

        url = None
        if trial_id.startswith("NCT"):
            url = f"https://clinicaltrials.gov/study/{trial_id}"
        elif trial_id.startswith("EUCTR"):
            url = f"https://www.clinicaltrialsregister.eu/ctr-search/trial/{trial_id}"
        elif trial_id.startswith("ISRCTN"):
            url = f"https://www.isrctn.com/{trial_id}"
        elif trial_id.startswith("EU"):
            url = f"https://euclinicaltrials.eu/ctis/#/search?searchTerm={trial_id}"

        if url:
            webbrowser.open(url)

    # ── Table context menu ──

    def _on_table_context_menu(self, pos):
        index = self.table_view.indexAt(pos)
        if not index.isValid():
            return

        menu = QMenu(self)

        copy_cell = menu.addAction("复制单元格")
        copy_row = menu.addAction("复制整行")
        menu.addSeparator()
        copy_selected = menu.addAction("复制选中行")
        export_selected = menu.addAction("导出选中行为 CSV")

        action = menu.exec(self.table_view.viewport().mapToGlobal(pos))

        if action == copy_cell:
            val = self.table_model.data(index, Qt.DisplayRole)
            self._copy_to_clipboard(val or "")
        elif action == copy_row:
            self._copy_rows([index.row()])
        elif action == copy_selected:
            rows = sorted(set(i.row() for i in self.table_view.selectedIndexes()))
            self._copy_rows(rows)
        elif action == export_selected:
            self._export_selected_rows()

    def _copy_to_clipboard(self, text: str):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    def _copy_rows(self, rows: list):
        if not rows or self._full_df is None:
            return
        # Map visual rows to source dataframe rows (accounting for pagination)
        page_start = (self._current_page - 1) * TREEVIEW_DISPLAY_LIMIT
        source_rows = [page_start + r for r in rows if page_start + r < len(self._full_df)]
        if not source_rows:
            return
        subset = self._full_df.iloc[source_rows]
        text = subset.to_csv(sep="\t", index=False)
        self._copy_to_clipboard(text)

    def _export_selected_rows(self):
        if self._full_df is None:
            return
        rows = sorted(set(i.row() for i in self.table_view.selectedIndexes()))
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择行")
            return
        page_start = (self._current_page - 1) * TREEVIEW_DISPLAY_LIMIT
        source_rows = [page_start + r for r in rows if page_start + r < len(self._full_df)]
        if not source_rows:
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "导出选中行", "selected_rows.csv",
            "CSV 文件 (*.csv);;All Files (*)"
        )
        if filename:
            try:
                self._full_df.iloc[source_rows].to_csv(filename, index=False)
                QMessageBox.information(self, "导出成功", f"已导出 {len(source_rows)} 行到:\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

    # ── Document download ──

    def _browse_doc_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择文档保存目录")
        if path:
            self.doc_path_input.setText(path)

    def _enable_doc_buttons(self, enabled: bool):
        for btn in [self.doc_protocol_btn, self.doc_sap_btn,
                     self.doc_both_btn, self.doc_all_btn]:
            btn.setEnabled(enabled)

    def _quick_download(self, doc_regexp: str = None):
        filtered_ids = getattr(self.app, 'filtered_ids', None)
        if not filtered_ids:
            search_ids = getattr(self.app, 'current_search_ids', None)
            if search_ids:
                if QMessageBox.question(
                    self, "确认下载范围",
                    f"尚未提取数据，将为全部 {len(search_ids)} 条记录下载文档。\n继续？",
                ) != QMessageBox.Yes:
                    return
                filtered_ids = search_ids
            else:
                QMessageBox.warning(self, "提示", "没有可下载的试验数据")
                return

        docs_path = self.doc_path_input.text().strip()
        if not docs_path:
            QMessageBox.critical(self, "错误", "请指定文档保存路径")
            return

        # Check for interrupted download (resume support)
        from ctrdata.documents import _get_resume_file, _load_resume, _session_hash, _cleanup_resume
        resume_file = _get_resume_file(self.app.bridge, docs_path)
        resume_data = _load_resume(self.app.bridge, resume_file)
        current_session = _session_hash(filtered_ids, docs_path)

        resume_info = None
        if resume_data.get("session") and resume_data["session"] == current_session:
            done_count = len(resume_data.get("completed", []))
            if done_count > 0 and done_count < len(filtered_ids):
                resume_info = (done_count, len(filtered_ids), resume_file)

        # Confirmation dialog
        doc_type_label = {
            "prot": "Protocol",
            "sap_|statist": "SAP/统计分析",
            "prot|sap_|statist": "Protocol + SAP",
        }.get(doc_regexp, "全部文档")

        if resume_info:
            done, total_ids, rf = resume_info
            remaining = total_ids - done
            msg = (
                f"检测到上次未完成的下载：已完成 {done}/{total_ids}，剩余 {remaining} 条。\n\n"
                f"点击 \"Yes\" 继续下载剩余 {remaining} 条{doc_type_label}\n"
                f"点击 \"No\" 重新下载全部 {total_ids} 条\n\n"
                f"保存到: {docs_path}"
            )
            reply = QMessageBox.question(self, "继续下载", msg)
            if reply == QMessageBox.Yes:
                pass  # Continue — bridge will auto-resume
            else:
                _cleanup_resume(self.app.bridge, rf)
        else:
            msg = (
                f"即将为 {len(filtered_ids)} 条试验下载{doc_type_label}。\n"
                f"保存到: {docs_path}\n\n确认开始下载？"
            )
            if QMessageBox.question(self, "确认下载", msg) != QMessageBox.Yes:
                return

        self._last_docs_regexp = doc_regexp
        total = len(filtered_ids)

        self._enable_doc_buttons(False)
        self.doc_progress.start(total)
        self.doc_progress.set_cancel_enabled(True)
        self.doc_progress.cancelled.connect(self._cancel_doc_download)
        self._doc_start_time = time.time()

        self._log(f"开始下载文档: {total} 个试验, 类型={doc_regexp or '全部'}")

        from ui.app import get_settings
        per_trial_timeout = int(get_settings().value("doc/timeout", 120))

        def _worker():
            svc = ExtractService(self.app.bridge)
            try:
                result = svc.download_documents(
                    trial_ids=filtered_ids,
                    documents_path=docs_path,
                    documents_regexp=doc_regexp,
                    per_trial_timeout=per_trial_timeout,
                    on_progress=lambda c, t, tid, s, detail="":
                        self._doc_progress.emit(c, t, tid, s, detail),
                )
                self._doc_complete.emit(result)
            except Exception as e:
                self._doc_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_doc_progress(self, current, total, trial_id, status, detail=""):
        self.doc_progress.update_progress(current, total, f"正在下载 {trial_id} ({current}/{total})")
        if status == "start":
            self.doc_progress.update_detail(f"{current}/{total} 试验")
            logger.info(f"文档下载 [{current}/{total}]: {trial_id} 开始")
        elif status == "ok":
            if current >= 3 and self._doc_start_time:
                elapsed = time.time() - self._doc_start_time
                remaining = elapsed / current * (total - current)
                self.doc_progress.update_eta(elapsed, remaining)
            logger.info(f"文档下载 [{current}/{total}]: {trial_id} 完成")
        elif status == "error":
            if current >= 3 and self._doc_start_time:
                elapsed = time.time() - self._doc_start_time
                remaining = elapsed / current * (total - current)
                self.doc_progress.update_eta(elapsed, remaining)
            logger.warning(f"文档下载 [{current}/{total}]: {trial_id} 失败")
        elif status == "skip":
            if current >= 3 and self._doc_start_time:
                elapsed = time.time() - self._doc_start_time
                remaining = elapsed / current * (total - current)
                self.doc_progress.update_eta(elapsed, remaining)
            logger.info(f"文档下载 [{current}/{total}]: {trial_id} 跳过")
        elif status == "file_skip":
            logger.info(f"文档下载 [{current}/{total}]: {trial_id} 跳过 {detail} 个已存在文件")

    def _on_doc_complete(self, result):
        try:
            self.doc_progress.cancelled.disconnect(self._cancel_doc_download)
        except RuntimeError:
            pass
        self._enable_doc_buttons(True)

        success = result.get("success", [])
        if isinstance(success, str): success = [success]
        failed = result.get("failed", {})
        skipped = result.get("skipped", {})
        fail_count = len(failed) if isinstance(failed, dict) else 0
        skip_count = len(skipped) if isinstance(skipped, dict) else 0

        self.doc_progress.finish(success=len(success), skipped=skip_count, failed=fail_count)

        self._log(
            f"文档下载完成: 成功 {len(success)}, 跳过 {skip_count}, 失败 {fail_count}"
        )
        self.doc_status.setText(
            f"完成: 成功 {len(success)}, 跳过 {skip_count}, 失败 {fail_count}"
        )

        dlg = DocResultDialog(result, self)
        dlg.exec()

    def _on_doc_error(self, error_msg):
        self.doc_progress.reset()
        self._enable_doc_buttons(True)
        self._log(f"文档下载失败: {error_msg}")
        self.doc_status.setText("文档下载失败")
        QMessageBox.critical(self, "文档下载失败", error_msg)

    def _cancel_doc_download(self):
        self.doc_progress.set_cancel_enabled(False)
        self.doc_status.setText("正在取消...")
        self._log("用户取消文档下载")
        if self.app.bridge:
            self.app.bridge.cancel()
        self.doc_status.setText("已取消")
        self._enable_doc_buttons(True)
        self.doc_progress.reset()

    # ── Logging ──

    def _log(self, msg: str):
        """Thread-safe log — MUST go through signal."""
        self._log_signal.emit("info", msg)

    def _on_log_signal(self, level: str, msg: str):
        try:
            if level == "error":
                logger.error(msg)
            elif level == "warning":
                logger.warning(msg)
            else:
                logger.info(msg)
        except RuntimeError:
            pass

    # ── CSV export ──

    def _export_csv(self):
        if self.app.current_data is None or len(self.app.current_data) == 0:
            QMessageBox.warning(self, "提示", "没有数据可导出")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", "clinical_trials_data.csv",
            "CSV 文件 (*.csv);;All Files (*)"
        )
        if filename:
            try:
                from ctrdata_core import CtrdataBridge
                export_df = self.app.current_data.copy()
                filepath = CtrdataBridge.export_csv(export_df, filename)
                QMessageBox.information(self, "导出成功", f"数据已导出到:\n{filepath}")
                self.app.status.showMessage(f"已导出: {os.path.basename(filepath)}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

    # ── Column width management ──

    _COL_WIDTH_RULES = [
        ("id", 120),
        ("trialid", 120),
        ("_id", 120),
        ("startdate", 110),
        ("recordlastimport", 130),
        ("trialphase", 100),
        ("statusrecruitment", 110),
        ("overallstatus", 110),
        ("title", 280),
        ("trialtitle", 280),
        ("condition", 180),
        ("intervention", 180),
        ("trialpopulation", 180),
        ("samplesize", 80),
        ("numsites", 80),
    ]
    _DEFAULT_COL_WIDTH = 130

    def _apply_column_widths(self, df: pd.DataFrame):
        """Set initial column widths based on column name heuristics."""
        header = self.table_view.horizontalHeader()
        from ui.app import get_settings
        s = get_settings()
        s.beginGroup("table_column_widths")

        for col_idx in range(self.table_model.columnCount()):
            col_name = self.table_model.headerData(col_idx, Qt.Horizontal)
            # Try saved width first
            saved = s.value(col_name, None)
            if saved is not None:
                try:
                    header.resizeSection(col_idx, int(saved))
                    continue
                except (ValueError, TypeError):
                    pass
            # Apply heuristic width
            width = self._DEFAULT_COL_WIDTH
            col_lower = col_name.lower() if col_name else ""
            for suffix, w in self._COL_WIDTH_RULES:
                if col_lower.endswith(suffix):
                    width = w
                    break
            header.resizeSection(col_idx, width)

        s.endGroup()

        # Save column widths when user manually resizes
        header.sectionResized.connect(self._save_column_width)

    def _save_column_width(self, logical_index: int, old_size: int, new_size: int):
        """Persist user-adjusted column width to QSettings."""
        col_name = self.table_model.headerData(logical_index, Qt.Horizontal)
        if not col_name:
            return
        from ui.app import get_settings
        s = get_settings()
        s.beginGroup("table_column_widths")
        s.setValue(col_name, new_size)
        s.endGroup()

