#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for FilterTableView — header filter dropdowns + checkbox column."""

import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from ui.widgets.filter_table import FilterTableView


class TestFilterTableViewBasic(unittest.TestCase):
    """Basic construction and data loading."""

    def test_create_widget(self):
        w = FilterTableView()
        self.assertIsNotNone(w)

    def test_set_data_creates_model(self):
        w = FilterTableView()
        columns = ["药物名", "申请号", "提交类型"]
        data = [
            ["Keytruda", "NDA215985", "ORIG-1"],
            ["Opdivo", "NDA208835", "ORIG-1"],
        ]
        w.set_data(columns, data)
        # Row count should be 2 (checkbox is an extra column)
        self.assertEqual(w.row_count(), 2)

    def test_check_all(self):
        w = FilterTableView()
        columns = ["药物名"]
        data = [["A"], ["B"], ["C"]]
        w.set_data(columns, data)
        w.check_all()
        self.assertEqual(w.checked_rows(), [0, 1, 2])

    def test_uncheck_all(self):
        w = FilterTableView()
        columns = ["药物名"]
        data = [["A"], ["B"]]
        w.set_data(columns, data)
        w.check_all()
        w.uncheck_all()
        self.assertEqual(w.checked_rows(), [])

    def test_check_single_row(self):
        w = FilterTableView()
        columns = ["药物名"]
        data = [["A"], ["B"]]
        w.set_data(columns, data)
        w.set_check_state(0, True)
        self.assertEqual(w.checked_rows(), [0])

    def test_get_row_data(self):
        w = FilterTableView()
        columns = ["药物名", "申请号"]
        data = [["Keytruda", "NDA215985"]]
        w.set_data(columns, data)
        row = w.get_row_data(0)
        self.assertEqual(row["药物名"], "Keytruda")
        self.assertEqual(row["申请号"], "NDA215985")


class TestFilterTableViewFilter(unittest.TestCase):
    """Header filter functionality."""

    def test_unique_values_for_column(self):
        w = FilterTableView()
        columns = ["药物名", "提交类型"]
        data = [
            ["Keytruda", "ORIG-1"],
            ["Keytruda", "SUPPL-1"],
            ["Opdivo", "ORIG-1"],
        ]
        w.set_data(columns, data)
        vals = w.unique_values(1)
        self.assertEqual(sorted(vals), ["ORIG-1", "SUPPL-1"])

    def test_filter_hides_rows(self):
        w = FilterTableView()
        columns = ["药物名", "提交类型"]
        data = [
            ["Keytruda", "ORIG-1"],
            ["Keytruda", "SUPPL-1"],
            ["Opdivo", "ORIG-1"],
        ]
        w.set_data(columns, data)
        # Hide SUPPL-1
        w.set_column_filter(1, ["ORIG-1"])
        self.assertEqual(w.visible_row_count(), 2)

    def test_clear_filter(self):
        w = FilterTableView()
        columns = ["药物名", "提交类型"]
        data = [
            ["Keytruda", "ORIG-1"],
            ["Keytruda", "SUPPL-1"],
        ]
        w.set_data(columns, data)
        w.set_column_filter(1, ["ORIG-1"])
        w.clear_column_filter(1)
        self.assertEqual(w.visible_row_count(), 2)


if __name__ == "__main__":
    unittest.main()
