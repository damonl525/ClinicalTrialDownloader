#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临床试验数据下载器 v0.3 — GUI 主应用

3 个标签页，对应 ctrdata 的 3 步工作流：
  1. 数据库连接  →  nodbi::src_sqlite()
  2. 搜索与下载  →  ctrGetQueryUrl() + ctrLoadQueryIntoDb()
  3. 提取与导出  →  dbGetFieldsIntoDf() + f.* 概念函数

不依赖 rpy2，通过 subprocess 调用 RScript
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

from core.constants import GUI_TITLE, GUI_DEFAULT_SIZE, GUI_MIN_SIZE
from config_manager import ConfigManager
from gui.styles import apply_styles
from gui.tabs.database_tab import DatabaseTab
from gui.tabs.search_tab import SearchTab
from gui.tabs.export_tab import ExportTab


class CtrdataGUI:
    """临床试验数据下载器 — 主 GUI"""

    def __init__(self):
        # ── 主窗口 ──
        self.root = tk.Tk()
        self.root.title(GUI_TITLE)
        self.root.geometry(f"{GUI_DEFAULT_SIZE[0]}x{GUI_DEFAULT_SIZE[1]}")
        self.root.minsize(*GUI_MIN_SIZE)

        # ── 共享状态 ──
        self.bridge = None          # CtrdataBridge 实例
        self.is_downloading = False
        self.download_thread = None
        self.filtered_ids = None    # 提取后过滤的 trial ID 列表
        self.current_search_ids = None  # 本次搜索下载的 trial ID 列表
        self.config = ConfigManager()

        # ── 构建 UI ──
        apply_styles()
        self._build_ui()
        self._check_r_environment()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=8)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text=GUI_TITLE, style="Title.TLabel").grid(
            row=0, column=0, pady=(0, 8)
        )

        self.notebook = ttk.Notebook(main)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.database_tab = DatabaseTab(self.notebook, self)
        self.search_tab = SearchTab(self.notebook, self)
        self.export_tab = ExportTab(self.notebook, self)

        # Update export tab scope labels when tab is selected
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._create_status_bar(main)
        self._create_menu()

        # Restore window geometry from config
        saved_size = self.config.get("gui.window_size", list(GUI_DEFAULT_SIZE))
        if isinstance(saved_size, list) and len(saved_size) == 2:
            self.root.geometry(f"{saved_size[0]}x{saved_size[1]}")

        # Save config on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_status_bar(self, parent):
        bar = ttk.Frame(parent)
        bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bar.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status_var, relief=tk.SUNKEN).grid(
            row=0, column=0, sticky="ew"
        )

        self.r_status_var = tk.StringVar(value="正在检查 R 环境...")
        self.r_status_label = ttk.Label(
            bar, textvariable=self.r_status_var, foreground="gray"
        )
        self.r_status_label.grid(row=0, column=1, padx=(10, 0))

    def _on_tab_changed(self, event):
        """Update export tab scope labels when switching tabs"""
        try:
            if hasattr(self, 'export_tab') and hasattr(self.export_tab, '_on_scope_change'):
                self.export_tab._on_scope_change()
        except Exception:
            pass

    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="退出", command=self.root.quit)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)

    # ================================================================
    # R 环境检查（后台线程）
    # ================================================================

    def _check_r_environment(self):
        """后台检查 R + ctrdata 环境"""
        def _worker():
            from ctrdata_core import check_r_environment

            info = check_r_environment()

            if info.get("r_available") and not info.get("error"):
                # 环境就绪，创建 bridge
                try:
                    from ctrdata_core import CtrdataBridge
                    self.bridge = CtrdataBridge()
                    self.root.after(0, lambda: self.r_status_var.set(
                        f"R {info.get('r_version', '?')} + ctrdata {info.get('packages', {}).get('ctrdata', '?')} 就绪"
                    ))
                    self.root.after(0, lambda: self.r_status_label.config(foreground="green"))
                    self.root.after(0, lambda: self.status_var.set("就绪 — 请连接数据库"))
                except Exception as e:
                    self.root.after(0, lambda: self._show_r_error(str(e)))

            elif info.get("r_available"):
                self.root.after(0, lambda: self._show_r_warning(info.get("error", "")))

            else:
                self.root.after(0, lambda: self._show_r_error(info.get("error", "未找到 R")))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_r_error(self, msg: str):
        self.r_status_var.set("R 不可用")
        self.r_status_label.config(foreground="red")
        self.status_var.set(f"错误: {msg}")
        messagebox.showerror("R 环境错误", f"{msg}\n\n请确保已安装 R 和 ctrdata")

    def _show_r_warning(self, msg: str):
        self.r_status_var.set("R 包不完整")
        self.r_status_label.config(foreground="orange")
        self.status_var.set(f"警告: {msg}")
        messagebox.showwarning("R 包缺失", msg)

    # ================================================================
    # 日志
    # ================================================================

    def log(self, msg: str, level: str = "INFO"):
        """记录日志"""
        if level == "ERROR":
            self.status_var.set(f"错误: {msg}")
        elif level == "WARNING":
            self.status_var.set(f"警告: {msg}")

    # ================================================================
    # 菜单
    # ================================================================

    def _show_help(self):
        messagebox.showinfo("使用说明", """
临床试验数据下载器 — 使用说明（v0.3 更新版）

第 1 步: 数据库
  - 指定 SQLite 文件路径
  - 点击「连接数据库」
  - 查看查询历史，可点击「增量更新」

第 2 步: 搜索与下载数据
  表单搜索 (推荐):
  - 输入疾病/干预措施/搜索短语
  - 可展开高级条件设置阶段、招募状态、日期等
  - 勾选目标注册中心 (CTGOV2/EUCTR/ISRCTN/CTIS)
  - 可先点击「预览计数」查看结果数量
  - 点击「搜索并下载数据」

  粘贴 URL:
  - 在浏览器搜索注册中心，复制 URL 粘贴

  按试验 ID 查询:
  - 直接输入 NCT 编号下载单条数据

第 3 步: 提取、过滤与文档下载
  - 勾选标准化函数 (f.*)
  - 设置过滤条件（阶段/状态/日期/适应症/干预措施）
  - 点击「提取数据」
  - 为筛选后的试验下载文档
  - 导出 CSV
""")

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            f"{GUI_TITLE}\n\n"
            "基于 ctrdata R 包 (CRAN 1.26.0)\n"
            "通过 RScript 调用 R，无编码冲突\n\n"
            "核心能力:\n"
            "  • 多注册中心 (CTGOV2/EUCTR/ISRCTN/CTIS)\n"
            "  • 数据 + 文档一步下载\n"
            "  • 14 个跨注册中心标准化函数\n"
            "  • 跨注册中心去重\n",
        )

    # ================================================================
    # 配置持久化
    # ================================================================

    def _on_close(self):
        """Window close handler — save config then destroy"""
        self._save_config()
        self.root.destroy()

    def _save_config(self):
        """Save user preferences to ConfigManager"""
        # Window geometry
        try:
            geo = self.root.geometry()  # "950x720+100+200"
            size_part = geo.split("+")[0].split("x")
            if len(size_part) == 2:
                self.config.set("gui.window_size", [int(size_part[0]), int(size_part[1])])
        except Exception:
            pass

    def get_config(self, key: str, default=None):
        """Convenience accessor for tabs"""
        return self.config.get(key, default)

    def set_config(self, key: str, value):
        """Convenience setter for tabs"""
        return self.config.set(key, value)

    # ================================================================
    # 运行
    # ================================================================

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = CtrdataGUI()
    app.run()
