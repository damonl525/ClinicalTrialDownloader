#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Log dialog — non-modal dialog with LogViewer for runtime log inspection.

Reuses the existing LogViewer widget with level filter, search (Ctrl+F),
and export capabilities.
"""

import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSizePolicy,
)
from PySide6.QtCore import Qt

from ui.theme import get_font, SPACING
from ui.widgets.log_viewer import LogViewer
from core.log_handler import QtLogHandler


class LogDialog(QDialog):
    """Non-modal log viewer dialog connected to Python logging."""

    def __init__(self, qt_handler: QtLogHandler, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行日志")
        self.resize(750, 500)
        self.setMinimumSize(500, 300)
        self._handler = qt_handler
        self._setup_ui()
        self._connect_handler()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING["sm"])

        # Log viewer (reuse existing widget)
        self._log_viewer = LogViewer()
        self._log_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._log_viewer)

        # Bottom controls
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(SPACING["sm"])

        # Log level selector
        bottom_row.addWidget(QLabel("日志级别:"))
        self._level_combo = QComboBox()
        self._level_combo.addItem("DEBUG", logging.DEBUG)
        self._level_combo.addItem("INFO", logging.INFO)
        self._level_combo.addItem("WARNING", logging.WARNING)
        self._level_combo.addItem("ERROR", logging.ERROR)
        self._level_combo.setCurrentIndex(1)  # INFO
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        bottom_row.addWidget(self._level_combo)

        bottom_row.addStretch()

        # Clear button
        self._clear_btn = QPushButton("清除")
        self._clear_btn.setObjectName("secondary")
        self._clear_btn.clicked.connect(self._log_viewer.clear_log)
        bottom_row.addWidget(self._clear_btn)

        # Close button
        self._close_btn = QPushButton("关闭")
        self._close_btn.setObjectName("secondary")
        self._close_btn.clicked.connect(self.close)
        bottom_row.addWidget(self._close_btn)

        layout.addLayout(bottom_row)

    def _connect_handler(self):
        """Connect the QtLogHandler signal to the log viewer."""
        # Replay buffered history so user sees logs from before dialog was opened
        for level, msg in self._handler.get_buffered():
            self._log_viewer.append_log(level, msg)
        self._handler.log_message.connect(self._on_log_message)

    def _on_log_message(self, level: str, message: str):
        """Receive log from QtLogHandler and forward to LogViewer."""
        self._log_viewer.append_log(level, message)

    def _on_level_changed(self, index: int):
        """Adjust handler log level based on combo box selection."""
        level = self._level_combo.currentData()
        self._handler.setLevel(level)

    def closeEvent(self, event):
        """Disconnect handler signal when dialog is closed."""
        try:
            self._handler.log_message.disconnect(self._on_log_message)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(event)
