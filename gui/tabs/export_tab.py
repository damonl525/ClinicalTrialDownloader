#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract & Export tab — redesigned layout

Layout (top to bottom):
  1. Data scope selector (current search vs full database)
  2. Quick document download bar (Protocol / SAP / Protocol+SAP / All)
  3. Collapsible filter panel
  4. Results table
  5. Collapsible advanced options (concept functions + DB fields)
"""

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import webbrowser

import pandas as pd

from core.constants import (
    CONCEPT_FUNCTIONS,
    DEFAULT_CONCEPTS,
    TREEVIEW_DISPLAY_LIMIT,
    DOC_TYPE_OPTIONS,
    FILTER_PHASES,
    FILTER_STATUSES,
)


class ExportTab:
    """Extract & Export tab with data scope + quick doc download"""

    def __init__(self, notebook: ttk.Notebook, app):
        self.app = app
        self._doc_process = None
        self._doc_thread = None
        self._last_docs_regexp = None  # For retry downloads

        self._create(notebook)

    def _create(self, notebook: ttk.Notebook):
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text=" 3. 提取与导出 ")

        # ============================================================
        # 1. Data scope selector
        # ============================================================
        scope_frame = ttk.Frame(tab)
        scope_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(scope_frame, text="数据范围:", font=("Arial", 10, "bold")).pack(
            side=tk.LEFT
        )

        self.app.scope_var = tk.StringVar(
            value=self.app.get_config("export.last_scope", "current_search")
            if hasattr(self.app, 'get_config') else "current_search"
        )
        self.app.scope_current_rb = ttk.Radiobutton(
            scope_frame,
            text="仅本次搜索结果",
            variable=self.app.scope_var,
            value="current_search",
            command=self._on_scope_change,
        )
        self.app.scope_current_rb.pack(side=tk.LEFT, padx=(10, 5))

        self.app.scope_count_label = ttk.Label(
            scope_frame, text="(0 条)", foreground="gray"
        )
        self.app.scope_count_label.pack(side=tk.LEFT)

        self.app.scope_all_rb = ttk.Radiobutton(
            scope_frame,
            text="全部数据库",
            variable=self.app.scope_var,
            value="all_database",
            command=self._on_scope_change,
        )
        self.app.scope_all_rb.pack(side=tk.LEFT, padx=(15, 5))

        self.app.scope_db_count_label = ttk.Label(
            scope_frame, text="(0 条)", foreground="gray"
        )
        self.app.scope_db_count_label.pack(side=tk.LEFT)

        # ============================================================
        # 2. Quick document download bar
        # ============================================================
        doc_bar = ttk.LabelFrame(tab, text="快捷文档下载", padding=8)
        doc_bar.pack(fill=tk.X, pady=(0, 5))

        # Path row
        path_row = ttk.Frame(doc_bar)
        path_row.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(path_row, text="保存到:").pack(side=tk.LEFT)
        self.app.docs_path_var = tk.StringVar(
            value=self.app.get_config("download.default_docs_path", "./documents")
            if hasattr(self.app, 'get_config') else "./documents"
        )
        ttk.Entry(path_row, textvariable=self.app.docs_path_var, width=40).pack(
            side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True
        )
        ttk.Button(path_row, text="浏览...", command=self._browse_docs).pack(
            side=tk.LEFT
        )

        # Quick buttons row
        btn_row = ttk.Frame(doc_bar)
        btn_row.pack(fill=tk.X, pady=(0, 5))

        self.app.doc_protocol_btn = ttk.Button(
            btn_row, text="下载 Protocol",
            command=lambda: self._quick_download("prot"),
            state=tk.DISABLED,
        )
        self.app.doc_protocol_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.app.doc_sap_btn = ttk.Button(
            btn_row, text="下载 SAP",
            command=lambda: self._quick_download("sap_|statist"),
            state=tk.DISABLED,
        )
        self.app.doc_sap_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.app.doc_both_btn = ttk.Button(
            btn_row, text="Protocol + SAP",
            command=lambda: self._quick_download("prot|sap_|statist"),
            state=tk.DISABLED,
        )
        self.app.doc_both_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.app.doc_all_btn = ttk.Button(
            btn_row, text="全部文档",
            command=lambda: self._quick_download(None),
            state=tk.DISABLED,
        )
        self.app.doc_all_btn.pack(side=tk.LEFT, padx=(0, 15))

        self.app.doc_cancel_btn = ttk.Button(
            btn_row, text="取消", command=self._cancel_doc_download, state=tk.DISABLED
        )
        self.app.doc_cancel_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.app.doc_status_var = tk.StringVar(value="请先提取数据或下载搜索结果")
        ttk.Label(
            doc_bar, textvariable=self.app.doc_status_var, foreground="gray"
        ).pack(anchor=tk.W)

        # Doc download progress bar
        self.app.doc_progress = ttk.Progressbar(
            doc_bar, mode="indeterminate",
            style="pointed.Horizontal.TProgressbar",
        )
        self.app.doc_progress.pack(fill=tk.X, pady=(3, 0))

        # ============================================================
        # 3. Collapsible filter panel
        # ============================================================
        self._filter_visible = False  # Default collapsed
        self._filter_toggle_btn = ttk.Button(
            tab,
            text="▸ 过滤条件（可选，点击展开）",
            command=self._toggle_filter,
        )
        self._filter_toggle_btn.pack(fill=tk.X, pady=(0, 0))

        self._filter_frame = ttk.Frame(tab)
        # Don't pack — collapsed by default

        # Filters grid
        filters_inner = ttk.Frame(self._filter_frame)
        filters_inner.pack(fill=tk.X, padx=5, pady=5)

        row = 0
        # Phase
        ttk.Label(filters_inner, text="阶段:").grid(row=row, column=0, sticky=tk.W, pady=3)
        self.phase_var = tk.StringVar(value="全部")
        ttk.Combobox(
            filters_inner, textvariable=self.phase_var,
            values=list(FILTER_PHASES.keys()), state="readonly", width=15,
        ).grid(row=row, column=1, sticky=tk.W, padx=(5, 20), pady=3)

        # Status
        ttk.Label(filters_inner, text="招募状态:").grid(row=row, column=2, sticky=tk.W, pady=3)
        self.status_filter_var = tk.StringVar(value="全部")
        ttk.Combobox(
            filters_inner, textvariable=self.status_filter_var,
            values=list(FILTER_STATUSES.keys()), state="readonly", width=12,
        ).grid(row=row, column=3, sticky=tk.W, padx=(5, 0), pady=3)

        row += 1
        # Date range
        ttk.Label(filters_inner, text="开始日期:").grid(row=row, column=0, sticky=tk.W, pady=3)
        date_row = ttk.Frame(filters_inner)
        date_row.grid(row=row, column=1, columnspan=3, sticky=tk.W, padx=(5, 0), pady=3)
        self.date_start_var = tk.StringVar()
        ttk.Entry(date_row, textvariable=self.date_start_var, width=12).pack(side=tk.LEFT)
        ttk.Label(date_row, text=" ~ ").pack(side=tk.LEFT)
        self.date_end_var = tk.StringVar()
        ttk.Entry(date_row, textvariable=self.date_end_var, width=12).pack(side=tk.LEFT)
        ttk.Label(date_row, text=" YYYY-MM-DD", foreground="gray").pack(side=tk.LEFT, padx=(5, 0))

        row += 1
        # Condition
        ttk.Label(filters_inner, text="适应症:").grid(row=row, column=0, sticky=tk.W, pady=3)
        self.condition_var = tk.StringVar()
        ttk.Entry(filters_inner, textvariable=self.condition_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=(5, 20), pady=3
        )
        ttk.Label(filters_inner, text="关键词，空格分隔", foreground="gray").grid(
            row=row, column=2, columnspan=2, sticky=tk.W, pady=3
        )

        row += 1
        # Intervention
        ttk.Label(filters_inner, text="干预措施:").grid(row=row, column=0, sticky=tk.W, pady=3)
        self.intervention_var = tk.StringVar()
        ttk.Entry(filters_inner, textvariable=self.intervention_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=(5, 20), pady=3
        )

        row += 1
        # Dedup checkbox (inside collapsible filter)
        self.app.deduplicate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            filters_inner, text="跨注册中心去重",
            variable=self.app.deduplicate_var,
        ).grid(row=row, column=0, columnspan=4, sticky=tk.W, pady=3)

        # Extract button + status (OUTSIDE collapsible filter, always visible)
        extract_row = ttk.Frame(tab)
        extract_row.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(
            extract_row, text="提取数据", command=self._extract
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.app.extract_status_var = tk.StringVar(value="就绪")
        ttk.Label(
            extract_row, textvariable=self.app.extract_status_var, foreground="blue"
        ).pack(side=tk.LEFT)

        # ============================================================
        # 4. Results table
        # ============================================================
        results_frame = ttk.LabelFrame(tab, text="提取结果", padding=5)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        stats_frame = ttk.Frame(results_frame)
        stats_frame.pack(fill=tk.X, pady=(0, 5))

        self.app.results_stats_var = tk.StringVar(value="")
        ttk.Label(
            stats_frame, textvariable=self.app.results_stats_var, font=("Arial", 9)
        ).pack(side=tk.LEFT)

        ttk.Button(stats_frame, text="导出 CSV", command=self._export_csv).pack(
            side=tk.RIGHT
        )

        # Pagination controls
        page_frame = ttk.Frame(results_frame)
        page_frame.pack(fill=tk.X, pady=(0, 3))

        self._page_prev_btn = ttk.Button(
            page_frame, text="◀ 上一页", command=self._prev_page, state=tk.DISABLED
        )
        self._page_prev_btn.pack(side=tk.LEFT, padx=(0, 5))

        self._page_label = ttk.Label(page_frame, text="", font=("Arial", 9))
        self._page_label.pack(side=tk.LEFT, padx=(0, 5))

        self._page_next_btn = ttk.Button(
            page_frame, text="下一页 ▶", command=self._next_page, state=tk.DISABLED
        )
        self._page_next_btn.pack(side=tk.LEFT)

        # Pagination state
        self._full_df: pd.DataFrame = None
        self._current_page = 1
        self._total_pages = 1

        tree_frame = ttk.Frame(results_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.app.result_tree = ttk.Treeview(tree_frame, show="headings")
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.app.result_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.app.result_tree.xview)
        self.app.result_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.app.result_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.app.current_data = None

        # Double-click to open trial in browser
        self.app.result_tree.bind("<Double-1>", self._on_tree_double_click)

        # ============================================================
        # 5. Collapsible advanced options (concept functions + DB fields)
        # ============================================================
        adv_expanded = (
            self.app.get_config("gui.advanced_expanded", False)
            if hasattr(self.app, 'get_config') else False
        )
        self._adv_visible = adv_expanded
        self._adv_toggle_btn = ttk.Button(
            tab,
            text=("▾ 高级选项（标准化函数、数据库字段）" if adv_expanded
                  else "▸ 高级选项（标准化函数、数据库字段）"),
            command=self._toggle_advanced,
        )
        self._adv_toggle_btn.pack(fill=tk.X, pady=(0, 0))

        self._adv_frame = ttk.Frame(tab)
        if adv_expanded:
            self._adv_frame.pack(fill=tk.X, after=self._adv_toggle_btn)

        # Concept functions sub-section
        concepts_lf = ttk.LabelFrame(
            self._adv_frame, text="跨注册中心标准化函数 (f.*)", padding=5
        )
        concepts_lf.pack(fill=tk.X, padx=5, pady=(5, 3))

        self.app.concept_vars = {}
        saved_concepts = (
            self.app.get_config("export.last_concepts", None)
            if hasattr(self.app, 'get_config') else None
        )
        for func_name, info in CONCEPT_FUNCTIONS.items():
            display_name = info[0] if isinstance(info, tuple) else info
            if saved_concepts is not None:
                default = func_name in saved_concepts
            else:
                default = func_name in DEFAULT_CONCEPTS
            var = tk.BooleanVar(value=default)
            self.app.concept_vars[func_name] = (var, display_name)

        concepts_inner = ttk.Frame(concepts_lf)
        concepts_inner.pack(fill=tk.X)

        # Group concept functions for better discoverability
        CONCEPT_GROUPS = {
            "核心信息": [
                "f.statusRecruitment", "f.trialPhase",
                "f.trialTitle", "f.startDate",
            ],
            "试验设计": [
                "f.sampleSize", "f.numSites",
                "f.controlType", "f.assignmentType",
            ],
            "其他信息": [
                "f.sponsorType", "f.hasResults", "f.isUniqueTrial",
                "f.primaryEndpointDescription", "f.trialObjectives", "f.trialPopulation",
            ],
        }

        # Flatten all functions in group order, two columns
        all_funcs_ordered = []
        for group_funcs in CONCEPT_GROUPS.values():
            all_funcs_ordered.extend(group_funcs)

        col = 0
        for func_name in all_funcs_ordered:
            if func_name not in self.app.concept_vars:
                continue
            var, display_name = self.app.concept_vars[func_name]
            cb = ttk.Checkbutton(
                concepts_inner,
                text=display_name,
                variable=var,
            )
            row_idx = col // 2
            col_idx = col % 2
            cb.grid(row=row_idx, column=col_idx, sticky=tk.W, padx=(5, 15), pady=2)
            concepts_inner.columnconfigure(col_idx, weight=1)
            col += 1

        # DB fields sub-section
        fields_lf = ttk.LabelFrame(
            self._adv_frame, text="数据库字段", padding=5
        )
        fields_lf.pack(fill=tk.X, padx=5, pady=(3, 5))

        fields_btn_row = ttk.Frame(fields_lf)
        fields_btn_row.pack(fill=tk.X)
        ttk.Button(fields_btn_row, text="刷新字段列表", command=self._refresh_fields).pack(
            side=tk.LEFT
        )
        self.app.fields_status_var = tk.StringVar(value="请先连接数据库并下载数据")
        ttk.Label(
            fields_btn_row, textvariable=self.app.fields_status_var, foreground="gray"
        ).pack(side=tk.LEFT, padx=10)

        fields_list_frame = ttk.Frame(fields_lf)
        fields_list_frame.pack(fill=tk.X, expand=True)

        self.app.fields_listbox = tk.Listbox(
            fields_list_frame, selectmode=tk.EXTENDED, height=4,
            exportselection=False,
        )
        fields_sb = ttk.Scrollbar(
            fields_list_frame, orient=tk.VERTICAL, command=self.app.fields_listbox.yview
        )
        self.app.fields_listbox.configure(yscrollcommand=fields_sb.set)
        self.app.fields_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        fields_sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Initialize scope display
        self._on_scope_change()

    # ================================================================
    # Scope management
    # ================================================================

    def _on_scope_change(self):
        """Update scope labels when radio button changes"""
        # Persist scope selection
        if hasattr(self.app, 'set_config'):
            self.app.set_config("export.last_scope", self.app.scope_var.get())

        search_ids = getattr(self.app, 'current_search_ids', None)
        search_count = len(search_ids) if search_ids else 0
        self.app.scope_count_label.config(text=f"({search_count} 条)")

        # Get DB count if bridge is connected
        db_count = "?"
        if self.app.bridge and self.app.bridge.db_path:
            try:
                info = self.app.bridge.get_db_info()
                db_count = info.get("total_records", "?")
            except Exception:
                pass
        self.app.scope_db_count_label.config(text=f"({db_count} 条)")

    def _get_scope_ids(self):
        """Get trial IDs based on current scope selection"""
        scope = self.app.scope_var.get()
        if scope == "current_search":
            return getattr(self.app, 'current_search_ids', None)
        return None  # None means all database

    # ================================================================
    # Toggle panels
    # ================================================================

    def _toggle_filter(self):
        self._filter_visible = not self._filter_visible
        if self._filter_visible:
            self._filter_frame.pack(fill=tk.X, pady=(0, 5), after=self._filter_toggle_btn)
            self._filter_toggle_btn.config(text="▾ 过滤条件（可选，点击收起）")
        else:
            self._filter_frame.pack_forget()
            self._filter_toggle_btn.config(text="▸ 过滤条件（可选，点击展开）")

    def _toggle_advanced(self):
        self._adv_visible = not self._adv_visible
        if self._adv_visible:
            self._adv_frame.pack(fill=tk.X, after=self._adv_toggle_btn)
            self._adv_toggle_btn.config(text="▾ 高级选项（标准化函数、数据库字段）")
        else:
            self._adv_frame.pack_forget()
            self._adv_toggle_btn.config(text="▸ 高级选项（标准化函数、数据库字段）")
        if hasattr(self.app, 'set_config'):
            self.app.set_config("gui.advanced_expanded", self._adv_visible)

    # ================================================================
    # Field discovery
    # ================================================================

    def _refresh_fields(self):
        if not self.app.bridge or not self.app.bridge.db_path:
            messagebox.showwarning("提示", "请先连接数据库")
            return

        self.app.fields_status_var.set("正在加载...")

        try:
            fields = self.app.bridge.find_fields(".*")
            self.app.fields_listbox.delete(0, tk.END)
            for f in sorted(fields):
                self.app.fields_listbox.insert(tk.END, f)
            self.app.fields_status_var.set(f"共 {len(fields)} 个字段")
        except Exception as e:
            self.app.fields_status_var.set(f"加载失败: {e}")

    # ================================================================
    # Data extraction
    # ================================================================

    def _extract(self):
        if not self.app.bridge or not self.app.bridge.db_path:
            messagebox.showerror("错误", "请先连接数据库")
            return

        # Check scope
        scope = self.app.scope_var.get()
        if scope == "current_search" and not getattr(self.app, 'current_search_ids', None):
            messagebox.showwarning(
                "提示",
                "没有本次搜索结果。请先在「搜索与下载」页下载数据，\n或切换到「全部数据库」范围。"
            )
            return

        filter_date_start = self.date_start_var.get().strip()
        filter_date_end = self.date_end_var.get().strip()
        filter_condition = self.condition_var.get().strip()
        filter_intervention = self.intervention_var.get().strip()

        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        if filter_date_start and not date_pattern.match(filter_date_start):
            messagebox.showwarning("提示", "起始日期格式错误，请使用 YYYY-MM-DD")
            return
        if filter_date_end and not date_pattern.match(filter_date_end):
            messagebox.showwarning("提示", "结束日期格式错误，请使用 YYYY-MM-DD")
            return

        selected_fields = [
            self.app.fields_listbox.get(i)
            for i in self.app.fields_listbox.curselection()
        ]
        selected_concepts = [
            name for name, (var, _) in self.app.concept_vars.items() if var.get()
        ]

        if not selected_fields and not selected_concepts:
            messagebox.showwarning(
                "提示",
                "请至少选择一个标准化函数或数据库字段\n\n"
                "建议：使用默认勾选的标准化函数即可获得常用数据"
            )
            return

        self.app.extract_status_var.set("正在提取...")
        self.app.status_var.set("正在提取数据...")

        try:
            dedup = self.app.deduplicate_var.get()
            filter_phase = FILTER_PHASES.get(self.phase_var.get(), "")
            filter_status = FILTER_STATUSES.get(self.status_filter_var.get(), "")

            df = self.app.bridge.extract_to_dataframe(
                fields=selected_fields if selected_fields else None,
                calculate=selected_concepts if selected_concepts else None,
                deduplicate=dedup,
                filter_phase=filter_phase,
                filter_status=filter_status,
                filter_date_start=filter_date_start,
                filter_date_end=filter_date_end,
                filter_condition=filter_condition,
                filter_intervention=filter_intervention,
            )

            # Scope filtering: limit to current search IDs if selected
            scope_ids = self._get_scope_ids()
            before_scope = len(df)
            if scope_ids:
                if "_id" in df.columns:
                    # Normalize IDs for reliable matching
                    scope_set = set(str(sid).strip() for sid in scope_ids)
                    df_ids = df["_id"].astype(str).str.strip()

                    # Try exact match first
                    exact_mask = df_ids.isin(scope_set)
                    exact_matched = exact_mask.sum()

                    if exact_matched > 0:
                        df = df[exact_mask]
                    else:
                        # Try loose matching: strip version suffix and country codes
                        # e.g. "NCT04523532-1" → "NCT04523532"
                        # e.g. "EUCTR1234-567-DE" → "EUCTR1234-567"
                        def _normalize_id(tid):
                            tid = str(tid).strip()
                            # EUCTR: keep base ID without country suffix
                            if tid.startswith("EUCTR"):
                                parts = tid.rsplit("-", 1)
                                if len(parts) > 1 and len(parts[-1]) == 2:
                                    return parts[0]
                            # NCT: strip version suffix
                            if tid.startswith("NCT") and "-" in tid:
                                return tid.split("-")[0]
                            return tid

                        loose_scope = set(_normalize_id(s) for s in scope_set)
                        loose_df_ids = df_ids.apply(_normalize_id)
                        loose_mask = loose_df_ids.isin(loose_scope)
                        loose_matched = loose_mask.sum()

                        if loose_matched > 0:
                            df = df[loose_mask]
                        else:
                            # No match at all — ask user
                            answer = messagebox.askyesno(
                                "数据范围提醒",
                                f"本次搜索的 {len(scope_set)} 条试验，在提取结果中未找到匹配。\n\n"
                                f"可能原因：不同数据来源的试验编号格式不同。\n\n"
                                f"是否显示数据库中的全部提取结果？\n"
                                f"（选「否」将取消本次提取）"
                            )
                            if not answer:
                                self.app.extract_status_var.set("已取消（ID 不匹配）")
                                return
                            # User chose to continue — skip filtering, show all data
                else:
                    self.app.extract_status_var.set("警告: 数据中无 _id 列，无法按搜索范围过滤")
            # else: scope is "all_database" — no filtering

            self.app.current_data = df

            # Save filtered_ids for document download
            if "_id" in df.columns:
                self.app.filtered_ids = df["_id"].tolist()
            else:
                self.app.filtered_ids = list(range(len(df)))

            self._display_results(df)

            # Stats summary
            unique_info = " (已去重)" if dedup else ""
            scope_info = ""
            if scope_ids:
                scope_info = f", 范围过滤 {before_scope} → {len(df)}"
            parts = [f"提取完成: {len(df)} 行, {len(df.columns)} 列{unique_info}{scope_info}"]
            if filter_phase:
                parts.append(f"阶段={filter_phase}")
            if filter_status:
                parts.append(f"状态={filter_status}")
            self.app.extract_status_var.set(" | ".join(parts))
            self.app.status_var.set(f"数据提取成功: {len(df)} 行")

            # Enable quick download buttons
            self._enable_doc_buttons()

            # Save concept function selection to config
            if hasattr(self.app, 'set_config'):
                selected_concepts = [
                    name for name, (var, _) in self.app.concept_vars.items() if var.get()
                ]
                self.app.set_config("export.last_concepts", selected_concepts)

        except Exception as e:
            self.app.extract_status_var.set("提取失败")
            self.app.status_var.set("就绪")
            messagebox.showerror("提取失败", str(e))

    def _enable_doc_buttons(self):
        """Enable quick doc download buttons when data is available"""
        ids = self.app.filtered_ids
        if ids:
            count = len(ids)
            state = tk.NORMAL
            status = f"可为 {count} 条试验下载文档"
            # Check if search was Protocol-filtered
            if getattr(self.app, 'current_search_ids', None):
                protocol_flag = getattr(self.app, '_protocol_filtered', False)
                if protocol_flag:
                    status += " (已过滤: 仅含Protocol)"
            self.app.doc_status_var.set(status)
        else:
            state = tk.DISABLED
            self.app.doc_status_var.set("没有可下载的试验数据")

        for btn in [
            self.app.doc_protocol_btn,
            self.app.doc_sap_btn,
            self.app.doc_both_btn,
            self.app.doc_all_btn,
        ]:
            btn.config(state=state)

    def _display_results(self, df: pd.DataFrame):
        """Display results in Treeview with pagination"""
        # Clear tree
        for item in self.app.result_tree.get_children():
            self.app.result_tree.delete(item)

        if df is None or len(df) == 0:
            self.app.results_stats_var.set("无数据")
            self._full_df = None
            self._current_page = 1
            self._total_pages = 1
            self._update_page_controls()
            return

        # Store full dataframe and setup columns
        self._full_df = df
        columns = list(df.columns)
        self.app.result_tree["columns"] = columns

        for col in columns:
            self.app.result_tree.heading(
                col, text=col,
                command=lambda c=col: self._sort_column(c, False),
            )
            self.app.result_tree.column(col, width=120, anchor="w")

        # Calculate pagination
        self._total_pages = max(1, -(-len(df) // TREEVIEW_DISPLAY_LIMIT))
        self._current_page = 1
        self._render_page()

    def _render_page(self):
        """Render current page of results"""
        for item in self.app.result_tree.get_children():
            self.app.result_tree.delete(item)

        if self._full_df is None:
            return

        start = (self._current_page - 1) * TREEVIEW_DISPLAY_LIMIT
        end = start + TREEVIEW_DISPLAY_LIMIT
        page_df = self._full_df.iloc[start:end]

        columns = list(self._full_df.columns)
        for i, row in page_df.iterrows():
            values = [
                str(row[col])[:200] if pd.notna(row[col]) else ""
                for col in columns
            ]
            self.app.result_tree.insert("", tk.END, values=values)

        self.app.results_stats_var.set(
            f"共 {len(self._full_df)} 行"
        )
        self._update_page_controls()

    def _update_page_controls(self):
        """Update pagination button states and label"""
        total = self._total_pages
        current = self._current_page

        self._page_label.config(text=f"第 {current} 页 / 共 {total} 页")
        self._page_prev_btn.config(
            state=tk.NORMAL if current > 1 else tk.DISABLED
        )
        self._page_next_btn.config(
            state=tk.NORMAL if current < total else tk.DISABLED
        )

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._render_page()

    def _next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._render_page()

    # ================================================================
    # Treeview sorting
    # ================================================================

    def _sort_column(self, col, reverse):
        """Sort full dataframe by column, then re-render current page"""
        if self._full_df is None or col not in self._full_df.columns:
            return

        # Sort full dataframe
        try:
            self._full_df = self._full_df.sort_values(
                by=col, ascending=not reverse, key=lambda x: pd.to_numeric(x, errors="coerce")
            )
        except Exception:
            self._full_df = self._full_df.sort_values(by=col, ascending=not reverse)

        # Reset page to 1 after sort
        self._current_page = 1
        self._render_page()

        # Update column header indicators
        arrow = " ↓" if reverse else " ↑"
        for c in self.app.result_tree["columns"]:
            self.app.result_tree.heading(
                c,
                text=c + (arrow if c == col else ""),
                command=lambda c=c: self._sort_column(c, not reverse),
            )

    # ================================================================
    # Double-click trial → open in browser
    # ================================================================

    def _on_tree_double_click(self, event):
        """Open selected trial in default browser"""
        selection = self.app.result_tree.selection()
        if not selection:
            return
        item = self.app.result_tree.item(selection[0])
        values = item.get("values", [])
        if not values:
            return

        trial_id = str(values[0]).strip()
        if not trial_id:
            return

        url = None
        if trial_id.startswith("NCT"):
            url = f"https://clinicaltrials.gov/study/{trial_id}"
        elif trial_id.startswith("EUCTR"):
            url = (
                f"https://www.clinicaltrialsregister.eu/"
                f"ctr-search/trial/{trial_id}"
            )
        elif trial_id.startswith("ISRCTN"):
            url = f"https://www.isrctn.com/{trial_id}"
        elif trial_id.startswith("EU"):
            # CTIS trials
            url = f"https://euclinicaltrials.eu/ctis/#/search?searchTerm={trial_id}"

        if url:
            webbrowser.open(url)
        else:
            messagebox.showinfo(
                "提示",
                f"无法识别试验编号格式：{trial_id}\n"
                f"请手动在浏览器中搜索该编号。"
            )

    # ================================================================
    # Quick document download
    # ================================================================

    def _browse_docs(self):
        path = filedialog.askdirectory(title="选择文档保存目录")
        if path:
            self.app.docs_path_var.set(path)

    def _quick_download(self, doc_regexp: str = None):
        """Quick download documents with preset regexp"""
        filtered_ids = getattr(self.app, 'filtered_ids', None)
        if not filtered_ids:
            # Try to use current_search_ids directly (skip extract step)
            search_ids = getattr(self.app, 'current_search_ids', None)
            if search_ids:
                count = len(search_ids)
                if not messagebox.askyesno(
                    "确认下载范围",
                    f"尚未提取数据，将为本次搜索的全部 {count} 条记录下载文档。\n\n"
                    f"建议先「提取数据」并筛选，只为需要的试验下载文档。\n\n"
                    f"是否继续下载全部 {count} 条记录的文档？"
                ):
                    return
                filtered_ids = search_ids
            else:
                messagebox.showwarning("提示", "没有可下载的试验数据，请先提取数据或下载搜索结果")
                return

        docs_path = self.app.docs_path_var.get().strip()
        if not docs_path:
            messagebox.showerror("错误", "请指定文档保存路径")
            return

        self._last_docs_regexp = doc_regexp  # Save for retry downloads
        total = len(filtered_ids)

        # UI state
        self._set_doc_buttons_state(tk.DISABLED)
        self.app.doc_cancel_btn.config(state=tk.NORMAL)
        self.app.doc_progress.config(mode="indeterminate")
        self.app.doc_progress.start(15)
        self.app.doc_status_var.set(f"正在下载文档 0/{total}...")

        # Background thread
        self._doc_thread = threading.Thread(
            target=self._doc_download_worker,
            args=(filtered_ids, docs_path, doc_regexp, total),
            daemon=True,
        )
        self._doc_thread.start()

    def _set_doc_buttons_state(self, state):
        """Set state of all doc download buttons"""
        for btn in [
            self.app.doc_protocol_btn,
            self.app.doc_sap_btn,
            self.app.doc_both_btn,
            self.app.doc_all_btn,
        ]:
            btn.config(state=state)

    def _doc_download_worker(self, trial_ids, docs_path, docs_regexp, total):
        """Background doc download worker — auto-skip on timeout (120s)"""
        try:
            def on_progress(current, total_count, trial_id, status, err=None):
                def _update():
                    self.app.doc_status_var.set(
                        f"正在下载文档 {current}/{total_count} ({trial_id})..."
                    )
                self.app.root.after(0, _update)

            result = self.app.bridge.download_documents_for_ids(
                trial_ids=trial_ids,
                documents_path=docs_path,
                documents_regexp=docs_regexp,
                per_trial_timeout=120,  # 2 minutes auto-skip
                callback=on_progress,
            )

            self.app.root.after(0, lambda: self._on_doc_complete(result))

        except Exception as e:
            err_msg = str(e)
            self.app.root.after(0, lambda msg=err_msg: self._on_doc_error(msg))

    def _on_doc_complete(self, result):
        self.app.doc_cancel_btn.config(state=tk.DISABLED)
        self.app.doc_progress.stop()
        self.app.doc_progress.config(mode="determinate", value=100)

        # Normalize: R auto_unbox=TRUE converts single-element arrays to scalars
        success = result.get("success", [])
        if isinstance(success, str):
            success = [success]
        failed = result.get("failed", {})
        skipped = result.get("skipped", {})
        total = result.get("total", 0)

        fail_count = len(failed) if isinstance(failed, (dict, list)) else 0
        skip_count = len(skipped) if isinstance(skipped, (dict, list)) else 0

        self.app.doc_status_var.set(
            f"完成: 成功 {len(success)}, 跳过 {skip_count}, 失败 {fail_count}"
        )
        self._set_doc_buttons_state(tk.NORMAL)

        # Show report dialog if there are skips or failures
        if skip_count > 0 or fail_count > 0:
            self._show_download_report(len(success), skip_count, fail_count, skipped, failed)
        elif len(success) == 0:
            messagebox.showwarning(
                "文档下载完成",
                f"请求了 {total} 条试验的文档下载，但未成功下载任何文档。\n\n"
                f"可能原因：\n"
                f"  • 试验没有可供下载的文档\n"
                f"  • 网络连接问题\n"
                f"  • 文档保存路径无效"
            )
        else:
            messagebox.showinfo("文档下载完成", f"全部成功！共下载 {len(success)} 条试验文档。")

    def _show_download_report(self, success_count, skip_count, fail_count, skipped, failed):
        """Show download report window with retry buttons for skipped trials."""
        win = tk.Toplevel(self.app.root)
        win.title("文档下载报告")
        win.geometry("620x420")
        win.transient(self.app.root)

        # Title
        tk.Label(win, text="文档下载完成", font=("", 14, "bold")).pack(pady=10)

        # Stats
        stats_frame = tk.Frame(win)
        stats_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(stats_frame, text=f"成功: {success_count} 条").pack(side=tk.LEFT)
        tk.Label(stats_frame, text=f"跳过: {skip_count} 条 (超时 120 秒)").pack(
            side=tk.LEFT, padx=20
        )
        tk.Label(stats_frame, text=f"失败: {fail_count} 条").pack(side=tk.LEFT)

        # Skipped trials with retry buttons
        if skip_count > 0 and isinstance(skipped, dict) and skipped:
            skip_frame = tk.LabelFrame(
                win, text="以下试验有跳过的文件（可按需点击重新下载）", padx=10, pady=5
            )
            skip_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

            canvas = tk.Canvas(skip_frame)
            scrollbar = tk.Scrollbar(skip_frame, orient="vertical", command=canvas.yview)
            scrollable = tk.Frame(canvas)
            scrollable.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
            )
            canvas.create_window((0, 0), window=scrollable, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            for tid, reason in skipped.items():
                row = tk.Frame(scrollable, relief=tk.RIDGE, borderwidth=1)
                row.pack(fill=tk.X, pady=2, padx=5)

                tk.Label(row, text=tid, font=("Arial", 10, "bold")).pack(side=tk.LEFT)
                reason_short = (reason[:60] + "...") if len(reason) > 60 else reason
                tk.Label(row, text=f"({reason_short})", foreground="gray").pack(
                    side=tk.LEFT, padx=5
                )
                tk.Button(
                    row,
                    text="重新下载",
                    command=lambda t=tid: self._retry_single_trial(t),
                ).pack(side=tk.RIGHT)

            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Failed trials (read-only)
        if fail_count > 0 and isinstance(failed, dict) and failed:
            fail_frame = tk.LabelFrame(win, text="失败的试验", padx=10, pady=5)
            fail_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

            fail_text = tk.Text(fail_frame, height=5, state=tk.NORMAL)
            fail_text.pack(fill=tk.BOTH, expand=True)
            for tid, err in list(failed.items())[:10]:
                fail_text.insert(tk.END, f"  {tid}: {err[:100]}\n")
            if fail_count > 10:
                fail_text.insert(tk.END, f"  ... 共 {fail_count} 条失败\n")
            fail_text.config(state=tk.DISABLED)

        # Close button
        tk.Button(win, text="关闭", command=win.destroy, width=15).pack(pady=15)

    def _retry_single_trial(self, trial_id):
        """Re-download documents for a single trial."""
        docs_path = self.app.docs_path_var.get().strip()
        if not docs_path:
            messagebox.showerror("错误", "请指定文档保存路径")
            return

        docs_regexp = self._last_docs_regexp

        self.app.doc_status_var.set(f"正在重新下载 {trial_id}...")
        self.app.doc_progress.config(mode="indeterminate")
        self.app.doc_progress.start(15)

        def worker():
            try:
                result = self.app.bridge.download_documents_for_ids(
                    trial_ids=[trial_id],
                    documents_path=docs_path,
                    documents_regexp=docs_regexp,
                    per_trial_timeout=120,
                    callback=lambda c, t, tid, s, err=None: self.app.root.after(
                        0, lambda: self.app.doc_status_var.set(f"正在下载 {tid} ({s})...")
                    ),
                )
                success = result.get("success", [])
                self.app.root.after(0, self.app.doc_progress.stop)
                if success:
                    self.app.root.after(
                        0, lambda: messagebox.showinfo("成功", f"{trial_id} 文档下载成功！")
                    )
                else:
                    self.app.root.after(
                        0, lambda: messagebox.showinfo("失败", f"{trial_id} 文档下载失败")
                    )
                self.app.root.after(0, lambda: self.app.doc_status_var.set("完成"))
            except Exception as e:
                self.app.root.after(0, self.app.doc_progress.stop)
                self.app.root.after(
                    0, lambda: messagebox.showerror("错误", f"下载失败: {e}")
                )
                self.app.root.after(0, lambda: self.app.doc_status_var.set("下载失败"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_doc_error(self, error_msg):
        self.app.doc_cancel_btn.config(state=tk.DISABLED)
        self.app.doc_progress.stop()
        self.app.doc_progress.config(mode="determinate", value=0)
        self.app.doc_status_var.set("文档下载失败")
        self._set_doc_buttons_state(tk.NORMAL)
        messagebox.showerror("文档下载失败", error_msg)

    def _cancel_doc_download(self):
        self.app.doc_cancel_btn.config(state=tk.DISABLED)
        self.app.doc_progress.stop()
        self.app.doc_progress.config(mode="determinate", value=0)
        self.app.doc_status_var.set("正在取消...")

        if self.app.bridge:
            self.app.bridge.cancel()

        self.app.doc_status_var.set("已取消")
        self._set_doc_buttons_state(tk.NORMAL)

    # ================================================================
    # Export
    # ================================================================

    def _export_csv(self):
        if self.app.current_data is None or len(self.app.current_data) == 0:
            messagebox.showwarning("提示", "没有数据可导出，请先提取数据")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile="clinical_trials_data.csv",
        )

        if filename:
            try:
                from ctrdata_core import CtrdataBridge
                filepath = CtrdataBridge.export_csv(self.app.current_data, filename)
                messagebox.showinfo("导出成功", f"数据已导出到:\n{filepath}")
                self.app.status_var.set(f"已导出: {os.path.basename(filepath)}")
            except Exception as e:
                messagebox.showerror("导出失败", str(e))
