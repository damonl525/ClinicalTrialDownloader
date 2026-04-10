#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProgressWidget — progress bar with per-item status and statistics.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QProgressBar, QLabel, QPushButton,
)
from PySide6.QtCore import Qt, Signal, Slot

from ui.theme import SPACING


class ProgressWidget(QWidget):
    """Progress bar with label, stats, and cancel button."""

    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["xs"])

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

        # Status row
        status_row = QHBoxLayout()
        self.label = QLabel("")
        status_row.addWidget(self.label)

        self.stats = QLabel("")
        self.stats.setStyleSheet("color: #64748B;")
        status_row.addWidget(self.stats)

        status_row.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        status_row.addWidget(self.cancel_btn)

        layout.addLayout(status_row)

    def start(self, total: int):
        """Show progress bar and start tracking."""
        self.bar.setVisible(True)
        self.bar.setMinimum(0)
        self.bar.setMaximum(total)
        self.bar.setValue(0)
        self.cancel_btn.setVisible(True)

    def update_progress(self, current: int, total: int, message: str = ""):
        """Update progress bar and label."""
        self.bar.setMaximum(total)
        self.bar.setValue(current)
        pct = int(current / total * 100) if total > 0 else 0
        self.label.setText(f"{message} ({pct}%)")

    def finish(self, success: int, skipped: int = 0, failed: int = 0):
        """Mark operation as complete."""
        self.bar.setValue(self.bar.maximum())
        self.cancel_btn.setVisible(False)
        parts = [f"完成: {success}"]
        if skipped:
            parts.append(f"跳过: {skipped}")
        if failed:
            parts.append(f"失败: {failed}")
        self.stats.setText("  ".join(parts))
        self.label.setText("")

    def reset(self):
        """Reset to initial state."""
        self.bar.setVisible(False)
        self.bar.setValue(0)
        self.label.setText("")
        self.stats.setText("")
        self.cancel_btn.setVisible(False)

    def set_indeterminate(self):
        """Switch to indeterminate mode (no known total)."""
        self.bar.setMinimum(0)
        self.bar.setMaximum(0)
        self.bar.setVisible(True)
        self.cancel_btn.setVisible(True)
