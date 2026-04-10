#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一异常定义模块
"""


class CtrdataError(Exception):
    """Base exception for ctrdata operations"""
    pass


class DatabaseError(CtrdataError):
    """Database related errors"""
    pass


class QueryError(CtrdataError):
    """Query generation errors"""
    pass


class DownloadError(CtrdataError):
    """Download related errors"""
    pass
