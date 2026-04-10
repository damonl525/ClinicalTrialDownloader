#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PandasTableModel — QAbstractTableModel for pandas DataFrame display.

Features: lazy rendering, zebra stripes, column sorting, truncation.
"""

import pandas as pd
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor


class PandasTableModel(QAbstractTableModel):
    """Qt model wrapping a pandas DataFrame for QTableView."""

    def __init__(self, df: pd.DataFrame = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()
        self._headers = list(self._df.columns)

    def rowCount(self, parent=QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.DisplayRole:
            val = self._df.iloc[index.row(), index.column()]
            if pd.isna(val):
                return ""
            text = str(val)
            if len(text) > 200:
                return text[:200] + "..."
            return text

        if role == Qt.BackgroundRole and index.row() % 2 == 0:
            return QColor("#F8FAFC")

        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        if column < 0 or column >= len(self._headers):
            return
        self.layoutAboutToBeChanged.emit()
        col_name = self._headers[column]
        ascending = order == Qt.AscendingOrder
        col_data = self._df[col_name]
        # Use numeric sort only if column is mostly numeric
        numeric_col = pd.to_numeric(col_data, errors="coerce")
        if numeric_col.notna().sum() > len(col_data) // 2:
            self._df = self._df.copy()
            self._df["_sort_key"] = numeric_col
            self._df.sort_values("_sort_key", ascending=ascending, inplace=True)
            self._df.drop(columns="_sort_key", inplace=True)
        else:
            self._df = self._df.sort_values(col_name, ascending=ascending)
        self.layoutChanged.emit()

    def update_data(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df
        self._headers = list(df.columns)
        self.endResetModel()

    def get_dataframe(self) -> pd.DataFrame:
        return self._df
