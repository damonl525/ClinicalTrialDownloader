#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Colored log viewer — QTextEdit with level-based coloring,
search (Ctrl+F), level filtering, and export.
"""

import html as html_module
import os
from datetime import datetime
from typing import List, Tuple

from PySide6.QtWidgets import (
    QTextEdit, QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QLabel, QFileDialog,
    QSizePolicy, QApplication,
)
from PySide6.QtGui import QTextCursor, QTextDocument, QKeySequence, QAction
from PySide6.QtCore import Qt, Signal

from ui.theme import get_font


class LogViewer(QWidget):
    """Read-only log display with search, filter, and export."""

    LEVEL_STYLE = {
        "info":    ("ℹ", "#3B82F6"),   # Blue
        "success": ("✓", "#10B981"),   # Green
        "warning": ("⚠", "#F59E0B"),   # Orange
        "error":   ("✗", "#EF4444"),   # Red
    }

    MAX_LINES = 2000

    # Internal signal for thread-safe append
    _append_signal = Signal(str, str)  # level, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._log_entries: List[Tuple[str, str, str]] = []  # (level, timestamp, message)
        self._visible_levels = {"info", "success", "warning", "error"}
        self._search_visible = False

        self._setup_ui()
        self._setup_shortcuts()

        # Thread-safe append via signal
        self._append_signal.connect(self._do_append)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # --- Toolbar row: filter buttons + export ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self._filter_btns = {}
        for level, (icon, color) in self.LEVEL_STYLE.items():
            btn = QPushButton(f"{icon} {level.capitalize()}")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                f"QPushButton {{ color: {color}; border: 1px solid {color}; "
                f"border-radius: 3px; padding: 0 6px; font-size: 11px; }}"
                f"QPushButton:checked {{ background: {color}22; }}"
                f"QPushButton:!checked {{ background: transparent; color: #666; border-color: #666; }}"
            )
            btn.toggled.connect(lambda checked, lv=level: self._toggle_level(lv, checked))
            toolbar.addWidget(btn)
            self._filter_btns[level] = btn

        toolbar.addStretch()

        self._export_btn = QPushButton("导出日志")
        self._export_btn.setFixedHeight(24)
        self._export_btn.setStyleSheet(
            "QPushButton { border: 1px solid #666; border-radius: 3px; "
            "padding: 0 8px; font-size: 11px; }"
            "QPushButton:hover { background: #333; }"
        )
        self._export_btn.clicked.connect(self._export_log)
        toolbar.addWidget(self._export_btn)

        layout.addLayout(toolbar)

        # --- Search bar (hidden by default) ---
        self._search_bar = QWidget()
        self._search_bar.setVisible(False)
        search_layout = QHBoxLayout(self._search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索日志...")
        self._search_input.setFixedHeight(24)
        self._search_input.returnPressed.connect(self._find_next)
        search_layout.addWidget(self._search_input)

        self._find_prev_btn = QPushButton("▲")
        self._find_prev_btn.setFixedSize(24, 24)
        self._find_prev_btn.clicked.connect(self._find_prev)
        search_layout.addWidget(self._find_prev_btn)

        self._find_next_btn = QPushButton("▼")
        self._find_next_btn.setFixedSize(24, 24)
        self._find_next_btn.clicked.connect(self._find_next)
        search_layout.addWidget(self._find_next_btn)

        self._search_close_btn = QPushButton("✕")
        self._search_close_btn.setFixedSize(24, 24)
        self._search_close_btn.clicked.connect(self._hide_search)
        search_layout.addWidget(self._search_close_btn)

        layout.addWidget(self._search_bar)

        # --- Text display ---
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(get_font("mono"))
        self._text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self._text_edit)

    def _setup_shortcuts(self):
        # Ctrl+F to toggle search
        find_action = QAction(self)
        find_action.setShortcut(QKeySequence("Ctrl+F"))
        find_action.triggered.connect(self._toggle_search)
        self.addAction(find_action)

        # Escape to close search
        esc_action = QAction(self)
        esc_action.setShortcut(QKeySequence("Escape"))
        esc_action.triggered.connect(self._hide_search)
        self.addAction(esc_action)

    # ================================================================
    # Public API (thread-safe via signal)
    # ================================================================

    def append_log(self, level: str, message: str):
        """Thread-safe: append a log message with level-based coloring."""
        self._append_signal.emit(level, message)

    def clear_log(self):
        self._text_edit.clear()
        self._log_entries.clear()

    def log_info(self, msg: str):
        self.append_log("info", msg)

    def log_success(self, msg: str):
        self.append_log("success", msg)

    def log_warning(self, msg: str):
        self.append_log("warning", msg)

    def log_error(self, msg: str):
        self.append_log("error", msg)

    def get_plain_text(self) -> str:
        """Return all log entries as plain text (for export)."""
        lines = []
        for level, ts, msg in self._log_entries:
            icon, _ = self.LEVEL_STYLE.get(level, ("•", ""))
            lines.append(f"[{ts}] {icon} [{level}] {msg}")
        return "\n".join(lines)

    # ================================================================
    # Internal append (runs on main thread via signal)
    # ================================================================

    def _do_append(self, level: str, message: str):
        """Append log entry — always called on main thread."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_entries.append((level, timestamp, message))

        # Trim if over limit
        if len(self._log_entries) > self.MAX_LINES:
            self._log_entries = self._log_entries[-self.MAX_LINES:]
            self._rebuild_display()
            return

        # Incremental append (only if level is visible)
        if level in self._visible_levels:
            self._append_html(level, timestamp, message)

        # Auto-scroll
        self._text_edit.moveCursor(QTextCursor.End)

    def _append_html(self, level: str, timestamp: str, message: str):
        icon, color = self.LEVEL_STYLE.get(level, ("•", "#64748B"))
        safe_msg = html_module.escape(message)
        html = (
            f'<span style="color:#94A3B8">{timestamp}</span> '
            f'<span style="color:{color}; font-weight:bold">{icon}</span> '
            f'<span style="color:{color}">{safe_msg}</span>'
        )
        self._text_edit.append(html)

    def _rebuild_display(self):
        """Rebuild the text display from stored entries (after filter change)."""
        self._text_edit.clear()
        for level, ts, msg in self._log_entries:
            if level in self._visible_levels:
                self._append_html(level, ts, msg)
        self._text_edit.moveCursor(QTextCursor.End)

    # ================================================================
    # Level filtering
    # ================================================================

    def _toggle_level(self, level: str, checked: bool):
        if checked:
            self._visible_levels.add(level)
        else:
            self._visible_levels.discard(level)
        self._rebuild_display()

    # ================================================================
    # Search
    # ================================================================

    def _toggle_search(self):
        if self._search_bar.isVisible():
            self._hide_search()
        else:
            self._show_search()

    def _show_search(self):
        self._search_bar.setVisible(True)
        self._search_input.setFocus()
        self._search_input.selectAll()

    def _hide_search(self):
        self._search_bar.setVisible(False)
        # Clear search highlighting
        cursor = self._text_edit.textCursor()
        cursor.clearSelection()
        self._text_edit.setTextCursor(cursor)

    def _find_next(self):
        text = self._search_input.text()
        if not text:
            return
        self._text_edit.find(text)

    def _find_prev(self):
        text = self._search_input.text()
        if not text:
            return
        self._text_edit.find(text, QTextDocument.FindFlag.FindBackward)

    # ================================================================
    # Export
    # ================================================================

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", f"ctrdata_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "文本文件 (*.txt);;所有文件 (*)",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.get_plain_text())
