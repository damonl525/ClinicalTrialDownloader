#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main window — QMainWindow with toolbar, 3-tab widget, and status bar.
"""

import logging
import os
import threading

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QLabel, QWidget, QVBoxLayout,
    QSizePolicy, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction

from ui.theme import get_font
from ui.tabs.database_tab import DatabaseTab
from ui.tabs.search_tab import SearchTab
from ui.tabs.export_tab import ExportTab
from ui.tabs.fda_tab import FdaTab
from ui.tabs.cde_tab import CdeTab
from ui.app import get_theme_mode, set_theme_mode, resolve_theme, apply_theme
from core.logger import setup_file_logging, remove_file_logging
from core.constants import APP_NAME, APP_VERSION

try:
    import qtawesome as qta
    _HAS_ICONS = True
except ImportError:
    _HAS_ICONS = False


def _icon(name: str, color: str = None):
    if _HAS_ICONS:
        try:
            return qta.icon(name, color=color)
        except Exception:
            pass
    return None


class MainWindow(QMainWindow):
    """Application main window with 3-tab layout."""

    # Signal: thread-safe env check result → main thread dialog
    _env_check_complete = Signal(dict, bool)

    def __init__(self, bridge=None):
        super().__init__()
        self.bridge = bridge
        self.env_info = None  # Store latest env check result
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(950, 720)
        self.setMinimumSize(800, 600)

        # Shared state (mirrors ctrdata_gui.py)
        self.filtered_ids = []
        self.current_data = None
        self.current_search_ids = None
        self.db_total_records = "?"

        self._build_toolbar()
        self._build_tabs()
        self._build_status_bar()

        # Connect signal before starting check
        self._env_check_complete.connect(self._on_env_check_complete)
        self._check_r_environment()

        # Qt log handler — bridges Python logging to GUI log dialog
        from core.log_handler import QtLogHandler
        self._qt_handler = QtLogHandler(self)
        self._qt_handler.setFormatter(logging.Formatter(
            "[%(levelname)s] %(name)s: %(message)s",
        ))
        self._qt_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(self._qt_handler)
        # Ensure root logger allows INFO+ through to handler
        if logging.getLogger().level > logging.INFO:
            logging.getLogger().setLevel(logging.INFO)
        self._log_dialog = None  # Created on demand

        # Optional file logging (controlled by QSettings)
        self._file_log_handler = None
        from PySide6.QtCore import QSettings
        settings = QSettings("ctrdata_downloader", "MainWindow")
        if settings.value("file_logging", False, type=bool):
            self._file_log_handler = setup_file_logging()

        # Window icon
        self._set_window_icon()

        # Auto-show guide on first launch (unless user opted out)
        from PySide6.QtCore import QSettings
        settings = QSettings("ctrdata_downloader", "MainWindow")
        if not settings.value("guide_dont_show", False, type=bool):
            self._show_guide_dialog(auto_opened=True)

    # ── Cleanup ──

    def closeEvent(self, event):
        """Cancel any running R process on window close."""
        if self.bridge:
            try:
                self.bridge.cancel()
            except Exception:
                pass
        # Clean up log handlers
        if self._file_log_handler:
            remove_file_logging(self._file_log_handler)
        if self._qt_handler:
            logging.getLogger().removeHandler(self._qt_handler)
        if self._log_dialog:
            self._log_dialog.close()
        event.accept()

    # ── Toolbar ──

    def _build_toolbar(self):
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)

        title = QLabel("  临床试验数据下载器  ")
        title.setFont(get_font("title"))
        toolbar.addWidget(title)

        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # Guide button with icon (accent color for visibility)
        self.guide_btn = QPushButton()
        guide_icon = _icon("fa5s.book-open", color="#3B82F6")
        if guide_icon:
            self.guide_btn.setIcon(guide_icon)
        else:
            self.guide_btn.setText("指南")
        self.guide_btn.setToolTip("查看操作指南 (F1)")
        self.guide_btn.setShortcut("F1")
        self.guide_btn.setStyleSheet(
            "QPushButton { color: #3B82F6; border: 1px solid #3B82F6; border-radius: 4px; padding: 4px 8px; }"
            "QPushButton:hover { background: #3B82F6; color: white; }"
        )
        self.guide_btn.clicked.connect(self._show_guide_dialog)
        toolbar.addWidget(self.guide_btn)

        # Theme toggle button with icon
        self.theme_btn = QPushButton()
        theme_icon = _icon("fa5s.palette")
        if theme_icon:
            self.theme_btn.setIcon(theme_icon)
        else:
            self.theme_btn.setText("主题")
        self.theme_btn.setToolTip("切换亮色/暗色主题")
        self.theme_btn.setObjectName("secondary")
        self.theme_btn.clicked.connect(self._cycle_theme)
        toolbar.addWidget(self.theme_btn)

        # Settings button with icon
        self.settings_btn = QPushButton()
        settings_icon = _icon("fa5s.cog")
        if settings_icon:
            self.settings_btn.setIcon(settings_icon)
        else:
            self.settings_btn.setText("设置")
        self.settings_btn.setToolTip("打开设置对话框")
        self.settings_btn.setObjectName("secondary")
        self.settings_btn.clicked.connect(self._open_settings)
        toolbar.addWidget(self.settings_btn)

        # Log viewer button
        self.log_btn = QPushButton()
        log_icon = _icon("fa5s.terminal")
        if log_icon:
            self.log_btn.setIcon(log_icon)
        else:
            self.log_btn.setText("日志")
        self.log_btn.setToolTip("查看运行日志")
        self.log_btn.setObjectName("secondary")
        self.log_btn.clicked.connect(self._show_log_dialog)
        toolbar.addWidget(self.log_btn)

    def _cycle_theme(self):
        modes = ["system", "light", "dark"]
        current = get_theme_mode()
        idx = modes.index(current) if current in modes else 0
        next_mode = modes[(idx + 1) % len(modes)]
        set_theme_mode(next_mode)
        effective = resolve_theme(next_mode)
        apply_theme(self.app_instance(), effective)
        mode_labels = {"system": "跟随系统", "light": "亮色", "dark": "暗色"}
        self.theme_btn.setToolTip(f"当前: {mode_labels.get(next_mode, next_mode)} (点击切换)")

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    def _show_guide_dialog(self, auto_opened=False):
        from ui.widgets.guide_dialog import GuideDialog
        dlg = GuideDialog(self, auto_opened=auto_opened)
        dlg.exec()

    def _show_log_dialog(self):
        """Show (or create) the non-modal log viewer dialog."""
        from ui.widgets.log_dialog import LogDialog
        if self._log_dialog is None or not self._log_dialog.isVisible():
            self._log_dialog = LogDialog(self._qt_handler, self)
            self._log_dialog.show()
        else:
            self._log_dialog.raise_()
            self._log_dialog.activateWindow()

    def _show_version_dialog(self):
        from ui.widgets.version_dialog import VersionDialog
        dlg = VersionDialog(self)
        dlg.exec()

    def app_instance(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    def _set_window_icon(self):
        """Set window icon from assets/icon.ico if available."""
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "icon.png",
        )
        if os.path.exists(icon_path):
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))

    # ── Tabs ──

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.db_tab = DatabaseTab(self)
        self.search_tab = SearchTab(self)
        self.export_tab = ExportTab(self)
        self.tabs.addTab(self.db_tab, "数据库")
        self.tabs.addTab(self.search_tab, "搜索与下载")
        self.tabs.addTab(self.export_tab, "提取与导出")
        self.fda_tab = FdaTab(self)
        self.tabs.addTab(self.fda_tab, "FDA审评资料")
        self.cde_tab = CdeTab(self)
        self.tabs.addTab(self.cde_tab, "CDE上市药品")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        # Auto-extract after search download
        self.search_tab.download_finished.connect(self._on_search_download_finished)

    # ── Status bar ──

    def _on_tab_changed(self, index: int):
        """Refresh scope counts when switching to export tab."""
        if index == 2:  # Export tab
            if hasattr(self.export_tab, 'refresh_scope_counts'):
                self.export_tab.refresh_scope_counts()

    def _on_search_download_finished(self, result):
        """Auto-navigate to ExportTab and trigger extraction after download."""
        success_ids = result.get("success", [])
        if not success_ids:
            return
        self.tabs.setCurrentIndex(2)
        self.export_tab.auto_extract(success_ids)

    def _build_status_bar(self):
        self.status = self.statusBar()
        self.status.showMessage("就绪")

        # Clickable version label (QPushButton for reliable click handling)
        self._version_label = QPushButton(f"v{APP_VERSION}")
        self._version_label.setFlat(True)
        self._version_label.setFont(get_font("caption"))
        self._version_label.setStyleSheet(
            "QPushButton { color: #64748B; border: none; margin-right: 8px; padding: 0; }"
            "QPushButton:hover { color: #3B82F6; }"
        )
        self._version_label.setCursor(Qt.PointingHandCursor)
        self._version_label.setToolTip("点击查看版本历史")
        self._version_label.clicked.connect(self._show_version_dialog)
        self.status.addPermanentWidget(self._version_label)

        self.r_status_label = QLabel("正在检查 R 环境...")
        self.status.addPermanentWidget(self.r_status_label)

        self._db_status_label = QLabel("")
        self._db_status_label.setStyleSheet("color: #64748B; margin-left: 8px;")
        self.status.addPermanentWidget(self._db_status_label)

    def update_db_status(self):
        """Refresh DB info in status bar. Call after connect/download/extract."""
        if not self.bridge or not self.bridge.db_path:
            self._db_status_label.setText("")
            self.db_total_records = "?"
            return
        try:
            info = self.bridge.get_db_info()
            import os
            name = os.path.basename(info.get("path", self.bridge.db_path))
            total = info.get("total_records", "?")
            self.db_total_records = total
            self._db_status_label.setText(f"  {name} | {total} 条记录")
        except Exception:
            self.db_total_records = "?"
            self._db_status_label.setText("")

    # ── R environment check ──

    def _check_r_environment(self, show_dialog_always=False):
        force_dialog = show_dialog_always

        def _worker():
            from ctrdata_core import check_r_environment
            info = check_r_environment()
            self._env_check_complete.emit(info, force_dialog)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_env_check_complete(self, info: dict, show_dialog_always=False):
        """Handle env check result on main thread — update status and show dialog if needed."""
        self.env_info = info

        if info.get("r_available") and not info.get("error"):
            try:
                from ctrdata_core import CtrdataBridge
                # Guard: don't overwrite an already-connected bridge
                if not self.bridge:
                    self.bridge = CtrdataBridge()
                ver = info.get("r_version", "?")
                pkg = info.get("packages", {}).get("ctrdata", "?")
                self._status_msg(f"{ver} + ctrdata {pkg} 就绪", "ok")
            except Exception as e:
                self._status_msg(f"R 初始化失败: {e}", "error")
                self._show_env_dialog(info)
            if show_dialog_always:
                self._show_env_dialog(info)
        elif info.get("r_available"):
            self._status_msg(f"R 包不完整: {info.get('error', '')}", "warn")
            self._show_env_dialog(info)
        else:
            self._status_msg("R 不可用", "error")
            self._show_env_dialog(info)

        # Update DatabaseTab env indicator
        db_tab = self.db_tab if hasattr(self, "db_tab") else None
        if db_tab and hasattr(db_tab, "_update_env_indicator"):
            db_tab._update_env_indicator()

    def _show_env_dialog(self, info: dict):
        from ui.widgets.env_check_dialog import EnvCheckDialog
        dlg = EnvCheckDialog(info, self)
        dlg.exec()

    def _status_msg(self, msg: str, level: str = "info"):
        """Thread-safe status bar update via signal."""
        try:
            color_map = {"ok": "green", "warn": "orange", "error": "red", "info": "gray"}
            color = color_map.get(level, "gray")
            self.r_status_label.setStyleSheet(f"color: {color};")
            self.r_status_label.setText(msg)
        except RuntimeError:
            pass  # Widget already destroyed during shutdown

    # ── Logging ──

    def log(self, msg: str, level: str = "INFO"):
        """Record log message (used by tabs)."""
        if level == "ERROR":
            self.status.showMessage(f"错误: {msg}")
        elif level == "WARNING":
            self.status.showMessage(f"警告: {msg}")
        else:
            self.status.showMessage(msg)
