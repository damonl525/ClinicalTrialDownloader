#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI 样式配置
"""

from tkinter import ttk


def apply_styles():
    """应用自定义样式"""
    style = ttk.Style()
    style.configure("Title.TLabel", font=("Arial", 14, "bold"))

    # 进度条
    style.configure(
        "pointed.Horizontal.TProgressbar",
        troughcolor="#e0e0e0",
        background="#4a90d9",
        thickness=18,
    )
