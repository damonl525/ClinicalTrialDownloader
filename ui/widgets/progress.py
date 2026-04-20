#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProgressPanel — progress bar with ETA, detail line, and per-item statistics.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QProgressBar, QLabel, QPushButton,
)
from PySide6.QtCore import Qt, Signal, Slot

from ui.theme import SPACING


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string.

    - < 60s   -> "45s"
    - >= 60s  -> "2m 5s"
    - >= 3600s -> "1h 1m"
    """
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        minutes, secs = divmod(total, 60)
        return f"{minutes}m {secs}s"
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


class ProgressPanel(QWidget):
    """Progress bar with label, detail, stats, ETA, and cancel button."""

    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["xs"])

        # Row 1: Progress bar
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.bar)

        # Row 2: Status row — [label] [stretch] [cancel_btn]
        status_row = QHBoxLayout()
        self.label = QLabel("")
        status_row.addWidget(self.label)

        status_row.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        status_row.addWidget(self.cancel_btn)

        layout.addLayout(status_row)

        # Row 3: Detail line (hidden when empty)
        self.detail = QLabel("")
        self.detail.setStyleSheet("color: #64748B; font-size: 11px;")
        self.detail.setVisible(False)
        layout.addWidget(self.detail)

        # Row 4: Stats line (hidden when empty)
        self.stats = QLabel("")
        self.stats.setStyleSheet("color: #64748B; font-size: 11px;")
        self.stats.setVisible(False)
        layout.addWidget(self.stats)

    # ── Existing methods (backward-compatible) ──

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
        # Exit indeterminate mode (min=0,max=0) before setting value
        self.bar.setMaximum(1)
        self.bar.setValue(1)
        self.cancel_btn.setVisible(False)
        parts = [f"完成: {success}"]
        if skipped:
            parts.append(f"跳过: {skipped}")
        if failed:
            parts.append(f"失败: {failed}")
        self.stats.setText("  ".join(parts))
        self.stats.setVisible(True)
        self.label.setText("")
        self.detail.setVisible(False)

    def reset(self):
        """Reset to initial state."""
        self.bar.setVisible(False)
        self.bar.setValue(0)
        self.bar.setMaximum(1)  # Reset from indeterminate mode
        self.label.setText("")
        self.stats.setText("")
        self.stats.setVisible(False)
        self.detail.setText("")
        self.detail.setVisible(False)
        self.cancel_btn.setVisible(False)

    def set_indeterminate(self):
        """Switch to indeterminate mode (no known total)."""
        self.bar.setMinimum(0)
        self.bar.setMaximum(0)
        self.bar.setVisible(True)
        self.cancel_btn.setVisible(True)

    # ── New methods ──

    def update_eta(self, elapsed_seconds: float, estimated_remaining: float):
        """Show elapsed and estimated remaining time in stats label."""
        elapsed = _format_duration(elapsed_seconds)
        remaining = _format_duration(estimated_remaining)
        self.stats.setText(f"已用时 {elapsed} | 预计剩余 {remaining}")
        self.stats.setVisible(True)

    def update_detail(self, message: str):
        """Show a secondary detail line below the main label."""
        self.detail.setText(message)
        self.detail.setVisible(bool(message))

    def set_cancel_enabled(self, enabled: bool):
        """Show or hide the cancel button independently."""
        self.cancel_btn.setVisible(enabled)


# Backward-compatible alias
ProgressWidget = ProgressPanel
