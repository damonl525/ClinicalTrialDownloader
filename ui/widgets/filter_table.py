#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FilterTableView — QTableView with header filter dropdowns and checkbox column.

Features:
- Column 0 is a checkbox column (select/deselect rows)
- Clicking filterable column headers shows a dropdown with unique values
- Uses custom QSortFilterProxyModel subclass for filtering
- get_row_data() returns dict mapping column names to values
- context_menu_requested signal for right-click actions
"""

import webbrowser

from PySide6.QtWidgets import (
    QTableView,
    QHeaderView,
    QMenu,
)
from PySide6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Signal,
    QPoint,
)
from PySide6.QtGui import QAction


class _TableModel(QAbstractTableModel):
    """Internal data model. Column 0 is checkbox, rest are data columns."""

    def __init__(self, columns: list, data: list, parent=None):
        super().__init__(parent)
        self._columns = ["\u2611"] + columns  # checkbox column prepended
        self._data = data  # list of lists
        self._checks = [False] * len(data)

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if role == Qt.DisplayRole or role == Qt.EditRole:
            if col == 0:
                return None
            if row < len(self._data):
                return str(self._data[row][col - 1])
        if role == Qt.CheckStateRole and col == 0:
            if row < len(self._checks):
                return Qt.Checked if self._checks[row] else Qt.Unchecked
            return Qt.Unchecked
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._columns[section]
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        if index.column() == 0 and role == Qt.CheckStateRole:
            self._checks[index.row()] = value == Qt.Checked
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    def flags(self, index):
        flags = super().flags(index)
        if index.column() == 0:
            flags |= Qt.ItemIsUserCheckable
        return flags


class _FilterProxyModel(QSortFilterProxyModel):
    """Custom proxy that filters by column value sets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._column_filters = {}  # proxy_col -> set of allowed values

    def set_column_filters(self, filters: dict):
        self._column_filters = filters
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._column_filters:
            return True
        source_model = self.sourceModel()
        for proxy_col, allowed in self._column_filters.items():
            idx = source_model.index(source_row, proxy_col)
            val = source_model.data(idx, Qt.DisplayRole)
            if val not in allowed:
                return False
        return True


