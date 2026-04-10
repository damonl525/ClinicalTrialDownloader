#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tab 1: Database — connect to SQLite via nodbi, query history with incremental update.
"""

import os
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QFrame, QSizePolicy, QScrollArea,
    QMessageBox, QInputDialog,
)
from PySide6.QtCore import Qt, Signal

from ui.theme import get_font, SPACING
from ui.app import get_settings, set_recent_db, get_recent_db
from core.constants import DEFAULT_DB_NAME, DEFAULT_COLLECTION


class DatabaseTab(QWidget):
    """Database connection and query history tab."""

    # Signal for thread-safe history update
    _history_loaded = Signal(object)
    _update_complete = Signal(int, int, int, int)  # query_index, n, success, failed
    _update_error = Signal(str)

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.app = main_window
        self._history_data = None
        self._setup_ui()

        # Connect signals for thread-safe UI updates
        self._history_loaded.connect(self._render_history)
        self._update_complete.connect(self._on_update_complete)
        self._update_error.connect(self._on_update_error)

        # Initialize env indicator from current state
        self._update_env_indicator()

    def _make_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        return frame

    def _setup_ui(self):
        # Wrap entire tab in scroll area for safe resizing
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(SPACING["md"])

        # ── Card: Database connection ──
        card1 = self._make_card()
        card_layout = QVBoxLayout(card1)
        card_layout.setSpacing(SPACING["sm"])

        # Environment status indicator row
        env_row = QHBoxLayout()
        self._env_indicator = QLabel("● R 环境检查中...")
        self._env_indicator.setStyleSheet("color: #64748B; font-size: 9pt;")
        self._env_indicator.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        env_row.addWidget(self._env_indicator)
        self._env_check_btn = QPushButton("重新检测")
        self._env_check_btn.setObjectName("secondary")
        self._env_check_btn.clicked.connect(self._recheck_env)
        env_row.addWidget(self._env_check_btn)
        card_layout.addLayout(env_row)

        card_layout.addWidget(QLabel("数据库文件:"))
        path_row = QHBoxLayout()
        saved_db = get_recent_db() or DEFAULT_DB_NAME
        self.path_input = QLineEdit(saved_db)
        path_row.addWidget(self.path_input)
        self.new_btn = QPushButton("新建")
        self.new_btn.setObjectName("secondary")
        self.new_btn.setMinimumWidth(55)
        self.new_btn.clicked.connect(self._new_db)
        path_row.addWidget(self.new_btn)
        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.setObjectName("secondary")
        self.browse_btn.clicked.connect(self._browse_db)
        path_row.addWidget(self.browse_btn)
        card_layout.addLayout(path_row)

        coll_row = QHBoxLayout()
        coll_row.addWidget(QLabel("集合名称:"))
        self.collection_input = QLineEdit(DEFAULT_COLLECTION)
        self.collection_input.setMaximumWidth(200)
        self.collection_input.setToolTip(
            "数据在 SQLite 数据库中的集合名称，类似于数据表的分组标识。默认 'ctrdata' 即可。"
        )
        coll_row.addWidget(self.collection_input)
        coll_row.addWidget(QLabel("(nodbi 集合，默认 ctrdata)"))
        coll_row.addStretch()
        card_layout.addLayout(coll_row)

        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("连接数据库")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.setMinimumWidth(100)
        self.connect_btn.clicked.connect(self._connect_db)
        btn_row.addWidget(self.connect_btn)
        self.disconnect_btn = QPushButton("断开连接")
        self.disconnect_btn.setObjectName("secondary")
        self.disconnect_btn.setMinimumWidth(80)
        self.disconnect_btn.clicked.connect(self._disconnect_db)
        self.disconnect_btn.setEnabled(False)
        btn_row.addWidget(self.disconnect_btn)
        btn_row.addStretch()
        card_layout.addLayout(btn_row)

        self.info_label = QLabel("未连接")
        self.info_label.setStyleSheet("color: #64748B;")
        self.info_label.setWordWrap(True)
        card_layout.addWidget(self.info_label)

        self.delete_btn = QPushButton("删除数据库")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.setMinimumWidth(90)
        self.delete_btn.clicked.connect(self._delete_db)
        self.delete_btn.setEnabled(False)
        card_layout.addWidget(self.delete_btn, alignment=Qt.AlignLeft)

        layout.addWidget(card1)

        # ── Card: Query history ──
        card2 = self._make_card()
        hist_layout = QVBoxLayout(card2)
        hist_layout.setSpacing(SPACING["sm"])

        hist_header = QHBoxLayout()
        hist_header.addWidget(QLabel("查询历史"))
        hist_header.addStretch()
        self.refresh_btn = QPushButton("刷新历史")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self._refresh_history)
        hist_header.addWidget(self.refresh_btn)
        hist_layout.addLayout(hist_header)

        # Scroll area for history items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        scroll.setMaximumHeight(600)
        self._history_container = QWidget()
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.setSpacing(2)
        self._history_layout.addStretch()
        scroll.setWidget(self._history_container)
        hist_layout.addWidget(scroll)

        layout.addWidget(card2)
        layout.addStretch()

        self._scroll.setWidget(container)
        outer.addWidget(self._scroll)

    def _browse_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据库文件", "",
            "SQLite 数据库 (*.sqlite *.db);;All Files (*)"
        )
        if path:
            self.path_input.setText(path)

    def _new_db(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "新建数据库文件", "trials.db",
            "SQLite 数据库 (*.sqlite *.db);;All Files (*)"
        )
        if not path:
            return
        # Ensure .db extension
        if not path.lower().endswith((".db", ".sqlite")):
            path += ".db"
        self.path_input.setText(path)
        # Auto-connect to create the database
        self._connect_db()

    def _connect_db(self):
        path = self.path_input.text().strip()
        collection = self.collection_input.text().strip()

        if not path:
            QMessageBox.warning(self, "错误", "请指定数据库文件路径")
            return

        self.connect_btn.setEnabled(False)
        self.info_label.setText("正在连接...")

        try:
            if not self.app.bridge:
                from ctrdata_core import CtrdataBridge
                self.app.bridge = CtrdataBridge()

            info = self.app.bridge.connect(path, collection)
            total = info.get("total_records", "?")
            self.info_label.setText(
                f"已连接: {os.path.basename(path)}\n"
                f"路径: {info.get('path', path)}  |  集合: {collection}  |  记录数: {total}"
            )
            self.info_label.setStyleSheet("color: #10B981;")
            self.app.status.showMessage("数据库连接成功")
            set_recent_db(path)

            self._set_connected_state(True)
            self._refresh_history()
            self.app.update_db_status()

        except Exception as e:
            self.info_label.setText(f"连接失败: {e}")
            self.info_label.setStyleSheet("color: #EF4444;")
            QMessageBox.critical(self, "连接失败", str(e))
        finally:
            self.connect_btn.setEnabled(True)

    def _set_connected_state(self, connected: bool):
        """Toggle button states based on connection status."""
        self.disconnect_btn.setEnabled(connected)
        self.delete_btn.setEnabled(connected)

    def _disconnect_db(self):
        """Disconnect from current database."""
        if self.app.bridge:
            self.app.bridge.disconnect()
        self.info_label.setText("未连接")
        self.info_label.setStyleSheet("color: #64748B;")
        self.app.status.showMessage("已断开数据库连接")
        self._set_connected_state(False)
        self._clear_history()
        self.app.update_db_status()

    def _delete_db(self):
        """Delete the current database file with confirmation."""
        if not self.app.bridge or not self.app.bridge.db_path:
            return

        db_path = self.app.bridge.db_path
        db_name = os.path.basename(db_path)

        # Two-step confirmation: first confirm intent
        reply = QMessageBox.warning(
            self, "删除数据库",
            f"确定要删除数据库 \"{db_name}\" 吗？\n\n"
            "此操作不可恢复，数据库文件将被永久删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Second step: type database name to confirm
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "确认删除",
            f'请输入数据库名称 "{db_name}" 以确认删除：',
        )
        if not ok or name != db_name:
            return

        # Disconnect first
        self.app.bridge.disconnect()
        self._clear_history()

        # Remove database file
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"无法删除数据库文件: {e}")
            return

        # Remove associated resume file
        resume_path = os.path.splitext(db_path)[0] + "_doc_resume.json"
        try:
            if os.path.exists(resume_path):
                os.remove(resume_path)
        except Exception:
            pass

        self.info_label.setText("数据库已删除")
        self.info_label.setStyleSheet("color: #64748B;")
        self.app.status.showMessage(f"数据库 {db_name} 已删除")
        self._set_connected_state(False)
        self.app.update_db_status()

    def _clear_history(self):
        """Clear the history display."""
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        lbl = QLabel("暂无查询历史")
        lbl.setStyleSheet("color: #64748B;")
        self._history_layout.insertWidget(0, lbl)

    def _refresh_history(self):
        if not self.app.bridge or not self.app.bridge.db_path:
            return

        def _worker():
            try:
                history = self.app.bridge.get_query_history()
                self._history_loaded.emit(history)
            except Exception as e:
                self._history_loaded.emit(None)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_history(self, history):
        # Clear existing items
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if history is None or history.empty:
            lbl = QLabel("暂无查询历史")
            lbl.setStyleSheet("color: #64748B;")
            self._history_layout.insertWidget(0, lbl)
            return

        self._history_data = history

        for idx, (_, row) in enumerate(history.iterrows()):
            row_widget = QFrame()
            row_widget.setStyleSheet(
                "QFrame { background: #F8FAFC; border-radius: 4px; padding: 4px; }"
            )
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(SPACING["sm"], SPACING["xs"], SPACING["sm"], SPACING["xs"])

            ts = str(row.get("query-timestamp", "?"))[:19]
            reg = str(row.get("query-register", "?"))
            n = str(row.get("query-records", "?"))
            term = str(row.get("query-term", ""))[:80]

            info_text = f"#{idx+1}  {ts}  |  {reg}  |  {n} 条  |  {term}"
            lbl = QLabel(info_text)
            lbl.setToolTip(str(row.get("query-term", "")))
            row_layout.addWidget(lbl)

            query_idx = idx + 1  # R uses 1-based indexing
            update_btn = QPushButton("增量更新")
            update_btn.setObjectName("secondary")
            update_btn.setFixedWidth(100)
            update_btn.setToolTip("重新执行该历史查询，仅下载新增或有变更的试验数据。")
            update_btn.clicked.connect(
                lambda checked, qi=query_idx: self._incremental_update(qi)
            )
            row_layout.addWidget(update_btn)

            self._history_layout.insertWidget(idx, row_widget)

    def _incremental_update(self, query_index: int):
        if not self.app.bridge or not self.app.bridge.db_path:
            QMessageBox.critical(self, "错误", "请先连接数据库")
            return

        reply = QMessageBox.question(
            self, "确认更新",
            f"增量更新查询 #{query_index}？\n\n"
            "仅下载上次查询后有更新的试验数据。",
        )
        if reply != QMessageBox.Yes:
            return

        self.app.status.showMessage(f"正在更新查询 #{query_index}...")

        def _worker():
            try:
                result = self.app.bridge.update_last_query(query_index=query_index)
                n = result.get("n", 0)
                s = result.get("success", [])
                f = result.get("failed", [])
                s_count = len(s) if isinstance(s, list) else (1 if s else 0)
                f_count = len(f) if isinstance(f, list) else (1 if f else 0)
                self._update_complete.emit(query_index, n, s_count, f_count)
            except Exception as e:
                self._update_error.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_complete(self, query_index, n, success, failed):
        self.app.status.showMessage(f"查询 #{query_index} 更新完成: {n} 条记录")
        QMessageBox.information(
            self, "更新完成",
            f"查询 #{query_index} 已更新\n"
            f"更新记录: {n}\n成功: {success}\n失败: {failed}",
        )
        self._refresh_history()
        # Update db info
        if self.app.bridge:
            try:
                info = self.app.bridge.get_db_info()
                total = info.get("total_records", "?")
                self.info_label.setText(
                    f"路径: {info.get('path', '')}\n"
                    f"集合: {info.get('collection', '')}  |  记录数: {total}"
                )
            except Exception:
                pass
        self.app.update_db_status()

    def _on_update_error(self, error_msg):
        self.app.status.showMessage("更新失败")
        QMessageBox.critical(self, "更新失败", error_msg)

    # ── Environment indicator ──

    def _update_env_indicator(self):
        """Update the env indicator based on MainWindow.env_info."""
        info = self.app.env_info if hasattr(self.app, "env_info") else None
        if info is None:
            self._env_indicator.setText("● R 环境检查中...")
            self._env_indicator.setStyleSheet("color: #64748B; font-size: 9pt;")
            return

        if not info.get("r_available"):
            self._env_indicator.setText("● R 未安装")
            self._env_indicator.setStyleSheet("color: #EF4444; font-size: 9pt;")
        elif info.get("error"):
            self._env_indicator.setText("● R 包不完整")
            self._env_indicator.setStyleSheet("color: #F59E0B; font-size: 9pt;")
        else:
            ver = info.get("r_version", "?")
            pkg = info.get("packages", {}).get("ctrdata", "?")
            self._env_indicator.setText(f"● {ver} + ctrdata {pkg}")
            self._env_indicator.setStyleSheet("color: #10B981; font-size: 9pt;")

    def _recheck_env(self):
        """Trigger R environment re-check."""
        self._env_indicator.setText("● 正在检测...")
        self._env_indicator.setStyleSheet("color: #64748B; font-size: 9pt;")
        if hasattr(self.app, "_check_r_environment"):
            self.app._check_r_environment()
