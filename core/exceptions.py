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


class DownloadTimeoutError(DownloadError):
    """Raised when an R download operation exceeds the time limit.

    Carries the elapsed seconds, user_action (continue/skip/cancel),
    so the caller can decide how to handle the timeout.
    """

    def __init__(self, message: str = "", elapsed: int = 0, register: str = "",
                 user_action: str = ""):
        super().__init__(message)
        self.elapsed = elapsed
        self.register = register
        self.user_action = user_action
