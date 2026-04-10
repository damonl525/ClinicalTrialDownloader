#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CollapsibleCard — fold/unfold panel with toggle header.
Properly notifies parent layout on expand/collapse.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFrame, QSizePolicy
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from ui.theme import SPACING

try:
    import qtawesome as qta
    _HAS_ICONS = True
except ImportError:
    _HAS_ICONS = False


def _icon(name: str, color: str = None):
    """Safely get a qtawesome icon, returns None if unavailable."""
    if _HAS_ICONS:
        try:
            return qta.icon(name, color=color)
        except Exception:
            pass
    return None


class CollapsibleCard(QWidget):
    """Card with toggle header — click to expand/collapse.

    Uses sizeHint to report proper height and fires LayoutRequest
    events so parent layouts resize correctly on toggle.
    """

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title = title

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header button
        self.header = QPushButton(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setObjectName("collapsibleHeader")
        self.header.clicked.connect(self._toggle)
        self._update_header_icon(expanded)
        layout.addWidget(self.header)

        # Body frame — layout is set later via set_body_layout()
        self.body = QFrame()
        self.body.setObjectName("collapsibleBody")
        self.body.setVisible(expanded)
        layout.addWidget(self.body)

    # ── Toggle ──

    def _toggle(self, checked):
        self._update_header_icon(checked)
        self.body.setVisible(checked)

        # Force parent layout to recalculate
        self.updateGeometry()
        self._notify_ancestors()

    def _update_header_icon(self, expanded: bool):
        """Set header icon and text based on expand state."""
        if expanded:
            icon = _icon("fa5s.chevron-down")
            prefix = "▾"
        else:
            icon = _icon("fa5s.chevron-right")
            prefix = "▸"
        if icon:
            self.header.setIcon(icon)
            self.header.setText(f"  {self._title}")
        else:
            self.header.setIcon(QIcon())
            self.header.setText(f"{prefix} {self._title}")

    def _notify_ancestors(self):
        """Walk up the widget tree and force layout recalculation."""
        w = self.parent()
        while w:
            w.updateGeometry()
            if w.layout():
                w.layout().invalidate()
                w.layout().activate()
            w = w.parent()

    # ── Size hints ──

    def sizeHint(self):
        hint = super().sizeHint()
        if not self.body.isVisible():
            header_h = self.header.sizeHint().height()
            hint.setHeight(header_h)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        if not self.body.isVisible():
            header_h = self.header.minimumSizeHint().height()
            hint.setHeight(header_h)
        return hint

    # ── Body layout ──

    def set_body_layout(self, content_layout):
        """Set the body's content layout. Margins and spacing are enforced."""
        content_layout.setContentsMargins(
            SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"]
        )
        content_layout.setSpacing(SPACING["md"])
        self.body.setLayout(content_layout)
