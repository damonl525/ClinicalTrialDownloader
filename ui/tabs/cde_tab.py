#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CDE Tab — CDE上市药品信息搜索、爬取和 PDF 下载。
无数据库依赖，所有请求通过 QWebEngine 绕过瑞数 WAF。
"""

import logging
import os
import re
import webbrowser

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QMessageBox,
    QFileDialog, QMenu, QCheckBox,
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
    CDE_DRUG_TYPES,
    CDE_APPLY_TYPES,
    CDE_REG_CLASSES,
)


class CdeTab(QWidget):
    """Standalone CDE marketed drug search and PDF download tab."""

    # Signals
    _scrape_complete = Signal(list)
    _scrape_error = Signal(str)
    _download_complete = Signal(dict)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._all_rows = []
        self._current_page = 0
        self._total_pages = 0
        self._scraper = None
        self._pdf_downloader = None

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING["md"])

        self._build_search_area(layout)
        self._build_result_table(layout)
        self._build_action_bar(layout)

        # Signal connections
        self._scrape_complete.connect(self._on_scrape_complete)
        self._scrape_error.connect(self._on_scrape_error)
        self._download_complete.connect(self._on_pdf_download_complete)

        # Right-click context menu
        self.table.context_menu_requested.connect(self._on_table_context_menu)

    # ─────────────────────────────────────────────────────────────
    # Search area
    # ─────────────────────────────────────────────────────────────

    def _build_search_area(self, parent_layout):
        # Main search row
        search_row = QHBoxLayout()
        search_row.setSpacing(SPACING["sm"])

        search_row.addWidget(QLabel("关键词:"))
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("输入药品名称/受理号")
        self.keyword_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.keyword_input, stretch=2)

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

        adv_layout.addWidget(QLabel("药品类型:"), 0, 0)
        self.drug_type_combo = QComboBox()
        for label, val in CDE_DRUG_TYPES.items():
            self.drug_type_combo.addItem(label, val)
        adv_layout.addWidget(self.drug_type_combo, 0, 1)

        adv_layout.addWidget(QLabel("申请类型:"), 0, 2)
        self.apply_type_combo = QComboBox()
        for label, val in CDE_APPLY_TYPES.items():
            self.apply_type_combo.addItem(label, val)
        adv_layout.addWidget(self.apply_type_combo, 0, 3)

        adv_layout.addWidget(QLabel("注册分类:"), 1, 0)
        self.reg_class_combo = QComboBox()
        for label, val in CDE_REG_CLASSES.items():
            self.reg_class_combo.addItem(label, val)
        adv_layout.addWidget(self.reg_class_combo, 1, 1)

        self.advanced_card.set_body_layout(adv_layout)
        parent_layout.addWidget(self.advanced_card)

    # ─────────────────────────────────────────────────────────────
    # Result table
    # ─────────────────────────────────────────────────────────────

    def _build_result_table(self, parent_layout):
        self.result_label = QLabel("输入关键词搜索 CDE 上市药品信息")
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

        # Scrape all checkbox
        self.scrape_all_checkbox = QCheckBox("爬取全部页")
        self.scrape_all_checkbox.setToolTip("勾选后自动翻页爬取所有记录")
        page_row.addWidget(self.scrape_all_checkbox)

        parent_layout.addLayout(page_row)

    # ─────────────────────────────────────────────────────────────
    # Action bar
    # ─────────────────────────────────────────────────────────────

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
        self.download_btn.setToolTip("下载选中的审评报告和说明书 PDF")
        self.download_btn.clicked.connect(self._do_download)
        action_row.addWidget(self.download_btn)

        parent_layout.addLayout(action_row)

        # Progress panel
        self.download_progress = ProgressPanel()
        parent_layout.addWidget(self.download_progress)

    # ─────────────────────────────────────────────────────────────
    # Search / scrape logic
    # ─────────────────────────────────────────────────────────────

    def _collect_params(self) -> dict:
        """Gather search params from UI fields."""
        params = {"keyword": self.keyword_input.text().strip()}

        df = self.date_from.date_str()
        if df:
            params["date_from"] = df
        dt = self.date_to.date_str()
        if dt:
            params["date_to"] = dt

        drug_type = self.drug_type_combo.currentData()
        if drug_type:
            params["drug_type"] = drug_type

        apply_type = self.apply_type_combo.currentData()
        if apply_type:
            params["apply_type"] = apply_type

        reg_class = self.reg_class_combo.currentData()
        if reg_class:
            params["reg_class"] = reg_class

        params["scrape_all"] = self.scrape_all_checkbox.isChecked()
        return params

    def _do_search(self):
        params = self._collect_params()
        self._current_params = params
        self._current_page = 0
        self.search_btn.setEnabled(False)
        self.table.uncheck_all()
        self.result_label.setText("正在加载...")
        logger.info("CDE搜索请求: keyword=%s", params.get("keyword", ""))

        # Check PySide6-WebEngineWidgets availability
        try:
            from PySide6.QtWebEngineCore import QWebEngineProfile
        except ImportError:
            self.search_btn.setEnabled(True)
            QMessageBox.critical(
                self, "组件缺失",
                "PySide6-WebEngineWidgets 未安装，无法使用 CDE 功能。\n"
                "请安装: pip install PySide6-WebEngineWidgets",
            )
            return

        try:
            from service.cde_scraper import CdeListScraper
            scraper = CdeListScraper(self)
            scraper.page_parsed.connect(self._on_page_parsed)
            scraper.scrape_complete.connect(self._scrape_complete.emit)
            scraper.scrape_error.connect(self._scrape_error.emit)
            scraper.scrape_progress.connect(self._on_scrape_progress)
            self._scraper = scraper
            scraper.scrape(
                keyword=params.get("keyword", ""),
                date_from=params.get("date_from", ""),
                date_to=params.get("date_to", ""),
                drug_type=params.get("drug_type", ""),
                apply_type=params.get("apply_type", ""),
                reg_class=params.get("reg_class", ""),
                scrape_all=params.get("scrape_all", False),
            )
        except Exception as e:
            self._scrape_error.emit(str(e))

    def _on_page_parsed(self, current_page: int, total_pages: int, rows: list):
        """Handle individual page parsed — update table."""
        self._current_page = current_page
        self._total_pages = total_pages

        if current_page == 1:
            self._all_rows = []

        self._all_rows.extend(rows)
        self._populate_table(self._all_rows)
        self._update_page_label()

    def _on_scrape_progress(self, current: int, total: int):
        self.result_label.setText(f"正在爬取第 {current}/{total} 页...")

    def _on_scrape_complete(self, all_rows: list):
        self.search_btn.setEnabled(True)
        self._all_rows = all_rows
        self._populate_table(all_rows)
        self._update_page_label()
        self.result_label.setText(f"共爬取 {len(all_rows)} 条记录")
        logger.info("CDE爬取完成: %d 条记录", len(all_rows))

    def _on_scrape_error(self, error_msg: str):
        self.search_btn.setEnabled(True)
        self.result_label.setText("爬取失败")
        logger.error("CDE爬取失败: %s", error_msg)
        QMessageBox.critical(self, "爬取失败", error_msg)

    def _populate_table(self, rows: list):
        """Map row dicts to table data and display."""
        columns = [
            "受理号", "药品名称", "药品类型", "申请类型",
            "注册分类", "企业名称", "承办日期",
        ]
        data = []
        for r in rows:
            data.append([
                r.get("accept_id", ""),
                r.get("drug_name", ""),
                r.get("drug_type", ""),
                r.get("apply_type", ""),
                r.get("reg_class", ""),
                r.get("company", ""),
                r.get("date", ""),
            ])
        self.table.set_data(columns, data)

    def _update_page_label(self):
        shown = self.table.row_count()
        start = (self._current_page - 1) * 10 + 1 if self._current_page else 1
        end = start + shown - 1
        self.page_label.setText(
            f"第 {start}-{end} 条，共 {len(self._all_rows)} 条"
        )
        self.prev_btn.setEnabled(self._current_page > 1)
        self.next_btn.setEnabled(
            self._current_page > 0 and self._current_page < self._total_pages
        )

    def _prev_page(self):
        pass  # Not implemented — scrape_all handles pagination

    def _next_page(self):
        pass  # Not implemented — scrape_all handles pagination

    def _do_reset(self):
        self.keyword_input.clear()
        self.date_from.clear()
        self.date_to.clear()
        self.drug_type_combo.setCurrentIndex(0)
        self.apply_type_combo.setCurrentIndex(0)
        self.reg_class_combo.setCurrentIndex(0)
        self.scrape_all_checkbox.setChecked(False)

    # ─────────────────────────────────────────────────────────────
    # Action logic
    # ─────────────────────────────────────────────────────────────

    def _update_selected_count(self):
        count = len(self.table.checked_rows())
        self.selected_label.setText(f"已选 {count} 条")
        self.download_btn.setEnabled(count > 0)

    def _get_default_save_dir(self) -> str:
        """Get default download directory: QSettings > DB directory."""
        settings = get_settings()
        saved = settings.value("cde/download_path", "")
        if saved and os.path.isdir(saved):
            return saved
        db_path = get_recent_db() or DEFAULT_DB_NAME
        return os.path.dirname(os.path.abspath(db_path))

    def _browse_save_path(self):
        current = self.save_path_input.text().strip() or self._get_default_save_dir()
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", current)
        if path:
            self.save_path_input.setText(path)

    def _do_download(self):
        """Start two-phase download: parse detail pages → download PDFs."""
        checked = self.table.checked_rows()
        if not checked:
            return

        rows = [self._all_rows[i] for i in checked if i < len(self._all_rows)]
        detail_urls = [r.get("detail_url", "") for r in rows if r.get("detail_url")]
        if not detail_urls:
            QMessageBox.information(self, "提示", "选中的记录没有详情页链接")
            return

        save_dir = self.save_path_input.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "提示", "请先设置保存路径")
            return

        # Confirm
        msg = (
            f"即将下载 {len(rows)} 个药品的审评报告和说明书 PDF（共 {len(detail_urls) * 2} 个文件）。\n"
            f"保存到: {save_dir}\n\n确认开始下载？"
        )
        if QMessageBox.question(self, "确认下载", msg) != QMessageBox.Yes:
            return

        # Save to QSettings
        get_settings().setValue("cde/download_path", save_dir)

        self.download_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.download_progress.start(len(detail_urls) * 2)
        self.download_progress.set_cancel_enabled(True)
        self.download_progress.cancelled.connect(self._cancel_download)

        # Phase 1: parse detail pages to get PDF URLs
        self.result_label.setText(f"正在解析详情页 (0/{len(detail_urls)})...")
        self._download_rows = rows
        self._download_save_dir = save_dir
        self._detail_pdf_map = {}

        try:
            from service.cde_scraper import CdeListScraper
            scraper = CdeListScraper(self)
            scraper.detail_parsed.connect(self._on_detail_parsed)
            scraper.detail_error.connect(self._on_detail_error)
            scraper.detail_complete.connect(self._on_detail_parse_complete)
            self._detail_scraper = scraper
            scraper.parse_detail_pages(detail_urls)
        except Exception as e:
            self._scrape_error.emit(str(e))

    def _on_detail_parsed(self, detail_url: str, data: dict):
        """Handle detail page parsed — store classified attachment info keyed by detail_url."""
        attachments = data.get("attachments", [])

        # Classify by doc_type from scraper
        review_url = ""
        instr_url = ""
        for att in attachments:
            if att.get("doc_type") == "review_report" and not review_url:
                review_url = att.get("url", "")
            elif att.get("doc_type") == "instructions" and not instr_url:
                instr_url = att.get("url", "")

        self._detail_pdf_map[detail_url] = {
            "review_report": review_url,
            "instructions": instr_url,
        }

        done = len(self._detail_pdf_map)
        total = len(self._download_rows)
        self.result_label.setText(f"正在解析详情页 ({done}/{total})...")
        logger.info("CDE详情页解析: %s — 审评报告=%s, 说明书=%s",
                     detail_url, bool(review_url), bool(instr_url))

        if done >= total:
            self._start_pdf_downloads()

    def _on_detail_error(self, detail_url: str, error: str):
        """Handle detail page parse error."""
        logger.warning("CDE详情页解析失败: %s — %s", detail_url, error)
        self._detail_pdf_map[detail_url] = {"review_report": "", "instructions": ""}

        done = len(self._detail_pdf_map)
        total = len(self._download_rows)
        self.result_label.setText(f"正在解析详情页 ({done}/{total})...")

        if done >= total:
            self._start_pdf_downloads()

    def _on_detail_parse_complete(self, results: dict):
        """Handle all detail pages parsed — start PDF downloads."""
        logger.info("CDE详情页解析全部完成: %d 个", len(results))
        self._start_pdf_downloads()

    def _start_pdf_downloads(self):
        """Build PDF download queue and start CdePdfDownloader."""
        # Guard against double-call (from _on_detail_parsed + _on_detail_parse_complete)
        if self._pdf_downloader is not None:
            return

        docs = []
        for row in self._download_rows:
            detail_url = row.get("detail_url", "")
            drug_name = row.get("drug_name", "")
            accept_id = row.get("accept_id", "")
            pdf_info = self._detail_pdf_map.get(detail_url, {})

            review_url = pdf_info.get("review_report", "")
            if review_url:
                docs.append({
                    "url": review_url,
                    "drug_name": drug_name,
                    "accept_id": accept_id,
                    "doc_type": "审评报告",
                })
            else:
                logger.info("CDE: 无审评报告URL — %s (detail_url=%s)", drug_name, detail_url)

            instr_url = pdf_info.get("instructions", "")
            if instr_url:
                docs.append({
                    "url": instr_url,
                    "drug_name": drug_name,
                    "accept_id": accept_id,
                    "doc_type": "说明书",
                })
            else:
                logger.info("CDE: 无说明书URL — %s (detail_url=%s)", drug_name, detail_url)

        if not docs:
            self.search_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.download_progress.reset()
            self.result_label.setText("未能从详情页提取到 PDF 链接")
            QMessageBox.warning(self, "下载失败", "未能从详情页提取到 PDF 链接")
            return

        self.result_label.setText(f"开始下载 PDF ({len(docs)} 个)...")

        try:
            from service.cde_pdf_downloader import CdePdfDownloader
            self._pdf_downloader = CdePdfDownloader(self)
            self._pdf_downloader.download_progress.connect(self._on_pdf_download_progress)
            self._pdf_downloader.download_complete.connect(self._on_pdf_download_complete)
            self._pdf_downloader.download(docs, self._download_save_dir)
        except ImportError:
            self.search_btn.setEnabled(True)
            self.download_btn.setEnabled(True)
            self.download_progress.reset()
            QMessageBox.critical(
                self, "下载失败",
                "PySide6-WebEngineWidgets 未安装，无法下载 CDE 文档。",
            )

    def _cancel_download(self):
        self.download_progress.set_cancel_enabled(False)
        self.download_progress.update_progress(0, 0, "正在取消...")
        if self._scraper:
            self._scraper.cancel()
        if self._pdf_downloader:
            self._pdf_downloader.cancel()

    def _on_pdf_download_progress(self, current: int, total: int, filename: str):
        self.download_progress.update_progress(
            current, total, f"正在下载 {filename} ({current}/{total})"
        )
        logger.info("CDE文档下载进度: %d/%d - %s", current, total, filename)

    def _on_pdf_download_complete(self, results: dict):
        self.download_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self._pdf_downloader = None  # Reset guard for next download batch

        try:
            self.download_progress.cancelled.disconnect(self._cancel_download)
        except RuntimeError:
            pass

        success = results.get("success", [])
        failed = results.get("failed", [])
        skipped = results.get("skipped", [])
        skip_count = len(skipped)

        self.download_progress.finish(success=len(success), failed=len(failed))

        if not failed:
            parts = [f"{len(success)} 个文件已保存"]
            if skip_count:
                parts.append(f"{skip_count} 个已存在跳过")
            self.result_label.setText(f"下载完成: {', '.join(parts)}")
            self.app.status.showMessage(f"已下载 {len(success)} 个 CDE 审评文档")
        else:
            parts = [f"成功: {len(success)} 个"]
            if skip_count:
                parts.append(f"跳过: {skip_count} 个")
            parts.append(f"失败: {len(failed)} 个")
            self.result_label.setText(f"下载完成: {', '.join(parts)}")
            errors = "\n".join(
                f"- {f.get('filename', '未知')}: {f.get('error', '未知错误')}"
                for f in failed[:10]
            )
            skip_line = f"\n跳过: {skip_count} 个" if skip_count else ""
            QMessageBox.warning(
                self, "部分下载失败",
                f"成功: {len(success)} 个\n"
                f"失败: {len(failed)} 个{skip_line}\n\n"
                f"失败详情:\n{errors}",
            )

    # ─────────────────────────────────────────────────────────────
    # Right-click context menu
    # ─────────────────────────────────────────────────────────────

    def _on_table_context_menu(self, source_row: int, global_pos):
        """Show context menu for right-clicked row."""
        if source_row >= len(self._all_rows):
            return

        row_data = self._all_rows[source_row]
        detail_url = row_data.get("detail_url", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = "https://www.cde.org.cn" + detail_url

        menu = QMenu(self)
        open_action = menu.addAction("在浏览器中打开")
        open_action.setEnabled(bool(detail_url))

        is_checked = source_row in self.table.checked_rows()
        toggle_text = "取消勾选" if is_checked else "勾选此行"
        toggle_action = menu.addAction(toggle_text)

        chosen = menu.exec(global_pos)
        if chosen == open_action and detail_url:
            webbrowser.open(detail_url)
        elif chosen == toggle_action:
            self.table.set_check_state(source_row, not is_checked)