class FilterTableView(QTableView):
    """QTableView with header filter dropdowns and checkbox selection."""

    checked_changed = Signal()
    context_menu_requested = Signal(int, QPoint)  # source_row, global_pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_model = None
        self._proxy_model = _FilterProxyModel(self)
        self._columns = []
        self._filterable_columns = set()

        self.setModel(self._proxy_model)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        # Header click for filter
        self.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

    def set_data(
        self,
        columns: list,
        data: list,
        filterable: list = None,
        keep_filters: bool = False,
    ):
        """Load data into the table.

        Args:
            keep_filters: If True, preserve current column filters across
                          data reload (e.g. pagination). If False, clear all.
        """
        saved = dict(self._proxy_model._column_filters) if keep_filters else None
        self._columns = columns
        self._source_model = _TableModel(columns, data, self)
        self._proxy_model.setSourceModel(self._source_model)
        self._proxy_model.set_column_filters(saved or {})
        self._filterable_columns = set(filterable or range(len(columns)))

        # Set checkbox column width
        self.setColumnWidth(0, 40)

    # -- Row count helpers --

    def row_count(self) -> int:
        return self._source_model.rowCount() if self._source_model else 0

    def visible_row_count(self) -> int:
        return self._proxy_model.rowCount()

    # -- Checkbox: explicit click handling for reliability --

    def mouseReleaseEvent(self, event):
        """Handle checkbox clicks on column 0 explicitly."""
        if event.button() == Qt.LeftButton and self._source_model:
            index = self.indexAt(event.pos())
            if index.isValid() and index.column() == 0:
                source_idx = self._proxy_model.mapToSource(index)
                current = self._source_model.data(source_idx, Qt.CheckStateRole)
                new_state = Qt.Unchecked if current == Qt.Checked else Qt.Checked
                self._source_model.setData(source_idx, new_state, Qt.CheckStateRole)
                self.checked_changed.emit()
                return
        super().mouseReleaseEvent(event)

    def check_all(self):
        if not self._source_model:
            return
        for i in range(self._proxy_model.rowCount()):
            proxy_idx = self._proxy_model.index(i, 0)
            source_idx = self._proxy_model.mapToSource(proxy_idx)
            self._source_model.setData(source_idx, Qt.Checked, Qt.CheckStateRole)
        self.checked_changed.emit()

    def uncheck_all(self):
        if not self._source_model:
            return
        for i in range(self._proxy_model.rowCount()):
            proxy_idx = self._proxy_model.index(i, 0)
            source_idx = self._proxy_model.mapToSource(proxy_idx)
            self._source_model.setData(source_idx, Qt.Unchecked, Qt.CheckStateRole)
        self.checked_changed.emit()

    def set_check_state(self, row: int, checked: bool):
        if not self._source_model:
            return
        idx = self._source_model.index(row, 0)
        self._source_model.setData(
            idx, Qt.Checked if checked else Qt.Unchecked, Qt.CheckStateRole
        )
        self.checked_changed.emit()

    def checked_rows(self) -> list:
        """Return list of source row indices that are checked."""
        if not self._source_model:
            return []
        return [
            i for i in range(self._source_model.rowCount())
            if self._source_model._checks[i]
        ]

    # -- Data access --

    def get_row_data(self, source_row: int) -> dict:
        """Return dict {column_name: value} for a source row."""
        if not self._source_model or source_row >= len(self._source_model._data):
            return {}
        row_data = self._source_model._data[source_row]
        return {
            name: row_data[i]
            for i, name in enumerate(self._columns)
            if i < len(row_data)
        }

    # -- Filter operations --

    def unique_values(self, col_index: int) -> list:
        """Get sorted unique values for a data column (0-based, excluding checkbox)."""
        if not self._source_model:
            return []
        vals = set()
        for row in self._source_model._data:
            if col_index < len(row):
                vals.add(str(row[col_index]))
        return sorted(vals)

    def set_column_filter(self, col_index: int, allowed: list):
        """Filter column (0-based data column) to only show these values."""
        proxy_col = col_index + 1
        current = dict(self._proxy_model._column_filters)
        current[proxy_col] = set(str(v) for v in allowed)
        self._proxy_model.set_column_filters(current)

    def clear_column_filter(self, col_index: int):
        proxy_col = col_index + 1
        current = dict(self._proxy_model._column_filters)
        current.pop(proxy_col, None)
        self._proxy_model.set_column_filters(current)

    # -- Header click -> filter menu --

    def _on_header_clicked(self, logical_index: int):
        if logical_index == 0:  # checkbox column
            return
        data_col = logical_index - 1
        if data_col not in self._filterable_columns:
            return

        values = self.unique_values(data_col)
        if not values:
            return

        current_filters = self._proxy_model._column_filters
        current_allowed = current_filters.get(logical_index, set(values))

        menu = QMenu(self)
        menu.setSeparatorsCollapsible(False)

        # Add checkable actions for each unique value
        val_actions = []
        for val in values:
            action = QAction(val, self)
            action.setCheckable(True)
            action.setChecked(val in current_allowed)
            menu.addAction(action)
            val_actions.append((val, action))

        # Apply filter immediately when action toggled
        def _apply_filter():
            allowed = set(v for v, a in val_actions if a.isChecked())
            cur = dict(self._proxy_model._column_filters)
            if allowed == set(values):
                cur.pop(logical_index, None)
            else:
                cur[logical_index] = allowed
            self._proxy_model.set_column_filters(cur)

        for _, action in val_actions:
            action.toggled.connect(lambda checked, _f=_apply_filter: _f())

        # Select all / Deselect all
        menu.addSeparator()
        select_all = QAction("全选", self)
        deselect_all = QAction("取消全选", self)

        def _select_all():
            for _, a in val_actions:
                a.setChecked(True)

        def _deselect_all():
            for _, a in val_actions:
                a.setChecked(False)

        select_all.triggered.connect(_select_all)
        deselect_all.triggered.connect(_deselect_all)
        menu.addAction(select_all)
        menu.addAction(deselect_all)

        # Position below header section
        header = self.horizontalHeader()
        x = header.sectionViewportPosition(logical_index)
        y = header.height()
        pos = header.mapToGlobal(QPoint(x, y))

        menu.exec(pos)

    # -- Context menu (right-click) --

    def _on_context_menu(self, pos: QPoint):
        """Handle right-click context menu."""
        index = self.indexAt(pos)
        if not index.isValid():
            return
        source_idx = self._proxy_model.mapToSource(index)
        source_row = source_idx.row()
        global_pos = self.viewport().mapToGlobal(pos)
        self.context_menu_requested.emit(source_row, global_pos)
