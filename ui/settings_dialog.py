#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Settings dialog — theme, R timeout, default paths.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QFileDialog, QGroupBox,
    QFormLayout, QDialogButtonBox, QMessageBox,
)
from PySide6.QtCore import Qt

from ui.theme import get_font, SPACING
from ui.app import (
    get_settings, get_theme_mode, set_theme_mode,
    get_recent_db, set_recent_db, resolve_theme, apply_theme,
)


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(420)
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING["md"])

        # ── Theme group ──
        theme_group = QGroupBox("外观")
        theme_form = QFormLayout(theme_group)
        theme_form.setSpacing(SPACING["sm"])

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", "system")
        self.theme_combo.addItem("亮色模式", "light")
        self.theme_combo.addItem("暗色模式", "dark")
        theme_form.addRow("主题:", self.theme_combo)

        layout.addWidget(theme_group)

        # ── Database group ──
        db_group = QGroupBox("数据库")
        db_form = QFormLayout(db_group)
        db_form.setSpacing(SPACING["sm"])

        db_path_row = QHBoxLayout()
        self.db_path_input = QLineEdit()
        db_path_row.addWidget(self.db_path_input)
        self.db_browse_btn = QPushButton("浏览...")
        self.db_browse_btn.setObjectName("secondary")
        self.db_browse_btn.clicked.connect(self._browse_db_path)
        db_path_row.addWidget(self.db_browse_btn)
        db_form.addRow("默认路径:", db_path_row)

        layout.addWidget(db_group)

        # ── Documents group ──
        doc_group = QGroupBox("文档下载")
        doc_form = QFormLayout(doc_group)
        doc_form.setSpacing(SPACING["sm"])

        doc_path_row = QHBoxLayout()
        self.doc_path_input = QLineEdit()
        doc_path_row.addWidget(self.doc_path_input)
        self.doc_browse_btn = QPushButton("浏览...")
        self.doc_browse_btn.setObjectName("secondary")
        self.doc_browse_btn.clicked.connect(self._browse_doc_path)
        doc_path_row.addWidget(self.doc_browse_btn)
        doc_form.addRow("默认保存路径:", doc_path_row)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 600)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setToolTip("单个试验文档下载超时时间")
        doc_form.addRow("下载超时:", self.timeout_spin)

        layout.addWidget(doc_group)

        # ── Buttons ──
        btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self._save_and_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _load_settings(self):
        settings = get_settings()
        # Theme
        mode = get_theme_mode()
        idx = self.theme_combo.findData(mode)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        # DB path
        self.db_path_input.setText(get_recent_db())
        # Doc path
        self.doc_path_input.setText(
            settings.value("doc/default_path", "./documents")
        )
        # Timeout
        self.timeout_spin.setValue(
            int(settings.value("doc/timeout", 120))
        )

    def _browse_db_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择默认数据库文件", "",
            "SQLite 数据库 (*.sqlite *.db);;All Files (*)"
        )
        if path:
            self.db_path_input.setText(path)

    def _browse_doc_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择默认文档保存目录")
        if path:
            self.doc_path_input.setText(path)

    def _save_and_accept(self):
        settings = get_settings()

        # Save theme
        new_mode = self.theme_combo.currentData()
        old_mode = get_theme_mode()
        set_theme_mode(new_mode)

        # If theme changed, apply immediately
        if new_mode != old_mode:
            effective = resolve_theme(new_mode)
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                apply_theme(app, effective)

        # Save DB path
        db_path = self.db_path_input.text().strip()
        if db_path:
            set_recent_db(db_path)

        # Save doc path
        settings.setValue("doc/default_path", self.doc_path_input.text().strip())

        # Save timeout
        settings.setValue("doc/timeout", self.timeout_spin.value())

        self.accept()

    def get_theme(self) -> str:
        return self.theme_combo.currentData()
