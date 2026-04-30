#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索与下载标签页 — 三种模式：表单搜索、粘贴 URL、按试验 ID 查询

工作流:
  模式 A: 表单搜索 → ctrGenerateQueries() → 多注册中心 URL → load_into_db()
  模式 B: 粘贴 URL → ctrGetQueryUrl() → load_into_db()
  模式 C: 试验 ID → load_by_trial_id()
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading

from core.constants import (
    SEARCH_PHASES,
    SEARCH_RECRUITMENT,
    SEARCH_POPULATIONS,
    SUPPORTED_REGISTERS,
    LOG_MAX_LINES,
)


class SearchTab:
    """搜索与下载标签页"""

    def __init__(self, notebook: ttk.Notebook, app):
        self.app = app
        self._generated_urls = {}  # 缓存 generate_queries 生成的 URL
        self._create(notebook)

    def _create(self, notebook: ttk.Notebook):
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=" 2. 搜索与下载 ")

        # ── 搜索模式选择 ──
        mode_frame = ttk.LabelFrame(tab, text="搜索模式", padding=8)
        mode_frame.pack(fill=tk.X, pady=(0, 5))

        self.app.search_mode_var = tk.StringVar(value="form")
        for text, val in [
            ("表单搜索 (ctrGenerateQueries)", "form"),
            ("粘贴 URL", "url"),
            ("按试验 ID 查询", "id"),
        ]:
            ttk.Radiobutton(
                mode_frame, text=text, variable=self.app.search_mode_var,
                value=val, command=self._toggle_mode,
            ).pack(side=tk.LEFT, padx=(0, 20))

        # ── 模式面板容器 ──
        self.panels_frame = ttk.Frame(tab)
        self.panels_frame.pack(fill=tk.X, pady=(0, 5))

        self._create_form_panel()
        self._create_url_panel()
        self._create_id_panel()

        # ── 操作按钮 ──
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, pady=5)

        self.preview_btn = ttk.Button(
            btn_frame, text="预览计数", command=self._preview_count,
        )
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.app.download_btn = ttk.Button(
            btn_frame, text="搜索并下载数据", command=self._start_download,
        )
        self.app.download_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.browser_btn = ttk.Button(
            btn_frame, text="在浏览器中查看", command=self._open_in_browser,
        )
        self.browser_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.copy_urls_btn = ttk.Button(
            btn_frame, text="复制所有URL", command=self._copy_all_urls,
        )
        self.copy_urls_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.update_btn = ttk.Button(
            btn_frame, text="更新上次查询", command=self._update_last_query,
        )
        self.update_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.app.cancel_btn = ttk.Button(
            btn_frame, text="取消", command=self._cancel, state=tk.DISABLED,
        )
        self.app.cancel_btn.pack(side=tk.LEFT)

        self.app.download_status_var = tk.StringVar(value="")
        ttk.Label(btn_frame, textvariable=self.app.download_status_var,
                  foreground="blue").pack(side=tk.LEFT, padx=20)

        # ── 进度条 ──
        self.app.download_progress = ttk.Progressbar(
            tab, mode="indeterminate",
            style="pointed.Horizontal.TProgressbar",
        )
        self.app.download_progress.pack(fill=tk.X, pady=(0, 5))

        # ── 日志区 ──
        log_frame = ttk.LabelFrame(tab, text="下载日志（ctrdata 输出）", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.app.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.app.log_text.pack(fill=tk.BOTH, expand=True)

        self._toggle_mode()

    # ================================================================
    # 面板 A: 表单搜索
    # ================================================================

    def _create_form_panel(self):
        self.form_panel = ttk.LabelFrame(
            self.panels_frame, text="表单搜索 (ctrGenerateQueries)", padding=10
        )

        # 疾病/状态
        ttk.Label(self.form_panel, text="疾病/状态:").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Label(
            self.form_panel, text="会被医学词典扩展", foreground="gray"
        ).grid(row=0, column=2, sticky=tk.W, padx=(5, 0), pady=3)
        self.search_condition_var = tk.StringVar()
        ttk.Entry(self.form_panel, textvariable=self.search_condition_var, width=45).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0), pady=3
        )

        # 干预措施名称
        ttk.Label(self.form_panel, text="干预措施名称:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.search_intervention_var = tk.StringVar()
        ttk.Entry(self.form_panel, textvariable=self.search_intervention_var, width=45).grid(
            row=1, column=1, sticky=(tk.W, tk.E), padx=(5, 0), pady=3
        )
        intrv_right = ttk.Frame(self.form_panel)
        intrv_right.grid(row=1, column=2, sticky=tk.W, padx=(5, 0), pady=3)
        ttk.Button(
            intrv_right, text="同义词", width=6,
            command=self._find_synonyms,
        ).pack(side=tk.LEFT)
        ttk.Label(
            intrv_right, text="如: aspirin", foreground="gray"
        ).pack(side=tk.LEFT, padx=(5, 0))

        # 搜索短语
        ttk.Label(self.form_panel, text="搜索短语:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.search_phrase_var = tk.StringVar()
        ttk.Entry(self.form_panel, textvariable=self.search_phrase_var, width=45).grid(
            row=2, column=1, sticky=(tk.W, tk.E), padx=(5, 0), pady=3
        )
        ttk.Label(self.form_panel, text="精确搜索，支持 AND / OR", foreground="gray").grid(
            row=2, column=2, sticky=tk.W, padx=(10, 0), pady=3
        )

        # 高级选项折叠
        adv_expanded = (
            self.app.get_config("gui.advanced_expanded", True)
            if hasattr(self.app, 'get_config') else True
        )
        self._adv_visible = adv_expanded
        self._adv_toggle_btn = ttk.Button(
            self.form_panel,
            text=("▾ 高级条件（可选）" if adv_expanded else "▸ 高级条件（可选）"),
            command=self._toggle_advanced,
        )
        self._adv_toggle_btn.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))

        self._adv_frame = ttk.Frame(self.form_panel)
        if adv_expanded:
            self._adv_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))

        row = 0
        # 阶段
        ttk.Label(self._adv_frame, text="阶段:").grid(row=row, column=0, sticky=tk.W, pady=3)
        self.search_phase_var = tk.StringVar(value="全部")
        ttk.Combobox(
            self._adv_frame, textvariable=self.search_phase_var,
            values=list(SEARCH_PHASES.keys()), state="readonly", width=15,
        ).grid(row=row, column=1, sticky=tk.W, padx=(5, 20), pady=3)

        # 招募状态
        ttk.Label(self._adv_frame, text="招募状态:").grid(row=row, column=2, sticky=tk.W, pady=3)
        self.search_recruitment_var = tk.StringVar(value="全部")
        ttk.Combobox(
            self._adv_frame, textvariable=self.search_recruitment_var,
            values=list(SEARCH_RECRUITMENT.keys()), state="readonly", width=12,
        ).grid(row=row, column=3, sticky=tk.W, padx=(5, 0), pady=3)
        ttk.Label(
            self._adv_frame, text="其他=含提前终止", foreground="gray"
        ).grid(row=row, column=4, sticky=tk.W, padx=(10, 0), pady=3)

        row += 1
        # 开始日期
        ttk.Label(self._adv_frame, text="开始日期从:").grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Label(
            self._adv_frame, text="EUCTR为注册日期", foreground="gray"
        ).grid(row=row, column=4, sticky=tk.W, padx=(5, 0), pady=3)
        self.start_after_var = tk.StringVar()
        ttk.Entry(self._adv_frame, textvariable=self.start_after_var, width=12).grid(
            row=row, column=1, sticky=tk.W, padx=(5, 20), pady=3
        )
        ttk.Label(self._adv_frame, text="到:").grid(row=row, column=2, sticky=tk.W, pady=3)
        self.start_before_var = tk.StringVar()
        ttk.Entry(self._adv_frame, textvariable=self.start_before_var, width=12).grid(
            row=row, column=3, sticky=tk.W, padx=(5, 0), pady=3
        )

        row += 1
        # 完成日期
        ttk.Label(self._adv_frame, text="完成日期从:").grid(row=row, column=0, sticky=tk.W, pady=3)
        self.completed_after_var = tk.StringVar()
        ttk.Entry(self._adv_frame, textvariable=self.completed_after_var, width=12).grid(
            row=row, column=1, sticky=tk.W, padx=(5, 20), pady=3
        )
        ttk.Label(self._adv_frame, text="到:").grid(row=row, column=2, sticky=tk.W, pady=3)
        self.completed_before_var = tk.StringVar()
        ttk.Entry(self._adv_frame, textvariable=self.completed_before_var, width=12).grid(
            row=row, column=3, sticky=tk.W, padx=(5, 0), pady=3
        )
        ttk.Label(self._adv_frame, text="YYYY-MM-DD (EUCTR不支持)", foreground="gray").grid(
            row=row, column=4, sticky=tk.W, padx=(10, 0), pady=3
        )

        row += 1
        # 目标人群
        ttk.Label(self._adv_frame, text="目标人群:").grid(row=row, column=0, sticky=tk.W, pady=3)
        self.population_var = tk.StringVar(value="全部")
        ttk.Combobox(
            self._adv_frame, textvariable=self.population_var,
            values=list(SEARCH_POPULATIONS.keys()), state="readonly", width=18,
        ).grid(row=row, column=1, sticky=tk.W, padx=(5, 20), pady=3)

        # 国家/地区
        ttk.Label(self._adv_frame, text="国家/地区:").grid(row=row, column=2, sticky=tk.W, pady=3)
        self.countries_var = tk.StringVar()
        ttk.Entry(self._adv_frame, textvariable=self.countries_var, width=15).grid(
            row=row, column=3, sticky=tk.W, padx=(5, 0), pady=3
        )
        ttk.Label(self._adv_frame, text="如: US,CN,DE", foreground="gray").grid(
            row=row, column=4, sticky=tk.W, padx=(5, 0), pady=3
        )

        row += 1
        # 复选框
        self.only_med_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self._adv_frame, text="仅药物干预试验",
            variable=self.only_med_var,
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=3)

        self.only_results_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self._adv_frame, text="仅有结果的试验",
            variable=self.only_results_var,
        ).grid(row=row, column=2, columnspan=2, sticky=tk.W, pady=3)

        row += 1
        self.protocol_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self._adv_frame, text="仅含Protocol文档的试验",
            variable=self.protocol_only_var,
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=3)
        ttk.Label(
            self._adv_frame, text="下载后自动扫描文档可用性",
            foreground="gray",
        ).grid(row=row, column=2, columnspan=2, sticky=tk.W, pady=3)

        # 注册中心选择
        row += 1
        ttk.Label(self._adv_frame, text="注册中心:").grid(row=row, column=0, sticky=tk.W, pady=(8, 3))
        self.register_vars = {}
        saved_regs = (
            self.app.get_config("query.default_registers", ["CTGOV2"])
            if hasattr(self.app, 'get_config') else ["CTGOV2"]
        )
        reg_col = 1
        for reg_key in SUPPORTED_REGISTERS:
            default = reg_key in saved_regs
            var = tk.BooleanVar(value=default)
            self.register_vars[reg_key] = var
            ttk.Checkbutton(
                self._adv_frame, text=f"{reg_key}",
                variable=var,
            ).grid(row=row, column=reg_col, sticky=tk.W, padx=(5, 0), pady=3)
            reg_col += 1

        self.form_panel.columnconfigure(1, weight=1)

    # ================================================================
    # 面板 B: 粘贴 URL
    # ================================================================

    def _create_url_panel(self):
        self.url_panel = ttk.LabelFrame(self.panels_frame, text="粘贴 URL", padding=10)

        ttk.Label(self.url_panel, text="粘贴注册中心搜索页 URL:").pack(anchor=tk.W)
        ttk.Label(
            self.url_panel,
            text="例: https://www.clinicaltrials.gov/search?cond=cancer",
            foreground="gray",
        ).pack(anchor=tk.W)
        self.app.url_var = tk.StringVar()
        ttk.Entry(self.url_panel, textvariable=self.app.url_var, width=80).pack(
            fill=tk.X, pady=5
        )

    # ================================================================
    # 面板 C: 按 ID 查询
    # ================================================================

    def _create_id_panel(self):
        self.id_panel = ttk.LabelFrame(self.panels_frame, text="按试验 ID 查询", padding=10)

        ttk.Label(self.id_panel, text="试验 ID:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.trial_id_var = tk.StringVar()
        ttk.Entry(self.id_panel, textvariable=self.trial_id_var, width=40).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0), pady=3
        )
        ttk.Label(
            self.id_panel,
            text="支持: NCTxxxxxx / 20xx-xxxxxx-xx / ISRCTNxxxxx / 20xx-xxx",
            foreground="gray",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(3, 0))

        self.id_panel.columnconfigure(1, weight=1)

    # ================================================================
    # 模式切换
    # ================================================================

    def _toggle_mode(self):
        mode = self.app.search_mode_var.get()
        self.form_panel.pack_forget()
        self.url_panel.pack_forget()
        self.id_panel.pack_forget()

        if mode == "form":
            self.form_panel.pack(fill=tk.X)
            self.preview_btn.config(state=tk.NORMAL)
            self.browser_btn.config(state=tk.NORMAL)
        elif mode == "url":
            self.url_panel.pack(fill=tk.X)
            self.preview_btn.config(state=tk.DISABLED)
            self.browser_btn.config(state=tk.DISABLED)
        elif mode == "id":
            self.id_panel.pack(fill=tk.X)
            self.preview_btn.config(state=tk.DISABLED)
            self.browser_btn.config(state=tk.DISABLED)

    def _toggle_advanced(self):
        self._adv_visible = not self._adv_visible
        if self._adv_visible:
            self._adv_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))
            self._adv_toggle_btn.config(text="▾ 高级条件（可选）")
        else:
            self._adv_frame.grid_forget()
            self._adv_toggle_btn.config(text="▸ 高级条件（可选）")
        if hasattr(self.app, 'set_config'):
            self.app.set_config("gui.advanced_expanded", self._adv_visible)

    # ================================================================
    # 收集表单参数
    # ================================================================

    def _collect_form_params(self) -> dict:
        """收集表单参数，返回 generate_queries() 的参数字典"""
        params = {}
        params["condition"] = self.search_condition_var.get().strip()
        params["intervention"] = self.search_intervention_var.get().strip()
        params["search_phrase"] = self.search_phrase_var.get().strip()
        params["phase"] = SEARCH_PHASES.get(self.search_phase_var.get(), "")
        params["recruitment"] = SEARCH_RECRUITMENT.get(self.search_recruitment_var.get(), "")
        params["start_after"] = self.start_after_var.get().strip()
        params["start_before"] = self.start_before_var.get().strip()
        params["completed_after"] = self.completed_after_var.get().strip()
        params["completed_before"] = self.completed_before_var.get().strip()
        params["population"] = SEARCH_POPULATIONS.get(self.population_var.get(), "")
        params["countries"] = self.countries_var.get().strip()
        params["only_med_interv_trials"] = self.only_med_var.get()
        params["only_with_results"] = self.only_results_var.get()
        return params

    def _get_selected_registers(self) -> list:
        """获取选中的注册中心列表"""
        return [k for k, v in self.register_vars.items() if v.get()]

    def _filter_urls_by_registers(self, urls: dict, registers: list) -> dict:
        """按选中注册中心过滤生成的 URL（精确匹配，排除 CTGOV2expert）"""
        filtered = {}
        for key, url in urls.items():
            if key in registers:
                filtered[key] = url
        return filtered

    # ================================================================
    # 预览计数
    # ================================================================

    def _preview_count(self):
        """预览搜索结果数量"""
        if not self.app.bridge or not self.app.bridge.db_path:
            messagebox.showerror("错误", "请先连接数据库（第 1 步）")
            return

        params = self._collect_form_params()
        if not params["condition"] and not params["intervention"] and not params["search_phrase"]:
            messagebox.showwarning("提示", "请至少输入一个搜索条件")
            return

        selected_regs = self._get_selected_registers()
        if not selected_regs:
            messagebox.showwarning("提示", "请至少选择一个注册中心")
            return

        self.app.download_status_var.set("正在预览计数...")
        self.app.root.update_idletasks()

        try:
            urls = self.app.bridge.generate_queries(**params)
            filtered_urls = self._filter_urls_by_registers(urls, selected_regs)

            if not filtered_urls:
                messagebox.showinfo("预览", "所选注册中心无匹配的 URL")
                return

            self._generated_urls = filtered_urls

            counts = self.app.bridge.count_trials(filtered_urls)

            lines = ["搜索结果预览\n" + "=" * 40]
            total = 0
            for reg, count in counts.items():
                lines.append(f"  {reg}: {count:,} 条")
                total += count
            lines.append("-" * 40)
            lines.append(f"  合计: {total:,} 条")
            lines.append(f"\n生成 URL 数: {len(filtered_urls)}")

            messagebox.showinfo("预览计数", "\n".join(lines))
            self.app.download_status_var.set(f"预览: {total:,} 条，跨 {len(counts)} 个注册中心")

        except Exception as e:
            messagebox.showerror("预览失败", str(e))
            self.app.download_status_var.set("")

    # ================================================================
    # 在浏览器中查看
    # ================================================================

    def _open_in_browser(self):
        """在浏览器中打开搜索结果"""
        if not self.app.bridge:
            messagebox.showerror("错误", "R 环境未就绪")
            return

        mode = self.app.search_mode_var.get()
        if mode != "form":
            messagebox.showinfo("提示", "浏览器查看仅在表单搜索模式下可用")
            return

        try:
            if self._generated_urls:
                for reg, url in self._generated_urls.items():
                    try:
                        self.app.bridge.open_in_browser(url=url)
                    except Exception:
                        pass
                return

            params = self._collect_form_params()
            if not params["condition"] and not params["intervention"] and not params["search_phrase"]:
                messagebox.showwarning("提示", "请先输入搜索条件")
                return

            urls = self.app.bridge.generate_queries(**params)
            selected_regs = self._get_selected_registers()
            filtered_urls = self._filter_urls_by_registers(urls, selected_regs)

            for reg, url in filtered_urls.items():
                try:
                    self.app.bridge.open_in_browser(url=url)
                except Exception:
                    pass

        except Exception as e:
            messagebox.showerror("错误", str(e))

    # ================================================================
    # 复制所有 URL
    # ================================================================

    def _copy_all_urls(self):
        """复制所有生成的搜索 URL 到剪贴板"""
        mode = self.app.search_mode_var.get()
        if mode == "form":
            # Generate URLs if not cached
            if not self._generated_urls:
                params = self._collect_form_params()
                if not params["condition"] and not params["intervention"] and not params["search_phrase"]:
                    messagebox.showwarning("提示", "请先输入搜索条件")
                    return
                try:
                    urls = self.app.bridge.generate_queries(**params)
                    selected_regs = self._get_selected_registers()
                    self._generated_urls = self._filter_urls_by_registers(urls, selected_regs)
                except Exception as e:
                    messagebox.showerror("错误", f"生成 URL 失败: {e}")
                    return

            if not self._generated_urls:
                messagebox.showinfo("提示", "没有可复制的 URL")
                return

            lines = []
            for reg, url in self._generated_urls.items():
                lines.append(f"{reg}: {url}")
            text = "\n".join(lines)

        elif mode == "url":
            url = self.app.url_var.get().strip()
            if not url:
                messagebox.showwarning("提示", "请先粘贴 URL")
                return
            text = url

        elif mode == "id":
            tid = self.trial_id_var.get().strip()
            if not tid:
                messagebox.showwarning("提示", "请先输入试验 ID")
                return
            text = tid
        else:
            return

        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)
        self.app.download_status_var.set(f"已复制 {len(text)} 字符到剪贴板")

    # ================================================================
    # 更新上次查询
    # ================================================================

    def _update_last_query(self):
        """增量更新上次查询"""
        if not self.app.bridge or not self.app.bridge.db_path:
            messagebox.showerror("错误", "请先连接数据库")
            return

        self.app.download_status_var.set("正在更新上次查询...")

        def _worker():
            try:
                def on_line(line):
                    if line and not line.startswith("{"):
                        self._log(f"  {line}")

                result = self.app.bridge.update_last_query(callback=on_line)
                self.app.root.after(0, lambda: self._on_update_complete(result))
            except Exception as e:
                err_msg = str(e)
                self.app.root.after(0, lambda msg=err_msg: self._on_error(msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_complete(self, result):
        n = result.get("n", 0)
        s_ids = result.get("success", [])
        f_ids = result.get("failed", [])
        if not isinstance(s_ids, list):
            s_ids = [s_ids] if s_ids else []
        if not isinstance(f_ids, list):
            f_ids = [f_ids] if f_ids else []
        self.app.download_status_var.set(f"更新完成: {n} 条更新, 成功 {len(s_ids)}, 失败 {len(f_ids)}")
        self.app.status_var.set(f"查询更新完成: {n} 条记录")
        messagebox.showinfo("更新完成", f"更新了 {n} 条记录\n成功: {len(s_ids)}\n失败: {len(f_ids)}")

    # ================================================================
    # 同义词查找
    # ================================================================

    def _find_synonyms(self):
        """查找干预措施的同义词"""
        intervention = self.search_intervention_var.get().strip()
        if not intervention:
            messagebox.showinfo("提示", "请先输入干预措施名称")
            return

        if not self.app.bridge:
            messagebox.showerror("错误", "请先连接数据库")
            return

        self.app.status_var.set(f"正在查找 {intervention} 的同义词...")

        def _worker():
            try:
                synonyms = self.app.bridge.find_synonyms(intervention)
                self.app.root.after(0, lambda: self._show_synonyms(intervention, synonyms))
            except Exception as e:
                err_msg = str(e)
                self.app.root.after(0, lambda msg=err_msg: messagebox.showerror("查询失败", msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_synonyms(self, intervention, synonyms):
        """显示同义词弹窗"""
        if not synonyms:
            messagebox.showinfo("同义词", f"未找到 \"{intervention}\" 的同义词")
            self.app.status_var.set("就绪")
            return

        # Create popup with synonym list
        popup = tk.Toplevel(self.app.root)
        popup.title(f"同义词: {intervention}")
        popup.geometry("450x350")
        popup.transient(self.app.root)
        popup.grab_set()

        ttk.Label(popup, text=f"\"{intervention}\" 的同义词:", font=("Arial", 11, "bold")).pack(
            anchor=tk.W, padx=10, pady=(10, 5)
        )

        listbox = tk.Listbox(popup, selectmode=tk.EXTENDED, height=12)
        for syn in synonyms:
            listbox.insert(tk.END, syn)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        def _append_selected():
            selected = [listbox.get(i) for i in listbox.curselection()]
            if selected:
                current = self.search_intervention_var.get().strip()
                if current:
                    new_val = current + " OR " + " OR ".join(selected)
                else:
                    new_val = " OR ".join(selected)
                self.search_intervention_var.set(new_val)
                self._log(f"已追加 {len(selected)} 个同义词到干预措施")
            popup.destroy()

        btn_frame = ttk.Frame(popup)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(btn_frame, text="追加到搜索条件", command=_append_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="复制到剪贴板", command=lambda: (
            self.app.root.clipboard_clear(),
            self.app.root.clipboard_append("\n".join(synonyms)),
            self._log("已复制同义词列表到剪贴板"),
        )).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="关闭", command=popup.destroy).pack(side=tk.RIGHT)

        self.app.status_var.set(f"找到 {len(synonyms)} 个同义词")

    # ================================================================
    # 日志
    # ================================================================

    def _log(self, msg: str):
        """线程安全地向日志区追加消息"""
        def _append():
            self.app.log_text.config(state=tk.NORMAL)
            self.app.log_text.insert(tk.END, msg + "\n")
            self.app.log_text.see(tk.END)
            line_count = int(self.app.log_text.index("end-1c").split(".")[0])
            if line_count > LOG_MAX_LINES:
                self.app.log_text.delete("1.0", f"{line_count - LOG_MAX_LINES}.0")
            self.app.log_text.config(state=tk.DISABLED)
        self.app.root.after(0, _append)

    # ================================================================
    # 下载流程
    # ================================================================

    def _start_download(self):
        """根据当前模式启动下载"""
        if not self.app.bridge or not self.app.bridge.db_path:
            messagebox.showerror("错误", "请先连接数据库（第 1 步）")
            return

        mode = self.app.search_mode_var.get()

        # Reset protocol filter flag
        self.app._protocol_filtered = False

        # 清空日志
        self.app.log_text.config(state=tk.NORMAL)
        self.app.log_text.delete("1.0", tk.END)
        self.app.log_text.config(state=tk.DISABLED)

        if mode == "form":
            self._start_form_download()
        elif mode == "url":
            self._start_url_download()
        elif mode == "id":
            self._start_id_download()

    def _start_form_download(self):
        """表单搜索 → generate_queries → 逐个注册中心下载"""
        params = self._collect_form_params()
        if not params["condition"] and not params["intervention"] and not params["search_phrase"]:
            messagebox.showwarning("提示", "请至少输入一个搜索条件")
            return

        # Validate date fields
        import re as _re
        date_fields = [
            ("开始日期从", params["start_after"]),
            ("开始日期到", params["start_before"]),
            ("完成日期从", params["completed_after"]),
            ("完成日期到", params["completed_before"]),
        ]
        for label, val in date_fields:
            if val and not _re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                messagebox.showwarning("日期格式错误", f"{label}: 请使用 YYYY-MM-DD 格式")
                return

        selected_regs = self._get_selected_registers()
        if not selected_regs:
            messagebox.showwarning("提示", "请至少选择一个注册中心")
            return

        self._set_downloading(True)
        self._log("正在通过 ctrGenerateQueries() 生成查询...")

        # Persist register selection
        if hasattr(self.app, 'set_config'):
            selected_regs = [k for k, v in self.register_vars.items() if v.get()]
            self.app.set_config("query.default_registers", selected_regs)

        # Read protocol filter state before thread (BooleanVar is not thread-safe)
        protocol_filter_enabled = self.protocol_only_var.get()

        def _worker():
            try:
                urls = self.app.bridge.generate_queries(**params)
                filtered_urls = self._filter_urls_by_registers(urls, selected_regs)
                self._generated_urls = filtered_urls

                self._log(f"生成了 {len(filtered_urls)} 个 URL:")
                for reg, url in filtered_urls.items():
                    self._log(f"  {reg}: {url[:100]}...")

                if not filtered_urls:
                    self.app.root.after(0, lambda: self._on_error("所选注册中心未生成 URL"))
                    return

                self._log("─" * 50)

                # Per-register sequential download (skip_parse=True for generated URLs)
                total_n = 0
                all_success_ids = []
                all_failed_ids = []
                reg_list = list(filtered_urls.items())

                for i, (reg, url) in enumerate(reg_list):
                    if not self.app.is_downloading:
                        self._log("用户已取消，停止下载")
                        break

                    self._log(f"[{i + 1}/{len(reg_list)}] 正在下载 {reg}...")

                    try:
                        def on_line(line):
                            if line and not line.startswith("{"):
                                self._log(f"  {line}")

                        result = self.app.bridge.load_into_db(
                            url=url,
                            callback=on_line,
                            skip_parse=True,  # Skip ctrGetQueryUrl for generated URLs
                        )
                        n = result.get("n", 0)
                        s_ids = result.get("success", [])
                        f_ids = result.get("failed", [])
                        if not isinstance(s_ids, list):
                            s_ids = [s_ids] if s_ids else []
                        if not isinstance(f_ids, list):
                            f_ids = [f_ids] if f_ids else []
                        total_n += n
                        all_success_ids.extend(s_ids)
                        all_failed_ids.extend(f_ids)
                        self._log(f"  {reg}: {n} 条记录 (成功 {len(s_ids)}, 失败 {len(f_ids)})")

                    except Exception as e:
                        self._log(f"  {reg}: 下载失败 — {e}")
                        all_failed_ids.append(f"{reg}: {e}")

                # Save aggregated search IDs to shared state
                self.app.current_search_ids = all_success_ids if all_success_ids else None

                # Protocol document availability scan
                if protocol_filter_enabled and all_success_ids and filtered_urls:
                    self._log("─" * 50)
                    self._log("正在扫描 Protocol 文档可用性...")

                    def on_scan_msg(msg):
                        self._log(f"  {msg}")

                    try:
                        protocol_ids = self.app.bridge.scan_document_availability(
                            urls=filtered_urls,
                            doc_pattern="prot",
                            callback=on_scan_msg,
                        )
                        before_count = len(all_success_ids)
                        filtered_ids = [tid for tid in all_success_ids if tid in protocol_ids]
                        removed = before_count - len(filtered_ids)
                        all_success_ids = filtered_ids
                        self.app.current_search_ids = filtered_ids if filtered_ids else None
                        self.app._protocol_filtered = True
                        self._log(f"  Protocol 过滤: {before_count} → {len(filtered_ids)} 条 (排除 {removed} 条)")
                        if not filtered_ids:
                            self._log("  注意: 没有试验包含 Protocol 文档")
                    except Exception as e:
                        self._log(f"  Protocol 扫描失败，跳过过滤: {e}")

                # Get total DB count for info
                try:
                    db_info = self.app.bridge.get_db_info()
                    db_total = db_info.get("total_records", "?")
                except Exception:
                    db_total = "?"

                self._log("─" * 50)
                self._log("数据下载完成!")
                self._log(f"  本次搜索共下载 {len(all_success_ids)} 条试验")
                self._log(f"  数据库总计 {db_total} 条记录")
                if all_success_ids:
                    self._log(f"  切换到「提取与导出」时，默认仅提取本次搜索的 {len(all_success_ids)} 条记录")
                else:
                    self._log("  注意: 本次搜索未下载到任何试验数据")

                agg_result = {
                    "n": total_n,
                    "success": all_success_ids,
                    "failed": all_failed_ids,
                }
                self.app.root.after(0, lambda: self._on_complete(agg_result))

            except Exception as e:
                err_msg = str(e)
                self._log(f"\n错误: {err_msg}")
                self.app.root.after(0, lambda msg=err_msg: self._on_error(msg))

        self.app.download_thread = threading.Thread(target=_worker, daemon=True)
        self.app.download_thread.start()

    def _start_url_download(self):
        """粘贴 URL 模式 → parse_query_url → load_into_db"""
        url = self.app.url_var.get().strip()
        if not url:
            messagebox.showerror("错误", "请粘贴搜索 URL")
            return

        # URL format validation
        try:
            from validators import InputValidator
            result = InputValidator.validate_url(url)
            if not result.is_valid:
                messagebox.showwarning("URL 格式错误", result.message)
                return
        except ImportError:
            pass  # validators not available, proceed without validation

        self._set_downloading(True)
        self._log("开始 URL 下载...")
        self._log(f"URL: {url[:120]}")

        def _worker():
            try:
                self._log("[1/2] 解析搜索 URL...")
                query_info = self.app.bridge.parse_query_url(url)
                self._log(f"  注册中心: {query_info.get('register', '?')}")
                self._log(f"  查询: {query_info.get('queryterm', '?')[:100]}")

                self._log("[2/2] 正在下载数据...")

                def on_line(line):
                    if line and not line.startswith("PROGRESS") and not line.startswith("RESULT"):
                        self._log(f"  {line}")

                result = self.app.bridge.load_into_db(url=url, callback=on_line)

                # Save search IDs
                s_ids = result.get("success", [])
                if not isinstance(s_ids, list):
                    s_ids = [s_ids] if s_ids else []
                self.app.current_search_ids = s_ids if s_ids else None

                self._log("─" * 50)
                self._log("数据下载完成!")
                self._log(f"  总记录数: {result.get('n', 0)}")
                self._log(f"  成功: {len(s_ids)} 条")
                f_ids = result.get("failed", [])
                if not isinstance(f_ids, list):
                    f_ids = [f_ids] if f_ids else []
                self._log(f"  失败: {len(f_ids)} 条")

                self.app.root.after(0, lambda: self._on_complete(result))

            except Exception as e:
                err_msg = str(e)
                self._log(f"\n错误: {err_msg}")
                self.app.root.after(0, lambda msg=err_msg: self._on_error(msg))

        self.app.download_thread = threading.Thread(target=_worker, daemon=True)
        self.app.download_thread.start()

    def _start_id_download(self):
        """按试验 ID 模式 → load_by_trial_id"""
        trial_id = self.trial_id_var.get().strip()
        if not trial_id:
            messagebox.showerror("错误", "请输入试验 ID")
            return

        self._set_downloading(True)
        self._log(f"正在下载试验: {trial_id}...")

        def _worker():
            try:
                def on_line(line):
                    if line and not line.startswith("{"):
                        self._log(f"  {line}")

                result = self.app.bridge.load_by_trial_id(trial_id, callback=on_line)

                # Save search IDs
                s_ids = result.get("success", [])
                if not isinstance(s_ids, list):
                    s_ids = [s_ids] if s_ids else []
                self.app.current_search_ids = s_ids if s_ids else None

                self._log("─" * 50)
                self._log(f"试验 {trial_id} 下载完成!")
                self._log(f"  记录数: {result.get('n', 0)}")
                self._log(f"  成功: {len(s_ids)} 条")

                self.app.root.after(0, lambda: self._on_complete(result))

            except Exception as e:
                err_msg = str(e)
                self._log(f"\n错误: {err_msg}")
                self.app.root.after(0, lambda msg=err_msg: self._on_error(msg))

        self.app.download_thread = threading.Thread(target=_worker, daemon=True)
        self.app.download_thread.start()

    # ================================================================
    # UI 状态管理
    # ================================================================

    def _set_downloading(self, downloading: bool):
        """设置下载进行中的 UI 状态"""
        self.app.is_downloading = downloading
        state = tk.DISABLED if downloading else tk.NORMAL
        self.app.download_btn.config(state=state)
        self.app.cancel_btn.config(state=tk.NORMAL if downloading else tk.DISABLED)
        self.preview_btn.config(state=state)
        self.browser_btn.config(state=state)
        self.update_btn.config(state=state)

        if downloading:
            self.app.download_status_var.set("正在下载...")
            self.app.download_progress.config(mode="indeterminate")
            self.app.download_progress.start(15)
            self.app.filtered_ids = None
            self.app.current_search_ids = None  # Clear previous search IDs
        else:
            self.app.download_progress.stop()
            self.app.download_progress.config(mode="determinate", value=0)

    def _on_complete(self, result):
        self._set_downloading(False)
        n = result.get("n", 0)
        s_ids = result.get("success", [])
        f_ids = result.get("failed", [])
        if not isinstance(s_ids, list):
            s_ids = [s_ids] if s_ids else []
        if not isinstance(f_ids, list):
            f_ids = [f_ids] if f_ids else []
        s_count = len(s_ids)
        f_count = len(f_ids)

        self.app.download_status_var.set(f"完成: {n} 条记录 (成功 {s_count})")
        self.app.status_var.set(f"数据下载完成: {n} 条记录")

        msg = (
            f"成功下载 {s_count} 条试验数据\n"
            f"失败: {f_count}\n\n"
            f"数据已存入数据库。\n"
            f"请切换到「提取与导出」标签页：\n"
            f"  1. 提取并过滤数据\n"
            f"  2. 为筛选后的试验下载文档"
        )
        messagebox.showinfo("下载完成", msg)

    def _on_error(self, error_msg):
        self._set_downloading(False)
        self.app.download_status_var.set("下载失败")
        messagebox.showerror("下载失败", error_msg)

    def _cancel(self):
        """取消当前下载"""
        self.app.download_status_var.set("正在取消...")
        self._log("用户取消了操作，正在终止 R 进程...")

        if self.app.bridge:
            self.app.bridge.cancel()

        self.app.current_search_ids = None  # Clear search IDs on cancel
        self._set_downloading(False)
        self.app.download_status_var.set("已取消")
