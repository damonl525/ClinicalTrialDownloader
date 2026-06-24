#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-9: _SilentPage 去重结构性验证。

QWebEnginePage 实例化需要 QApplication（GUI 环境），无法在无头单测中真正
构造。这里验证可静态检查的不变量：共享类存在、4 个 service 模块能 import
共享类、本地逐字复制的定义已被删除。PySide6 6.10.0 已确认安装，故 import
链路本身可被验证。
"""

import ast
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_DIR = os.path.join(ROOT, "service")
FOUR_FILES = [
    "fda_toc_parser.py",
    "fda_pdf_downloader.py",
    "cde_scraper.py",
    "cde_pdf_downloader.py",
]


def test_shared_module_exports_silent_page():
    """共享模块导出 SilentPage，且是 QWebEnginePage 子类（AST 级检查）。"""
    src = open(os.path.join(SERVICE_DIR, "_silent_page.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "SilentPage" in classes, "service/_silent_page.py 应定义 SilentPage"
    # 父类名应为 QWebEnginePage
    bases = [getattr(b, "id", getattr(b, "attr", None)) for b in classes["SilentPage"].bases]
    assert any("QWebEnginePage" in str(b) for b in bases), "SilentPage 应继承 QWebEnginePage"


def test_no_local_silentpage_class_in_service_files():
    """4 个 service 文件不再各自定义 _SilentPage（去重）。"""
    for fname in FOUR_FILES:
        path = os.path.join(SERVICE_DIR, fname)
        src = open(path, encoding="utf-8").read()
        assert not re.search(r"^class _SilentPage\b", src, re.MULTILINE), (
            f"{fname} 仍有本地 class _SilentPage 定义，应改用共享 service._silent_page"
        )


def test_service_files_import_shared_silent_page():
    """4 个 service 文件 import 共享 SilentPage（运行时 import 链路验证）。"""
    pytest.importorskip("PySide6")  # PySide6 已装；未装则跳过
    import importlib
    for fname in FOUR_FILES:
        mod_name = "service." + os.path.splitext(fname)[0]
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "_SilentPage"), f"{mod_name} 应暴露 _SilentPage（共享别名）"
