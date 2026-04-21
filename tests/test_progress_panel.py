#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for ProgressPanel — ETA, detail line, cancel control,
and backward-compatible existing methods.
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# Ensure a QApplication exists (required for QWidget tests)
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.widgets.progress import ProgressPanel, ProgressWidget, _format_duration


class TestFormatDuration(unittest.TestCase):
    """Test the _format_duration helper function."""

    def test_seconds_only(self):
        """< 60s returns seconds-only string like '45s'."""
        self.assertEqual(_format_duration(0), "0s")
        self.assertEqual(_format_duration(1), "1s")
        self.assertEqual(_format_duration(45), "45s")
        self.assertEqual(_format_duration(59), "59s")

    def test_minutes_and_seconds(self):
        """60s-3599s returns 'Xm Ys' format."""
        self.assertEqual(_format_duration(60), "1m 0s")
        self.assertEqual(_format_duration(65), "1m 5s")
        self.assertEqual(_format_duration(125), "2m 5s")
        self.assertEqual(_format_duration(3599), "59m 59s")

    def test_hours_and_minutes(self):
        """>= 3600s returns 'Xh Ym' format."""
        self.assertEqual(_format_duration(3600), "1h 0m")
        self.assertEqual(_format_duration(3660), "1h 1m")
        self.assertEqual(_format_duration(7200), "2h 0m")
        self.assertEqual(_format_duration(7380), "2h 3m")
        self.assertEqual(_format_duration(86400), "24h 0m")

    def test_float_input(self):
        """Float seconds are truncated to int."""
        self.assertEqual(_format_duration(45.7), "45s")
        self.assertEqual(_format_duration(65.9), "1m 5s")
        self.assertEqual(_format_duration(3600.5), "1h 0m")

    def test_negative_input(self):
        """Negative values are clamped to 0."""
        self.assertEqual(_format_duration(-1), "0s")
        self.assertEqual(_format_duration(-100), "0s")


class TestProgressPanelETA(unittest.TestCase):
    """Test update_eta method."""

    def setUp(self):
        self.panel = ProgressPanel()

    def test_eta_formats_elapsed_and_remaining(self):
        """update_eta sets stats text with formatted elapsed/remaining."""
        self.panel.update_eta(elapsed_seconds=45, estimated_remaining=120)
        text = self.panel.stats.text()
        self.assertIn("45s", text)
        self.assertIn("2m 0s", text)
        self.assertIn("已用时", text)
        self.assertIn("预计剩余", text)

    def test_eta_with_hours(self):
        """update_eta handles hour-scale durations."""
        self.panel.update_eta(elapsed_seconds=7200, estimated_remaining=3600)
        text = self.panel.stats.text()
        self.assertIn("2h 0m", text)
        self.assertIn("1h 0m", text)


class TestProgressPanelDetail(unittest.TestCase):
    """Test update_detail method."""

    def setUp(self):
        self.panel = ProgressPanel()

    def test_detail_sets_text(self):
        """update_detail sets the detail label text."""
        self.panel.update_detail("正在处理: NCT12345678")
        self.assertEqual(self.panel.detail.text(), "正在处理: NCT12345678")

    def test_detail_clears_with_empty_string(self):
        """update_detail with empty string clears the detail."""
        self.panel.update_detail("something")
        self.panel.update_detail("")
        self.assertEqual(self.panel.detail.text(), "")

    def test_detail_label_exists(self):
        """detail label is created in constructor."""
        self.assertIsNotNone(self.panel.detail)


class TestProgressPanelCancelControl(unittest.TestCase):
    """Test set_cancel_enabled method."""

    def setUp(self):
        self.panel = ProgressPanel()
        self.panel.show()

    def test_cancel_enabled_shows_button(self):
        """set_cancel_enabled(True) makes cancel button visible."""
        self.panel.cancel_btn.setVisible(False)
        self.panel.set_cancel_enabled(True)
        self.assertTrue(self.panel.cancel_btn.isVisible())

    def test_cancel_disabled_hides_button(self):
        """set_cancel_enabled(False) hides cancel button."""
        self.panel.cancel_btn.setVisible(True)
        self.panel.set_cancel_enabled(False)
        self.assertFalse(self.panel.cancel_btn.isVisible())


class TestProgressPanelBackwardCompat(unittest.TestCase):
    """Ensure all existing methods still work after refactor."""

    def setUp(self):
        self.panel = ProgressPanel()
        self.panel.show()

    def test_start_shows_bar_and_cancel(self):
        """start() shows progress bar and cancel button."""
        self.panel.start(100)
        self.assertTrue(self.panel.bar.isVisible())
        self.assertTrue(self.panel.cancel_btn.isVisible())
        self.assertEqual(self.panel.bar.maximum(), 100)
        self.assertEqual(self.panel.bar.value(), 0)

    def test_update_progress_updates_bar_and_label(self):
        """update_progress() sets bar value and label with percentage."""
        self.panel.start(100)
        self.panel.update_progress(50, 100, "下载中")
        self.assertEqual(self.panel.bar.value(), 50)
        self.assertIn("50%", self.panel.label.text())
        self.assertIn("下载中", self.panel.label.text())

    def test_finish_hides_cancel_and_shows_stats(self):
        """finish() hides cancel button and shows statistics."""
        self.panel.start(100)
        self.panel.finish(success=80, skipped=10, failed=10)
        self.assertFalse(self.panel.cancel_btn.isVisible())
        stats_text = self.panel.stats.text()
        self.assertIn("完成: 80", stats_text)
        self.assertIn("跳过: 10", stats_text)
        self.assertIn("失败: 10", stats_text)

    def test_reset_clears_everything(self):
        """reset() returns to initial state."""
        self.panel.start(100)
        self.panel.update_progress(50, 100, "test")
        self.panel.update_detail("some detail")
        self.panel.reset()
        self.assertFalse(self.panel.bar.isVisible())
        self.assertEqual(self.panel.bar.value(), 0)
        self.assertEqual(self.panel.label.text(), "")
        self.assertEqual(self.panel.stats.text(), "")
        self.assertEqual(self.panel.detail.text(), "")
        self.assertFalse(self.panel.cancel_btn.isVisible())

    def test_set_indeterminate(self):
        """set_indeterminate() sets max to 0 and shows bar."""
        self.panel.set_indeterminate()
        self.assertTrue(self.panel.bar.isVisible())
        self.assertEqual(self.panel.bar.maximum(), 0)
        self.assertTrue(self.panel.cancel_btn.isVisible())

    def test_cancel_signal_fires(self):
        """Clicking cancel emits the cancelled signal."""
        fired = []
        self.panel.cancelled.connect(lambda: fired.append(True))
        self.panel.cancel_btn.click()
        self.assertEqual(len(fired), 1)

    def test_progress_widget_alias(self):
        """ProgressWidget is an alias for ProgressPanel."""
        self.assertIs(ProgressWidget, ProgressPanel)


if __name__ == "__main__":
    unittest.main()
