#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pytest 全局 conftest — 测试环境的公共准备。

确保 QApplication 单例可用，并设置 QSettings 跳过首次启动的 guide dialog
（guide dialog 是模态的 dlg.exec()，会阻塞测试线程导致超时）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication


def pytest_configure(config):
    """pytest 启动时执行一次。"""
    # 确保 QApplication 单例（测试创建 QWidget/MainWindow 前必须有）
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # 跳过 MainWindow 构造时自动弹出的 guide dialog（模态，会阻塞测试）。
    # 注意：MainWindow 用的是 org "ctrdata_downloader"/"MainWindow" 的 QSettings，
    # 与 ui.app.get_settings()（org "ClinicalTrialDownloader"/"App"）不同。
    from PySide6.QtCore import QSettings
    QSettings("ctrdata_downloader", "MainWindow").setValue("guide_dont_show", True)
