#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3 UI tests — settings dialog, table context menu, status bar, theme.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest


def _get_app():
    """Get or create QApplication for testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestSettingsDialog(unittest.TestCase):
    """Settings dialog tests."""

    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def test_dialog_opens(self):
        """Settings dialog can be instantiated."""
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        self.assertIsNotNone(dlg)
        self.assertEqual(dlg.windowTitle(), "设置")
        dlg.close()

    def test_theme_combo_values(self):
        """Theme combo has system/light/dark options."""
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        combo = dlg.theme_combo
        self.assertEqual(combo.count(), 3)
        values = [combo.itemData(i) for i in range(combo.count())]
        self.assertIn("system", values)
        self.assertIn("light", values)
        self.assertIn("dark", values)
        dlg.close()

    def test_timeout_spin_range(self):
        """Timeout spinbox has valid range."""
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        self.assertEqual(dlg.timeout_spin.minimum(), 30)
        self.assertEqual(dlg.timeout_spin.maximum(), 600)
        dlg.close()

    def test_get_theme_returns_combo_data(self):
        """get_theme() returns the current combo data."""
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        dlg.theme_combo.setCurrentIndex(1)  # light
        self.assertEqual(dlg.get_theme(), "light")
        dlg.theme_combo.setCurrentIndex(2)  # dark
        self.assertEqual(dlg.get_theme(), "dark")
        dlg.close()


class TestTableContextMenu(unittest.TestCase):
    """Export tab right-click context menu tests."""

    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def test_context_menu_policy_set(self):
        """Table view has custom context menu policy."""
        from ui.tabs.export_tab import ExportTab
        from ui.main_window import MainWindow

        window = MainWindow()
        tab = ExportTab(window)
        self.assertEqual(
            tab.table_view.contextMenuPolicy(),
            Qt.CustomContextMenu,
        )
        window.close()

    def test_on_table_context_menu_with_invalid_pos(self):
        """Context menu at invalid position does nothing."""
        from ui.tabs.export_tab import ExportTab
        from ui.main_window import MainWindow

        window = MainWindow()
        tab = ExportTab(window)
        # Should not raise
        tab._on_table_context_menu(tab.table_view.viewport().rect().bottomRight())
        window.close()

    def test_copy_rows_with_data(self):
        """_copy_rows copies data to clipboard."""
        from ui.tabs.export_tab import ExportTab
        from ui.main_window import MainWindow

        window = MainWindow()
        tab = ExportTab(window)
        tab._full_df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        tab._current_page = 1
        tab._copy_rows([0, 1])
        clipboard = QApplication.clipboard().text()
        self.assertIn("1", clipboard)
        self.assertIn("x", clipboard)
        window.close()

    def test_copy_rows_empty(self):
        """_copy_rows with empty list does nothing."""
        from ui.tabs.export_tab import ExportTab
        from ui.main_window import MainWindow

        window = MainWindow()
        tab = ExportTab(window)
        tab._full_df = pd.DataFrame({"a": [1]})
        tab._copy_rows([])  # Should not raise
        window.close()


class TestStatusBarDbInfo(unittest.TestCase):
    """Status bar DB info label tests."""

    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def test_db_status_label_exists(self):
        """MainWindow has _db_status_label."""
        from ui.main_window import MainWindow

        window = MainWindow()
        self.assertTrue(hasattr(window, '_db_status_label'))
        window.close()

    def test_update_db_status_no_bridge(self):
        """update_db_status with no bridge clears label."""
        from ui.main_window import MainWindow

        window = MainWindow()
        window.bridge = None
        window.update_db_status()
        self.assertEqual(window._db_status_label.text(), "")
        window.close()


class TestCollapsibleCardQSS(unittest.TestCase):
    """CollapsibleCard uses objectName-based QSS (not inline styles)."""

    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def test_header_object_name(self):
        """Header has objectName for QSS targeting."""
        from ui.widgets.card import CollapsibleCard

        card = CollapsibleCard("Test")
        self.assertEqual(card.header.objectName(), "collapsibleHeader")
        card.close()

    def test_body_object_name(self):
        """Body has objectName for QSS targeting."""
        from ui.widgets.card import CollapsibleCard

        card = CollapsibleCard("Test")
        self.assertEqual(card.body.objectName(), "collapsibleBody")
        card.close()

    def test_toggle_expanded(self):
        """Toggling changes hidden state."""
        from ui.widgets.card import CollapsibleCard

        card = CollapsibleCard("Test", expanded=False)
        self.assertTrue(card.body.isHidden())
        card.header.click()
        self.assertFalse(card.body.isHidden())
        card.close()


class TestThemeQSS(unittest.TestCase):
    """Theme QSS generation tests."""

    def test_light_qss_contains_key_selectors(self):
        """Light theme QSS contains all key selectors."""
        from ui.theme import COLORS_LIGHT, _build_qss

        qss = _build_qss(COLORS_LIGHT)
        for selector in [
            "QFrame#card",
            "QPushButton#primary",
            "QPushButton#secondary",
            "QTabWidget::pane",
            "QLineEdit",
            "QComboBox",
            "QCheckBox",
            "QPushButton#collapsibleHeader",
            "QFrame#collapsibleBody",
            "QGroupBox",
            "QSpinBox",
        ]:
            self.assertIn(selector, qss, f"Missing selector: {selector}")

    def test_dark_qss_uses_dark_colors(self):
        """Dark theme QSS uses dark palette colors."""
        from ui.theme import COLORS_DARK, _build_qss

        qss = _build_qss(COLORS_DARK)
        self.assertIn(COLORS_DARK["bg"], qss)
        self.assertIn(COLORS_DARK["surface"], qss)
        self.assertIn(COLORS_DARK["border"], qss)


class TestMainWindowSettingsAction(unittest.TestCase):
    """MainWindow has settings button in toolbar."""

    @classmethod
    def setUpClass(cls):
        cls.app = _get_app()

    def test_settings_btn_exists(self):
        """Settings button is in toolbar."""
        from ui.main_window import MainWindow

        window = MainWindow()
        self.assertTrue(hasattr(window, 'settings_btn'))
        window.close()

    def test_theme_btn_exists(self):
        """Theme button is in toolbar."""
        from ui.main_window import MainWindow

        window = MainWindow()
        self.assertTrue(hasattr(window, 'theme_btn'))
        window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
