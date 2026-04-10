#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Design system — colors, fonts, spacing, and QSS generation.
"""

from PySide6.QtGui import QFont
from PySide6.QtCore import QSettings

# ================================================================
# Colors
# ================================================================

COLORS_LIGHT = {
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "bg": "#FFFFFF",
    "surface": "#F8FAFC",
    "border": "#E2E8F0",
    "text": "#1E293B",
    "text_secondary": "#64748B",
}

COLORS_DARK = {
    "primary": "#3B82F6",
    "primary_hover": "#60A5FA",
    "success": "#34D399",
    "warning": "#FBBF24",
    "error": "#F87171",
    "bg": "#0F172A",
    "surface": "#1E293B",
    "border": "#334155",
    "text": "#F1F5F9",
    "text_secondary": "#94A3B8",
}

# ================================================================
# Fonts
# ================================================================

FONT_FAMILY = "Microsoft YaHei UI"
FONT_FAMILY_MONO = "Consolas"

FONT_SIZES = {
    "title": 16,
    "heading": 13,
    "body": 10,
    "caption": 9,
    "mono": 10,
}


def get_font(role: str) -> QFont:
    """Return a QFont for the given role."""
    if role == "mono":
        return QFont(FONT_FAMILY_MONO, FONT_SIZES.get(role, 10))
    size = FONT_SIZES.get(role, 10)
    bold = role in ("title", "heading")
    font = QFont(FONT_FAMILY, size)
    font.setBold(bold)
    return font

# ================================================================
# Spacing & radius
# ================================================================

SPACING = {"xs": 4, "sm": 8, "md": 16, "lg": 24}
RADIUS = {"sm": 4, "md": 8, "lg": 12}

# ================================================================
# QSS generation
# ================================================================

def _build_qss(colors: dict) -> str:
    """Generate application stylesheet from a color palette."""
    return f"""
    /* ── Global ── */
    QWidget {{
        font-family: "{FONT_FAMILY}";
        font-size: {FONT_SIZES['body']}pt;
    }}

    /* ── Cards (QFrame with objectName "card") ── */
    QFrame#card {{
        background: {colors['surface']};
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['lg']}px;
        padding: {SPACING['md']}px;
    }}

    /* ── Primary button ── */
    QPushButton#primary {{
        background: {colors['primary']};
        color: #FFFFFF;
        border: none;
        border-radius: {RADIUS['md']}px;
        padding: {SPACING['sm']}px {SPACING['md']}px;
        font-weight: bold;
        min-height: 32px;
    }}
    QPushButton#primary:hover {{
        background: {colors['primary_hover']};
    }}
    QPushButton#primary:disabled {{
        background: {colors['border']};
        color: {colors['text_secondary']};
    }}

    /* ── Secondary button ── */
    QPushButton#secondary {{
        background: transparent;
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['md']}px;
        padding: {SPACING['sm']}px {SPACING['md']}px;
        min-height: 32px;
    }}
    QPushButton#secondary:hover {{
        background: {colors['surface']};
    }}

    /* ── Danger button (red outline for destructive actions) ── */
    QPushButton#danger {{
        background: transparent;
        border: 1px solid {colors['error']};
        border-radius: {RADIUS['md']}px;
        padding: {SPACING['sm']}px {SPACING['md']}px;
        color: {colors['error']};
        min-height: 32px;
    }}
    QPushButton#danger:hover {{
        background: {colors['error']};
        color: #FFFFFF;
    }}

    /* ── Tab bar ── */
    QTabWidget::pane {{
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['sm']}px;
        background: {colors['bg']};
        top: -1px;
    }}
    QTabWidget::tab-bar {{
        alignment: left;
    }}
    QTabBar::tab {{
        padding: {SPACING['sm']}px {SPACING['lg']}px;
        border: 1px solid {colors['border']};
        border-bottom: none;
        border-top-left-radius: {RADIUS['md']}px;
        border-top-right-radius: {RADIUS['md']}px;
        margin-right: 2px;
        min-width: 60px;
    }}
    QTabBar::tab:selected {{
        background: {colors['bg']};
        font-weight: bold;
    }}
    QTabBar::tab:!selected {{
        background: {colors['surface']};
    }}

    /* ── Line edit ── */
    QLineEdit {{
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['md']}px;
        padding: {SPACING['sm']}px {SPACING['md']}px;
        min-height: 28px;
    }}
    QLineEdit:focus {{
        border-color: {colors['primary']};
    }}

    /* ── Status bar ── */
    QStatusBar {{
        background: {colors['surface']};
        border-top: 1px solid {colors['border']};
        padding: {SPACING['xs']}px;
        color: {colors['text_secondary']};
    }}

    /* ── Toolbar ── */
    QToolBar {{
        background: {colors['bg']};
        border-bottom: 1px solid {colors['border']};
        spacing: {SPACING['sm']}px;
        padding: {SPACING['xs']}px;
    }}

    /* ── Progress bar ── */
    QProgressBar {{
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['md']}px;
        text-align: center;
        min-height: 20px;
    }}
    QProgressBar::chunk {{
        background: {colors['primary']};
        border-radius: {RADIUS['md']}px;
    }}

    /* ── Scrollbar ── */
    QScrollBar:vertical {{
        border: none;
        background: {colors['surface']};
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: {colors['border']};
        min-height: 30px;
        border-radius: 5px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    /* ── ComboBox ── */
    QComboBox {{
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['md']}px;
        padding: {SPACING['sm']}px {SPACING['md']}px;
        min-height: 28px;
        background: {colors['bg']};
    }}
    QComboBox:focus {{
        border-color: {colors['primary']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid {colors['border']};
        background: {colors['bg']};
        selection-background-color: {colors['primary']};
        selection-color: #FFFFFF;
    }}

    /* ── CheckBox ── */
    QCheckBox {{
        spacing: {SPACING['sm']}px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {colors['border']};
        border-radius: 3px;
        background: {colors['bg']};
    }}
    QCheckBox::indicator:checked {{
        background: {colors['primary']};
        border-color: {colors['primary']};
    }}

    /* ── ScrollArea ── */
    QScrollArea {{
        border: none;
        background: transparent;
    }}

    /* ── GroupBox (settings dialog) ── */
    QGroupBox {{
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['md']}px;
        margin-top: 12px;
        padding-top: 16px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: {SPACING['md']}px;
        padding: 0 {SPACING['sm']}px;
    }}

    /* ── CollapsibleCard ── */
    QPushButton#collapsibleHeader {{
        text-align: left;
        padding: {SPACING['sm']}px {SPACING['md']}px;
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['sm']}px;
        background: {colors['surface']};
        font-weight: bold;
    }}
    QPushButton#collapsibleHeader:checked {{
        border-bottom-left-radius: 0;
        border-bottom-right-radius: 0;
    }}
    QFrame#collapsibleBody {{
        border: 1px solid {colors['border']};
        border-top: none;
        border-bottom-left-radius: {RADIUS['sm']}px;
        border-bottom-right-radius: {RADIUS['sm']}px;
        background: {colors['bg']};
    }}

    /* ── SpinBox ── */
    QSpinBox {{
        border: 1px solid {colors['border']};
        border-radius: {RADIUS['md']}px;
        padding: {SPACING['sm']}px {SPACING['md']}px;
        min-height: 28px;
        background: {colors['bg']};
    }}
    QSpinBox:focus {{
        border-color: {colors['primary']};
    }}

    /* ── DialogButtonBox ── */
    QDialogButtonBox QPushButton {{
        min-width: 80px;
    }}
    """
