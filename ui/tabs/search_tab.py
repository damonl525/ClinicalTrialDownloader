#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 2: Search & Download — three modes: form search, URL paste, trial ID lookup.
"""

import logging
import queue
import re
import threading
import webbrowser

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QFrame,
    QSizePolicy, QTabWidget, QMessageBox, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ui.theme import get_font, SPACING
from ui.widgets.progress import ProgressPanel
from ui.widgets.date_edit import DateEdit
from ui.widgets.card import CollapsibleCard
from core.constants import (
    SEARCH_PHASES, SEARCH_RECRUITMENT, SEARCH_POPULATIONS,
    SUPPORTED_REGISTERS, LOG_MAX_LINES,
)
from service.download_service import DownloadService

logger = logging.getLogger(__name__)


class DownloadResultDialog(QMessageBox):
    """Download result dialog with collapsible detail sections."""

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载完成")
        self.setIcon(QMessageBox.Information)

        n = result.get("n", 0)
        s = result.get("success", [])
        failed = result.get("failed", [])
        failed_detail = result.get("failed_detail", [])
        skipped = result.get("skipped", 0)
        skipped_detail = result.get("skipped_detail", [])
        prot_skip = result.get("protocol_skipped", 0)
        prot_skip_ids = result.get("protocol_skipped_ids", [])

        # Summary
        summary_parts = [f"记录数: {n}", f"成功试验: {len(s)} 个"]
        if skipped:
            summary_parts.append(f"已存在跳过: {skipped}")
        if prot_skip:
            summary_parts.append(f"Protocol过滤跳过: {prot_skip}")
        if failed:
            summary_parts.append(f"失败: {len(failed)}")

        summary = "本次下载:\n  " + "\n  ".join(summary_parts)

        # Detail sections
        details = []

        # Skipped by duplicate
        if skipped_detail:
            lines = ["以下试验已存在于数据库，跳过下载:"]
            for item in skipped_detail:
                reg = item.get("register", "?")
                ids = item.get("ids", [])
                if ids:
                    for tid in ids[:50]:
                        lines.append(f"  [{reg}] {tid}")
                    if len(ids) > 50:
                        lines.append(f"  ... 及其他 {len(ids) - 50} 条")
            details.append(("\n".join(lines)))

        # Skipped by protocol filter
        if prot_skip_ids:
            lines = [f"以下 {prot_skip} 个试验无 Protocol 文档，已被过滤:"]
            for tid in prot_skip_ids[:50]:
                lines.append(f"  {tid}")
            if len(prot_skip_ids) > 50:
                lines.append(f"  ... 及其他 {len(prot_skip_ids) - 50} 条")
            details.append("\n".join(lines))

        # Failed
        if failed_detail:
            lines = ["以下操作失败:"]
            for item in failed_detail:
                reg = item.get("register", "?")
                err = item.get("error", item.get("id", "未知错误"))
                lines.append(f"  [{reg}] {err}")
            details.append("\n".join(lines))

        # Success list (always show if not too many)
        if len(s) <= 20:
            lines = [f"成功下载的试验 ({len(s)} 个):"]
            for tid in s:
                lines.append(f"  {tid}")
            details.append("\n".join(lines))

        if details:
            detail_text = "\n\n".join(details)
            self.setInformativeText("点击「显示详情」查看具体信息")
            self.setDetailedText(detail_text)
            # Pre-expand details
            for btn in self.buttons():
                if self.buttonRole(btn) == QMessageBox.ActionRole:
                    btn.click()
                    break

        self.setText(summary)
        self.addButton(QMessageBox.Ok)


class SearchTab(QWidget):
    """Search and download tab."""

    # Signals for thread-safe UI updates
    _download_complete = Signal(dict)
    _download_error = Signal(str)
    _status_msg = Signal(str)
    _log_signal = Signal(str, str)  # level, message
    _progress_update = Signal(int, int, str)  # current, total, message
    _timeout_request = Signal(dict)  # ctx dict with event + choice
    download_finished = Signal(dict)   # Emitted after download result dialog closes

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.app = main_window
        self._generated_urls = {}
        self.is_downloading = False
        self._dl_service = None
        self._timeout_queue = None  # queue.Queue, avoids PySide6 cross-thread dict copy
        self._timeout_dlg_active = False  # reentrancy guard
        self._setup_ui()

        # Connect signals
        self._download_complete.connect(self._on_complete)
        self._download_error.connect(self._on_error)
        self._status_msg.connect(lambda msg: self.progress_panel.update_detail(msg))
        self._log_signal.connect(self._on_log_signal)
        self._progress_update.connect(self._on_progress_update)
        self._timeout_request.connect(self._on_timeout_request)

        # Restore last search state
        self._restore_search_state()

    def _make_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        return frame

    def _setup_ui(self):
        # Wrap in scroll area for expand/collapse safety
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(SPACING["md"])

        # ── Search mode sub-tabs ──
        self.mode_tabs = QTabWidget()
        self.mode_tabs.currentChanged.connect(self._on_mode_changed)
        self._build_form_search()
        self._build_url_search()
        self._build_id_search()
        layout.addWidget(self.mode_tabs)

        # ── Card: Actions ──
        action_card = self._make_card()
        action_layout = QVBoxLayout(action_card)
        action_layout.setSpacing(SPACING["sm"])

        btn_row = QHBoxLayout()
        self.search_btn = QPushButton("搜索并下载")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._search_and_download)
        btn_row.addWidget(self.search_btn)

        self.browser_btn = QPushButton("浏览器查看")
        self.browser_btn.setObjectName("secondary")
        self.browser_btn.setToolTip("在浏览器中打开搜索结果页面")
        self.browser_btn.clicked.connect(self._open_in_browser)
        btn_row.addWidget(self.browser_btn)

        self.copy_urls_btn = QPushButton("复制所有URL")
        self.copy_urls_btn.setObjectName("secondary")
        self.copy_urls_btn.setToolTip("复制所有注册中心的搜索 URL 到剪贴板")
        self.copy_urls_btn.clicked.connect(self._copy_all_urls)
        btn_row.addWidget(self.copy_urls_btn)

        self.update_btn = QPushButton("增量更新")
        self.update_btn.setObjectName("secondary")
        self.update_btn.setToolTip("重新执行上次查询，仅下载新增或有变更的试验数据")
        self.update_btn.clicked.connect(self._update_last_query)
        btn_row.addWidget(self.update_btn)

        action_layout.addLayout(btn_row)

        self.progress_panel = ProgressPanel()
        self.progress_panel.cancelled.connect(self._cancel)
        action_layout.addWidget(self.progress_panel)

        layout.addWidget(action_card)

        layout.addStretch()

        self._scroll.setWidget(container)
        outer.addWidget(self._scroll)

    # ── Form search ──

    def _build_form_search(self) -> QWidget:
        w = QWidget()
        form = QVBoxLayout(w)
        form.setSpacing(SPACING["sm"])

        # Row 1: condition + intervention
        row1 = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(QLabel("疾病/状况"))
        self.condition_input = QLineEdit()
        self.condition_input.setPlaceholderText("e.g. cancer")
        col1.addWidget(self.condition_input)
        row1.addLayout(col1)

        col2 = QVBoxLayout()
        col2.addWidget(QLabel("干预措施"))
        self.intervention_input = QLineEdit()
        self.intervention_input.setPlaceholderText("e.g. aspirin")
        col2.addWidget(self.intervention_input)
        row1.addLayout(col2)
        form.addLayout(row1)

        # Row 2: phrase
        row2 = QHBoxLayout()
        col3 = QVBoxLayout()
        col3.addWidget(QLabel("搜索短语（精确搜索，支持 AND / OR）"))
        self.phrase_input = QLineEdit()
        col3.addWidget(self.phrase_input)
        row2.addLayout(col3)
        form.addLayout(row2)

        # Advanced options (collapsible)
        self._advanced_card = CollapsibleCard("高级条件（可选）", expanded=False)
        adv_layout = QVBoxLayout()

        # Phase + recruitment
        adv_row1 = QHBoxLayout()
        adv_row1.setSpacing(SPACING["sm"])
        adv_row1.addWidget(QLabel("阶段:"))
        self.phase_combo = QComboBox()
        for label in SEARCH_PHASES:
            self.phase_combo.addItem(label)
        adv_row1.addWidget(self.phase_combo)
        adv_row1.addSpacing(20)
        adv_row1.addWidget(QLabel("招募状态:"))
        self.recruitment_combo = QComboBox()
        for label in SEARCH_RECRUITMENT:
            self.recruitment_combo.addItem(label)
        adv_row1.addWidget(self.recruitment_combo)
        adv_row1.addWidget(QLabel("其他=含提前终止"))
        adv_row1.addStretch()
        adv_layout.addLayout(adv_row1)

        # Start date
        adv_row2 = QHBoxLayout()
        adv_row2.setSpacing(SPACING["sm"])
        adv_row2.addWidget(QLabel("开始日期从:"))
        self.start_after_input = DateEdit()
        adv_row2.addWidget(self.start_after_input)
        adv_row2.addWidget(QLabel("到:"))
        self.start_before_input = DateEdit()
        adv_row2.addWidget(self.start_before_input)
        adv_row2.addWidget(QLabel("EUCTR为注册日期"))
        adv_row2.addStretch()
        adv_layout.addLayout(adv_row2)

        # Completed date
        adv_row3 = QHBoxLayout()
        adv_row3.setSpacing(SPACING["sm"])
        adv_row3.addWidget(QLabel("完成日期从:"))
        self.completed_after_input = DateEdit()
        adv_row3.addWidget(self.completed_after_input)
        adv_row3.addWidget(QLabel("到:"))
        self.completed_before_input = DateEdit()
        adv_row3.addWidget(self.completed_before_input)
        adv_row3.addStretch()
        adv_layout.addLayout(adv_row3)

        # Population + countries
        adv_row4 = QHBoxLayout()
        adv_row4.setSpacing(SPACING["sm"])
        adv_row4.addWidget(QLabel("目标人群:"))
        self.population_combo = QComboBox()
        for label in SEARCH_POPULATIONS:
            self.population_combo.addItem(label)
        adv_row4.addWidget(self.population_combo)
        adv_row4.addSpacing(20)
        adv_row4.addWidget(QLabel("国家/地区:"))
        self.countries_input = QLineEdit()
        self.countries_input.setMaximumWidth(120)
        self.countries_input.setPlaceholderText("US,CN,DE")
        adv_row4.addWidget(self.countries_input)
        adv_row4.addStretch()
        adv_layout.addLayout(adv_row4)

        # Checkboxes
        adv_row5 = QHBoxLayout()
        adv_row5.setSpacing(SPACING["md"])
        self.only_med_check = QCheckBox("仅药物干预试验")
        self.only_med_check.setChecked(True)
        adv_row5.addWidget(self.only_med_check)
        self.only_results_check = QCheckBox("仅有结果的试验")
        self.only_results_check.setToolTip("仅筛选已在注册中心提交了结果数据的试验")
        adv_row5.addWidget(self.only_results_check)
        self.protocol_only_check = QCheckBox("仅含Protocol文档的试验")
        self.protocol_only_check.setToolTip(
            "Protocol: 研究方案;\nSAP: 统计分析计划;\n"
            "全部: 包含知情同意书等所有文档"
        )
        adv_row5.addWidget(self.protocol_only_check)
        adv_row5.addStretch()
        adv_layout.addLayout(adv_row5)

        # Registers
        adv_row6 = QHBoxLayout()
        adv_row6.setSpacing(SPACING["md"])
        adv_row6.addWidget(QLabel("注册中心:"))
        self.register_checks = {}
        _reg_desc = {
            "CTGOV2": "ClinicalTrials.gov (美国)",
            "EUCTR": "EU CTR (欧盟)",
            "ISRCTN": "ISRCTN (英国)",
            "CTIS": "CTIS (欧盟新)",
        }
        for key, name in SUPPORTED_REGISTERS.items():
            cb = QCheckBox(_reg_desc.get(key, key))
            cb.setChecked(key in ("CTGOV2",))
            self.register_checks[key] = cb
            adv_row6.addWidget(cb)
        adv_row6.addStretch()
        adv_layout.addLayout(adv_row6)

        # CTIS warning hint
        ctis_hint = QLabel("⚠ CTIS 无公开 API，下载易超时；CTGOV2 覆盖面最广，通常够用")
        ctis_hint.setStyleSheet("color: #94A3B8; font-size: 11px;")
        ctis_hint.setContentsMargins(SPACING["lg"] + SPACING["sm"], 0, 0, 0)
        adv_layout.addWidget(ctis_hint)

        self._advanced_card.set_body_layout(adv_layout)
        form.addWidget(self._advanced_card)

        self.mode_tabs.addTab(w, "表单搜索")
        return w

    # ── URL paste ──

    def _build_url_search(self) -> QWidget:
        w = QWidget()
        form = QVBoxLayout(w)
        form.addWidget(QLabel("粘贴注册中心搜索页 URL:"))
        form.addWidget(QLabel("例: https://www.clinicaltrials.gov/search?cond=cancer"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://...")
        form.addWidget(self.url_input)
        form.addStretch()
        self.mode_tabs.addTab(w, "粘贴 URL")
        return w

    # ── Trial ID ──

    def _build_id_search(self) -> QWidget:
        w = QWidget()
        form = QVBoxLayout(w)
        form.addWidget(QLabel("试验 ID:"))
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("NCT04523532")
        form.addWidget(self.id_input)
        form.addWidget(QLabel("支持: NCTxxxxxx / 20xx-xxxxxx-xx / ISRCTNxxxxx / 20xx-xxx"))
        form.addStretch()
        self.mode_tabs.addTab(w, "按试验ID")
        return w

    # ── Mode change ──

    def _on_mode_changed(self, index):
        mode = self._current_mode()
        if hasattr(self, 'browser_btn'):
            self.browser_btn.setEnabled(mode == "form")

    def _current_mode(self) -> str:
        idx = self.mode_tabs.currentIndex()
        return ["form", "url", "id"][idx] if 0 <= idx < 3 else "form"

    # ── Collect params ──

    def _collect_form_params(self) -> dict:
        return {
            "condition": self.condition_input.text().strip(),
            "intervention": self.intervention_input.text().strip(),
            "search_phrase": self.phrase_input.text().strip(),
            "phase": SEARCH_PHASES.get(self.phase_combo.currentText(), ""),
            "recruitment": SEARCH_RECRUITMENT.get(self.recruitment_combo.currentText(), ""),
            "start_after": self.start_after_input.date_str(),
            "start_before": self.start_before_input.date_str(),
            "completed_after": self.completed_after_input.date_str(),
            "completed_before": self.completed_before_input.date_str(),
            "population": SEARCH_POPULATIONS.get(self.population_combo.currentText(), ""),
            "countries": self.countries_input.text().strip(),
            "only_med_interv_trials": self.only_med_check.isChecked(),
            "only_with_results": self.only_results_check.isChecked(),
        }

    def _get_selected_registers(self) -> list:
        return [k for k, cb in self.register_checks.items() if cb.isChecked()]

    def _get_dl_service(self):
        """Lazily create DownloadService bound to current bridge."""
        if self._dl_service is None or self._dl_service.bridge is not self.app.bridge:
            self._dl_service = DownloadService(self.app.bridge)
        return self._dl_service

    def _filter_urls_by_registers(self, urls: dict, registers: list) -> dict:
        return {k: v for k, v in urls.items() if k in registers}

    # ── Preview count ──

    # ── Browser view ──

    def _open_in_browser(self):
        if not self.app.bridge:
            QMessageBox.critical(self, "错误", "R 环境未就绪")
            return

        try:
            if self._generated_urls:
                for reg, url in self._generated_urls.items():
                    try:
                        self.app.bridge.open_in_browser(url=url)
                    except Exception:
                        pass
                return

            params = self._collect_form_params()

            urls = self.app.bridge.generate_queries(**params)
            selected_regs = self._get_selected_registers()
            filtered_urls = self._filter_urls_by_registers(urls, selected_regs)
            for reg, url in filtered_urls.items():
                try:
                    self.app.bridge.open_in_browser(url=url)
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    # ── Copy URLs ──

    def _copy_all_urls(self):
        mode = self._current_mode()
        text = ""

        if mode == "form":
            if not self._generated_urls:
                params = self._collect_form_params()
                try:
                    urls = self.app.bridge.generate_queries(**params)
                    self._generated_urls = self._filter_urls_by_registers(urls, self._get_selected_registers())
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"生成 URL 失败: {e}")
                    return
            if not self._generated_urls:
                QMessageBox.information(self, "提示", "没有可复制的 URL")
                return
            text = "\n".join(f"{reg}: {url}" for reg, url in self._generated_urls.items())
        elif mode == "url":
            text = self.url_input.text().strip()
            if not text:
                QMessageBox.warning(self, "提示", "请先粘贴 URL")
                return
        elif mode == "id":
            text = self.id_input.text().strip()
            if not text:
                QMessageBox.warning(self, "提示", "请先输入试验 ID")
                return

        if text:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.progress_panel.update_detail(f"已复制到剪贴板")

    # ── Update last query ──

    def _update_last_query(self):
        if not self.app.bridge or not self.app.bridge.db_path:
            QMessageBox.critical(self, "错误", "请先连接数据库")
            return
        self.progress_panel.update_detail("正在更新上次查询...")

        def _worker():
            svc = self._get_dl_service()
            try:
                svc.update_query(
                    on_log=lambda msg: self._status_msg.emit(msg),
                )
            except Exception as e:
                self._download_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Synonyms ──

    def _find_synonyms(self):
        intervention = self.intervention_input.text().strip()
        if not intervention:
            QMessageBox.information(self, "提示", "请先输入干预措施名称")
            return
        if not self.app.bridge:
            QMessageBox.critical(self, "错误", "请先连接数据库")
            return

        self.progress_panel.update_detail(f"正在查找 {intervention} 的同义词...")

        def _worker():
            svc = self._get_dl_service()
            try:
                synonyms = svc.find_synonyms(
                    intervention,
                    on_log=lambda msg: self._status_msg.emit(msg),
                )
                if synonyms:
                    from PySide6.QtWidgets import QApplication
                    QApplication.clipboard().setText("\n".join(synonyms))
                    self._status_msg.emit(f"已复制 {len(synonyms)} 个同义词到剪贴板")
            except Exception as e:
                self._download_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Download flow ──

    def _search_and_download(self):
        if not self.app.bridge or not self.app.bridge.db_path:
            QMessageBox.critical(self, "错误", "请先连接数据库（第 1 步）")
            return

        mode = self._current_mode()
        self._save_search_state(mode)
        self.progress_panel.reset()
        self._set_downloading(True)

        if mode == "form":
            self._start_form_download()
        elif mode == "url":
            self._start_url_download()
        elif mode == "id":
            self._start_id_download()

    def _start_form_download(self):
        params = self._collect_form_params()

        selected_regs = self._get_selected_registers()
        if not selected_regs:
            QMessageBox.warning(self, "提示", "请至少选择一个注册中心")
            self._set_downloading(False)
            return

        protocol_filter = self.protocol_only_check.isChecked()
        # Store for Export Tab to pick up during auto-extract
        self.app.protocol_filter_requested = protocol_filter

        def _worker():
            svc = self._get_dl_service()
            try:
                result = svc.form_download(
                    params=params,
                    selected_regs=selected_regs,
                    is_cancelled=lambda: not self.is_downloading,
                    on_log=self._log,
                    on_progress=lambda c, t, m: self._progress_update.emit(c, t, m),
                    on_timeout=self._make_timeout_callback(),
                )
                if result.cancelled:
                    self._download_complete.emit({"cancelled": True})
                    return
                if not result.success and not result.failed:
                    self._download_error.emit("所选注册中心未生成 URL")
                    return
                self._generated_urls = result.urls
                self.app.current_search_ids = result.success if result.success else None
                agg = {
                    "n": result.n,
                    "success": result.success,
                    "failed": result.failed,
                    "failed_detail": result.failed_detail,
                    "skipped": result.skipped,
                    "skipped_detail": result.skipped_detail,
                    "protocol_skipped": result.protocol_skipped,
                    "protocol_skipped_ids": result.protocol_skipped_ids,
                }
                self._download_complete.emit(agg)
            except Exception as e:
                self._download_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _start_url_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.critical(self, "错误", "请粘贴搜索 URL")
            self._set_downloading(False)
            return

        self._log("开始 URL 下载...")
        self._log(f"URL: {url[:120]}")

        def _worker():
            svc = self._get_dl_service()
            try:
                result = svc.url_download(
                    url,
                    on_log=self._log,
                    on_progress=lambda c, t, m: self._progress_update.emit(c, t, m),
                )
                s = result.get("success", [])
                self.app.current_search_ids = s if s else None
                self._download_complete.emit(result)
            except Exception as e:
                self._download_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _start_id_download(self):
        trial_id = self.id_input.text().strip()
        if not trial_id:
            QMessageBox.critical(self, "错误", "请输入试验 ID")
            self._set_downloading(False)
            return

        self._log(f"正在下载试验: {trial_id}...")
        self._progress_update.emit(0, 1, f"正在下载 {trial_id}...")

        def _worker():
            svc = self._get_dl_service()
            try:
                result = svc.id_download(
                    trial_id,
                    on_log=self._log,
                )
                s = result.get("success", [])
                self.app.current_search_ids = s if s else None
                self._download_complete.emit(result)
            except Exception as e:
                self._download_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Logging (thread-safe) ──

    def _log(self, msg: str):
        """Thread-safe log append — MUST go through signal, never touch widgets directly."""
        self._status_msg.emit(msg)
        self._log_signal.emit("info", msg)

    def _on_log_signal(self, level: str, msg: str):
        """Handle log signal on GUI thread — forward to logging system."""
        try:
            if level == "error":
                logger.error(msg)
            elif level == "warning":
                logger.warning(msg)
            else:
                logger.info(msg)
        except RuntimeError:
            pass

    # ── UI state ──

    def _set_downloading(self, busy: bool):
        self.is_downloading = busy
        self.search_btn.setEnabled(not busy)
        self.browser_btn.setEnabled(not busy and self._current_mode() == "form")
        self.update_btn.setEnabled(not busy)

        if busy:
            self.progress_panel.start(1)
            self.progress_panel.update_progress(0, 1, "准备下载...")
            self.app.filtered_ids = []
            self.app.current_search_ids = None
        else:
            self.progress_panel.reset()

    def _on_complete(self, result):
        if result.get("cancelled"):
            # If _cancel() already reset UI (progress cancel button), skip
            if not self.is_downloading:
                return
            self._set_downloading(False)
            self.progress_panel.update_detail("下载已取消")
            self.app.status.showMessage("下载已取消")
            return

        self._set_downloading(False)

        n = result.get("n", 0)
        s = result.get("success", [])
        if not isinstance(s, list): s = [s] if s else []

        self.progress_panel.update_detail(f"完成: 下载 {n} 条记录, {len(s)} 个试验")
        self.app.status.showMessage(f"数据下载完成: {n} 条记录")
        self.app.update_db_status()

        # Refresh export tab scope counts
        export_tab = self.app.tabs.widget(2) if hasattr(self.app, 'tabs') else None
        if export_tab and hasattr(export_tab, 'refresh_scope_counts'):
            export_tab.refresh_scope_counts()

        dlg = DownloadResultDialog(result, self)
        dlg.exec()

        self.download_finished.emit(result)

    def _on_error(self, error_msg):
        self._set_downloading(False)
        self.progress_panel.update_detail("下载失败")
        QMessageBox.critical(self, "下载失败", error_msg)

    def _on_progress_update(self, current, total, message):
        """Update progress panel (thread-safe via signal)."""
        self.progress_panel.update_progress(current, total, message)

    def _cancel(self):
        self.progress_panel.update_detail("正在取消...")
        self._log("用户取消了操作")
        if self.app.bridge:
            self.app.bridge.cancel()
        self.app.current_search_ids = None
        self._set_downloading(False)
        self.progress_panel.update_detail("已取消")

    # ── Search state persistence ──

    def _save_search_state(self, mode: str):
        """Save current search inputs to QSettings."""
        from ui.app import get_settings
        s = get_settings()
        s.beginGroup("search_state")
        s.setValue("mode", mode)
        s.setValue("condition", self.condition_input.text())
        s.setValue("intervention", self.intervention_input.text())
        s.setValue("search_phrase", self.phrase_input.text())
        s.setValue("phase_index", self.phase_combo.currentIndex())
        s.setValue("recruitment_index", self.recruitment_combo.currentIndex())
        s.setValue("start_after", self.start_after_input.date_str())
        s.setValue("start_before", self.start_before_input.date_str())
        s.setValue("completed_after", self.completed_after_input.date_str())
        s.setValue("completed_before", self.completed_before_input.date_str())
        s.setValue("population_index", self.population_combo.currentIndex())
        s.setValue("countries", self.countries_input.text())
        s.setValue("only_med", self.only_med_check.isChecked())
        s.setValue("only_results", self.only_results_check.isChecked())
        s.setValue("protocol_only", self.protocol_only_check.isChecked())
        registers = [k for k, cb in self.register_checks.items() if cb.isChecked()]
        s.setValue("registers", registers)
        s.setValue("url", self.url_input.text())
        s.setValue("trial_id", self.id_input.text())
        s.endGroup()

    def _restore_search_state(self):
        """Restore last search inputs from QSettings."""
        from ui.app import get_settings
        s = get_settings()
        s.beginGroup("search_state")

        mode = s.value("mode", "form")
        mode_idx = {"form": 0, "url": 1, "id": 2}.get(mode, 0)
        self.mode_tabs.setCurrentIndex(mode_idx)

        self.condition_input.setText(s.value("condition", ""))
        self.intervention_input.setText(s.value("intervention", ""))
        self.phrase_input.setText(s.value("search_phrase", ""))

        phase_idx = s.value("phase_index", 0)
        if isinstance(phase_idx, int) and 0 <= phase_idx < self.phase_combo.count():
            self.phase_combo.setCurrentIndex(phase_idx)

        recruit_idx = s.value("recruitment_index", 0)
        if isinstance(recruit_idx, int) and 0 <= recruit_idx < self.recruitment_combo.count():
            self.recruitment_combo.setCurrentIndex(recruit_idx)

        self.start_after_input.setDateString(s.value("start_after", ""))
        self.start_before_input.setDateString(s.value("start_before", ""))
        self.completed_after_input.setDateString(s.value("completed_after", ""))
        self.completed_before_input.setDateString(s.value("completed_before", ""))

        pop_idx = s.value("population_index", 0)
        if isinstance(pop_idx, int) and 0 <= pop_idx < self.population_combo.count():
            self.population_combo.setCurrentIndex(pop_idx)

        self.countries_input.setText(s.value("countries", ""))
        self.only_med_check.setChecked(s.value("only_med", True) in (True, "true"))
        self.only_results_check.setChecked(s.value("only_results", False) in (True, "true"))
        self.protocol_only_check.setChecked(s.value("protocol_only", False) in (True, "true"))

        registers = s.value("registers", ["CTGOV2"])
        if isinstance(registers, list):
            for key, cb in self.register_checks.items():
                cb.setChecked(key in registers)

        self.url_input.setText(s.value("url", ""))
        self.id_input.setText(s.value("trial_id", ""))

        s.endGroup()

    # ── Timeout handling ──

    def _on_timeout_request(self, ctx: dict):
        """Show timeout dialog on GUI thread (called via signal from worker)."""
        # Reentrancy guard: if a dialog is already showing and a second
        # timeout fires, write "continue" to the current queue so the
        # worker doesn't hang, then ignore the duplicate signal.
        if self._timeout_dlg_active:
            logger.warning("Timeout dialog already active, ignoring duplicate signal")
            return

        self._timeout_dlg_active = True
        try:
            elapsed = ctx.get("elapsed", 600)
            register = ctx.get("register", "")

            # Disable progress cancel button to prevent double-action
            self.progress_panel.set_cancel_enabled(False)

            dlg = QMessageBox(self)
            dlg.setWindowTitle("下载超时")
            dlg.setIcon(QMessageBox.Warning)

            reg_text = f"（注册中心: {register}）" if register else ""
            dlg.setText(
                f"下载已运行 {elapsed} 秒仍未完成{reg_text}\n\n"
                "可能原因：\n"
                "  • 搜索结果条目过多\n"
                "  • 网络连接缓慢\n\n"
                "请选择操作："
            )

            continue_btn = dlg.addButton("继续等待", QMessageBox.AcceptRole)
            skip_btn = dlg.addButton("跳过此注册中心", QMessageBox.RejectRole)
            cancel_btn = dlg.addButton("取消全部下载", QMessageBox.DestructiveRole)

            # Default to "continue" (Enter key), Escape = "skip" (not cancel)
            dlg.setDefaultButton(continue_btn)
            dlg.setEscapeButton(skip_btn)

            dlg.exec()

            clicked = dlg.clickedButton()
            if clicked == continue_btn:
                choice = "continue"
                self.progress_panel.set_cancel_enabled(True)
            elif clicked == skip_btn:
                choice = "skip"
                self.progress_panel.update_detail("正在跳过...")
            elif clicked == cancel_btn:
                choice = "cancel"
                self.progress_panel.update_detail("正在取消...")
            else:
                # Dialog dismissed without explicit choice (X button, etc.)
                choice = "continue"
                self.progress_panel.set_cancel_enabled(True)

            logger.debug(
                f"Timeout dialog choice: {choice} "
                f"(register={register}, elapsed={elapsed}s, clicked={clicked})"
            )

            # Write choice to the queue so worker thread can read it.
            # Using queue.Queue avoids PySide6 cross-thread dict deep-copy issues.
            if self._timeout_queue is not None:
                self._timeout_queue.put(choice)
        finally:
            self._timeout_dlg_active = False

    def _make_timeout_callback(self):
        """Create a thread-safe timeout callback for DownloadService.

        Uses queue.Queue instead of threading.Event in signal payload
        to avoid PySide6 deep-copying mutable objects in cross-thread signals.
        """
        def on_timeout(elapsed: int, register: str) -> str:
            q = queue.Queue()
            self._timeout_queue = q
            try:
                # Emit signal with immutable data only
                self._timeout_request.emit({"elapsed": elapsed, "register": register})
                # Block until GUI thread writes response, with a generous timeout
                choice = q.get(timeout=300)  # 5 minutes max wait
                logger.debug(
                    f"Timeout callback received choice: '{choice}' "
                    f"(register={register}, elapsed={elapsed}s)"
                )
                return choice
            except queue.Empty:
                logger.warning(
                    f"Timeout dialog response timed out after 300s "
                    f"(register={register}), defaulting to continue"
                )
                return "continue"
            finally:
                self._timeout_queue = None
        return on_timeout
