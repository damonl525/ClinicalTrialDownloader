#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Version dialog — shows app version, credits, and changelog.
"""

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont

from ui.theme import get_font


class VersionDialog(QDialog):
    """Dialog displaying application version, credits, and changelog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setMinimumSize(500, 450)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._build_ui()

    def _build_ui(self):
        from core.constants import APP_NAME, APP_NAME_EN, APP_VERSION

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header: icon + name + version
        header = QHBoxLayout()

        icon_label = QLabel()
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets", "icon.png",
        )
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            icon_label.setPixmap(pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(icon_label)

        title_layout = QVBoxLayout()
        name_label = QLabel(APP_NAME)
        name_label.setFont(get_font("title"))
        title_layout.addWidget(name_label)

        ver_label = QLabel(f"v{APP_VERSION}")
        ver_label.setFont(get_font("heading"))
        ver_label.setStyleSheet("color: #3B82F6;")
        title_layout.addWidget(ver_label)

        header.addLayout(title_layout)
        header.addStretch()
        layout.addLayout(header)

        # Tech stack
        tech_label = QLabel("Built with Python + PySide6 + R ctrdata")
        tech_label.setFont(get_font("caption"))
        tech_label.setStyleSheet("color: gray;")
        layout.addWidget(tech_label)

        # Changelog section
        changelog_header = QLabel("版本历史")
        changelog_header.setFont(get_font("heading"))
        layout.addWidget(changelog_header)

        changelog_edit = QTextEdit()
        changelog_edit.setReadOnly(True)
        changelog_edit.setFont(get_font("mono"))

        changelog_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "CHANGELOG.md",
        )
        if os.path.exists(changelog_path):
            with open(changelog_path, "r", encoding="utf-8") as f:
                changelog_edit.setPlainText(f.read())
        else:
            changelog_edit.setPlainText("CHANGELOG.md not found.")

        layout.addWidget(changelog_edit)

        # OK button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primary")
        ok_btn.setFixedWidth(100)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)
