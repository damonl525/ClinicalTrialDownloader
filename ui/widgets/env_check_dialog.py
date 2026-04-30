#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Environment check dialog — shows R installation guidance when issues are detected.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QTextEdit, QDialogButtonBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.theme import SPACING

# Minimum required ctrdata version
MIN_CTRDATA_VERSION = "1.26.0"


def _parse_version(v: str):
    """Parse version string to comparable tuple."""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


class EnvCheckDialog(QDialog):
    """Dialog showing R environment status and installation guidance."""

    def __init__(self, env_info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("R 环境检查")
        self.setMinimumWidth(520)
        self.setMinimumHeight(320)
        self._env_info = env_info
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING["md"])

        r_available = self._env_info.get("r_available", False)
        error = self._env_info.get("error", "")
        packages = self._env_info.get("packages", {})
        r_version = self._env_info.get("r_version", "")

        if not r_available:
            self._build_r_missing(layout)
        elif error:
            self._build_packages_missing(layout, packages, error)
        else:
            self._build_all_ok(layout, packages, r_version)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

    def _build_r_missing(self, layout: QVBoxLayout):
        title = QLabel("R 环境未安装")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #EF4444;")
        layout.addWidget(title)

        desc = QLabel(
            "本工具依赖 R 语言和 ctrdata 包来下载临床试验数据。\n"
            "请按以下步骤安装："
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        steps = QTextEdit()
        steps.setReadOnly(True)
        steps.setMaximumHeight(180)
        steps.setHtml(
            "<ol>"
            "<li>下载并安装 R：<br>"
            "<a href='https://cran.r-project.org/'>https://cran.r-project.org/</a></li>"
            "<li>安装完成后，重启本工具</li>"
            "<li>在 R 控制台中安装所需包：<br>"
            "<code>install.packages(c('ctrdata', 'nodbi', 'RSQLite', 'chromote'))</code></li>"
            "</ol>"
        )
        steps.setOpenExternalLinks(True)
        layout.addWidget(steps)

    def _build_packages_missing(self, layout: QVBoxLayout, packages: dict, error: str):
        title = QLabel("R 包不完整")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #F59E0B;")
        layout.addWidget(title)

        missing = []
        version_warnings = []
        for pkg, ver in packages.items():
            if not ver:
                missing.append(pkg)
            elif pkg == "ctrdata" and _parse_version(ver) < _parse_version(MIN_CTRDATA_VERSION):
                version_warnings.append(f"ctrdata {ver}（需要 >= {MIN_CTRDATA_VERSION}）")

        info_parts = []
        if missing:
            info_parts.append(f"缺少包: {', '.join(missing)}")
        if version_warnings:
            info_parts.append(f"版本过低: {'; '.join(version_warnings)}")

        desc = QLabel("\n".join(info_parts))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #F59E0B;")
        layout.addWidget(desc)

        guide = QLabel("请在 R 控制台中执行以下命令安装/更新：")
        guide.setWordWrap(True)
        layout.addWidget(guide)

        cmd = 'install.packages(c("ctrdata", "nodbi", "RSQLite", "chromote"))'
        cmd_edit = QTextEdit()
        cmd_edit.setReadOnly(True)
        cmd_edit.setMaximumHeight(60)
        cmd_edit.setText(cmd)
        layout.addWidget(cmd_edit)

        copy_btn = QPushButton("复制安装命令")
        copy_btn.setObjectName("secondary")
        copy_btn.clicked.connect(lambda: self._copy_text(cmd))
        layout.addWidget(copy_btn, alignment=Qt.AlignLeft)

    def _build_all_ok(self, layout: QVBoxLayout, packages: dict, r_version: str):
        title = QLabel("R 环境正常")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #10B981;")
        layout.addWidget(title)

        info_lines = [f"{r_version}"]
        for pkg, ver in packages.items():
            info_lines.append(f"  {pkg}: {ver}" if ver else f"  {pkg}: 未安装")

        info = QLabel("\n".join(info_lines))
        info.setFont(QFont("Consolas", 10))
        layout.addWidget(info)

    def _copy_text(self, text: str):
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
