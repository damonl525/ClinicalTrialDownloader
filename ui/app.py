#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QApplication setup, theme initialization, and settings persistence.
"""

import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from ui.theme import COLORS_LIGHT, COLORS_DARK, _build_qss

# ── Settings helpers ──

_SETTINGS_ORG = "ClinicalTrialDownloader"
_SETTINGS_APP = "App"


def get_settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def get_theme_mode() -> str:
    """Return current theme mode: 'system' | 'light' | 'dark'."""
    return get_settings().value("ui/theme_mode", "system")


def set_theme_mode(mode: str):
    get_settings().setValue("ui/theme_mode", mode)


def get_recent_db() -> str:
    return get_settings().value("db/recent_path", "")


def set_recent_db(path: str):
    get_settings().setValue("db/recent_path", path)


# ── Theme application ──

def _detect_system_dark() -> bool:
    """Best-effort system dark mode detection."""
    try:
        import darkdetect
        return darkdetect.isDark()
    except ImportError:
        pass
    # Fallback: check Windows registry
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0  # 0 = dark
        except OSError:
            pass
    return False


def resolve_theme(mode: str) -> str:
    """Resolve effective theme name from mode setting."""
    if mode == "system":
        return "dark" if _detect_system_dark() else "light"
    return mode


def apply_theme(app: QApplication, mode: str):
    """Apply theme to the QApplication. mode is 'light' or 'dark'."""
    colors = COLORS_DARK if mode == "dark" else COLORS_LIGHT
    qss = _build_qss(colors)

    # Try pyqtdarktheme as base layer
    # Supports both v2.x (setup_theme) and v0.x (load_stylesheet)
    try:
        import qdarktheme
        if hasattr(qdarktheme, "setup_theme"):
            base = qdarktheme.setup_theme(mode)
        else:
            base = qdarktheme.load_stylesheet(mode)
        app.setStyleSheet(base + qss)
    except (ImportError, Exception):
        app.setStyleSheet(qss)


# ── App factory ──

def create_app() -> tuple[QApplication, str]:
    """
    Create QApplication with theme applied.
    Returns (app, theme_name).
    """
    # High DPI
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    mode = get_theme_mode()
    effective = resolve_theme(mode)
    apply_theme(app, effective)

    return app, effective
