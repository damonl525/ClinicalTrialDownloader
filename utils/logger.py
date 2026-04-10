#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志配置模块

提供全局日志配置，避免分散的 logging.basicConfig 调用
"""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """配置全局日志"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器"""
    return logging.getLogger(name)
