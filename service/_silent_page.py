#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared QWebEnginePage subclass that silences JavaScript console output.

FDA/CDE 的 QWebEngine service 加载真实网页时，网站自身 JavaScript 抛出的
控制台错误（如 "Container not found"、SyntaxError）会直接打到 stderr。
SilentPage 把这些消息路由到 Python logger（debug 级别），避免污染 stderr。

构造器沿用 QWebEnginePage 原生签名 (profile=None, parent=None)，因此两种
调用方式都兼容：
    SilentPage(parent)           # 默认 profile + parent
    SilentPage(profile, parent)  # 显式 profile + parent
"""

import logging

from PySide6.QtWebEngineCore import QWebEnginePage

logger = logging.getLogger(__name__)


class SilentPage(QWebEnginePage):
    """QWebEnginePage that suppresses JavaScript console messages from stderr."""

    def javaScriptConsoleMessage(self, level, message, line, sourceId):
        logger.debug("JS [%s:%d] %s", sourceId, line, message)
