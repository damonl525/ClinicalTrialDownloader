#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库标签页 — 使用 nodbi 连接，查询历史带增量更新按钮
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading

from core.constants import DEFAULT_DB_NAME, DEFAULT_COLLECTION


class DatabaseTab:
    """数据库连接和管理标签页"""

    def __init__(self, notebook: ttk.Notebook, app):
        self.app = app
        self._history_data = None
        self._create(notebook)

    def _create(self, notebook: ttk.Notebook):
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=" 1. 数据库 ")

        # ── 连接设置 ──
        conn_frame = ttk.LabelFrame(tab, text="数据库连接", padding=15)
        conn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(conn_frame, text="数据库文件:").grid(row=0, column=0, sticky=tk.W, pady=5)
        saved_db = self.app.get_config("database.last_save_path", DEFAULT_DB_NAME) if hasattr(self.app, 'get_config') else DEFAULT_DB_NAME
        self.app.db_path_var = tk.StringVar(value=saved_db)
        ttk.Entry(conn_frame, textvariable=self.app.db_path_var, width=50).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(10, 5), pady=5
        )
        ttk.Button(conn_frame, text="浏览...", command=self._browse_db).grid(
            row=0, column=2, pady=5
        )

        ttk.Label(conn_frame, text="集合名称:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.app.collection_var = tk.StringVar(value=DEFAULT_COLLECTION)
        ttk.Entry(conn_frame, textvariable=self.app.collection_var, width=30).grid(
            row=1, column=1, sticky=tk.W, padx=(10, 5), pady=5
        )
        ttk.Label(conn_frame, text="(nodbi 集合，默认 ctrdata)", foreground="gray").grid(
            row=1, column=2, sticky=tk.W, pady=5
        )

        self.connect_btn = ttk.Button(
            conn_frame, text="连接数据库", command=self._connect
        )
        self.connect_btn.grid(row=2, column=0, columnspan=3, pady=15)

        # ── 状态显示 ──
        status_frame = ttk.LabelFrame(tab, text="数据库状态", padding=15)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        self.app.db_status_var = tk.StringVar(value="未连接")
        ttk.Label(status_frame, textvariable=self.app.db_status_var,
                  font=("Arial", 11, "bold")).pack(anchor=tk.W)

        self.app.db_info_var = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.app.db_info_var,
                  foreground="blue").pack(anchor=tk.W, pady=(5, 0))

        # ── 查询历史（带增量更新按钮）──
        hist_frame = ttk.LabelFrame(tab, text="查询历史", padding=10)
        hist_frame.pack(fill=tk.BOTH, expand=True)

        hist_list_frame = ttk.Frame(hist_frame)
        hist_list_frame.pack(fill=tk.BOTH, expand=True)

        # Canvas + Frame 实现可滚动的带按钮历史列表
        self.hist_canvas = tk.Canvas(hist_list_frame)
        hist_vsb = ttk.Scrollbar(hist_list_frame, orient="vertical", command=self.hist_canvas.yview)
        self.hist_inner = ttk.Frame(self.hist_canvas)

        self.hist_inner.bind(
            "<Configure>",
            lambda e: self.hist_canvas.configure(scrollregion=self.hist_canvas.bbox("all")),
        )
        self.hist_canvas.create_window((0, 0), window=self.hist_inner, anchor=tk.NW)
        self.hist_canvas.configure(yscrollcommand=hist_vsb.set)

        self.hist_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hist_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮绑定
        def _on_mousewheel(event):
            self.hist_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.hist_canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        ttk.Button(hist_frame, text="刷新历史", command=self._refresh_history).pack(
            side=tk.BOTTOM, pady=(5, 0), anchor=tk.E
        )

        conn_frame.columnconfigure(1, weight=1)

    def _browse_db(self):
        path = filedialog.askopenfilename(
            defaultextension=".sqlite",
            filetypes=[("SQLite 数据库", "*.sqlite *.db"), ("所有文件", "*.*")],
        )
        if path:
            self.app.db_path_var.set(path)

    def _connect(self):
        """连接数据库"""
        self.connect_btn.config(state=tk.DISABLED)
        self.app.db_status_var.set("正在连接...")

        try:
            db_path = self.app.db_path_var.get().strip()
            collection = self.app.collection_var.get().strip()

            if not db_path:
                messagebox.showerror("错误", "请指定数据库文件路径")
                return

            # Validate path format (no side effects)
            try:
                from validators import InputValidator
                result = InputValidator.validate_file_path(
                    db_path, must_exist=False, must_be_writable=False
                )
                if not result.is_valid:
                    messagebox.showwarning("路径无效", result.message)
                    self.connect_btn.config(state=tk.NORMAL)
                    return
            except ImportError:
                pass  # validators not available

            if not self.app.bridge:
                from ctrdata_core import CtrdataBridge
                self.app.bridge = CtrdataBridge()

            info = self.app.bridge.connect(db_path, collection)

            self.app.db_status_var.set(f"已连接: {os.path.basename(db_path)}")
            self.app.db_info_var.set(
                f"路径: {info['path']}\n"
                f"集合: {info['collection']}  |  记录数: {info.get('total_records', '?')}"
            )
            self.app.status_var.set("数据库连接成功")

            # Persist database path
            if hasattr(self.app, 'set_config'):
                self.app.set_config("database.last_save_path", db_path)

            self._refresh_history()

        except Exception as e:
            self.app.db_status_var.set("连接失败")
            self.app.db_info_var.set("")
            messagebox.showerror("连接失败", str(e))

        finally:
            self.connect_btn.config(state=tk.NORMAL)

    def _refresh_history(self):
        """刷新查询历史，每条记录带增量更新按钮"""
        if not self.app.bridge or not self.app.bridge.db_path:
            return

        try:
            history = self.app.bridge.get_query_history()
            self._history_data = history

            # 清空旧控件
            for widget in self.hist_inner.winfo_children():
                widget.destroy()

            if history.empty:
                ttk.Label(self.hist_inner, text="暂无查询历史").pack(anchor=tk.W)
            else:
                # 表头
                header = ttk.Frame(self.hist_inner)
                header.pack(fill=tk.X, pady=(0, 5))
                ttk.Label(header, text="#", width=4, font=("", 9, "bold")).pack(side=tk.LEFT)
                ttk.Label(header, text="时间", width=22, font=("", 9, "bold")).pack(side=tk.LEFT, padx=5)
                ttk.Label(header, text="注册中心", width=10, font=("", 9, "bold")).pack(side=tk.LEFT, padx=5)
                ttk.Label(header, text="记录数", width=8, font=("", 9, "bold")).pack(side=tk.LEFT, padx=5)
                ttk.Label(header, text="查询", font=("", 9, "bold")).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
                ttk.Label(header, text="操作", width=14, font=("", 9, "bold")).pack(side=tk.RIGHT, padx=5)

                ttk.Separator(self.hist_inner, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=2)

                for idx, (_, row) in enumerate(history.iterrows()):
                    row_frame = ttk.Frame(self.hist_inner)
                    row_frame.pack(fill=tk.X, pady=1)

                    ts = str(row.get("query-timestamp", "?"))[:19]
                    reg = str(row.get("query-register", "?"))
                    n = str(row.get("query-records", "?"))
                    term = str(row.get("query-term", ""))[:80]

                    ttk.Label(row_frame, text=str(idx + 1), width=4).pack(side=tk.LEFT)
                    ttk.Label(row_frame, text=ts, width=22).pack(side=tk.LEFT, padx=5)
                    ttk.Label(row_frame, text=reg, width=10).pack(side=tk.LEFT, padx=5)
                    ttk.Label(row_frame, text=n, width=8).pack(side=tk.LEFT, padx=5)
                    ttk.Label(row_frame, text=term).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

                    # 增量更新按钮
                    query_idx = idx + 1  # R 用 1-based 索引
                    update_btn = ttk.Button(
                        row_frame,
                        text="增量更新",
                        command=lambda qi=query_idx: self._incremental_update(qi),
                        width=14,
                    )
                    update_btn.pack(side=tk.RIGHT, padx=5)

        except Exception as e:
            for widget in self.hist_inner.winfo_children():
                widget.destroy()
            ttk.Label(self.hist_inner, text=f"获取历史失败: {e}").pack(anchor=tk.W)

    def _incremental_update(self, query_index: int):
        """增量更新指定查询"""
        if not self.app.bridge or not self.app.bridge.db_path:
            messagebox.showerror("错误", "请先连接数据库")
            return

        if not messagebox.askyesno(
            "确认更新",
            f"增量更新查询 #{query_index}？\n\n"
            "仅下载上次查询后有更新的试验数据。"
        ):
            return

        self.app.status_var.set(f"正在更新查询 #{query_index}...")

        def _worker():
            try:
                result = self.app.bridge.update_last_query(query_index=query_index)
                n = result.get("n", 0)
                s = result.get("success", 0)
                f = result.get("failed", 0)

                self.app.root.after(0, lambda: self._on_update_complete(query_index, n, s, f))
            except Exception as e:
                err_msg = str(e)
                self.app.root.after(0, lambda msg=err_msg: self._on_update_error(msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_complete(self, query_index, n, success, failed):
        self.app.status_var.set(f"查询 #{query_index} 更新完成: {n} 条记录")
        messagebox.showinfo(
            "更新完成",
            f"查询 #{query_index} 已更新\n"
            f"更新记录: {n}\n"
            f"成功: {success}\n"
            f"失败: {failed}",
        )
        # 刷新历史和数据库信息
        self._refresh_history()
        if self.app.bridge:
            info = self.app.bridge.get_db_info()
            if info.get("total_records") is not None:
                self.app.db_info_var.set(
                    f"路径: {info['path']}\n"
                    f"集合: {info['collection']}  |  记录数: {info.get('total_records', '?')}"
                )

    def _on_update_error(self, error_msg):
        self.app.status_var.set("更新失败")
        messagebox.showerror("更新失败", error_msg)
