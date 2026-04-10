#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型定义
"""

from dataclasses import dataclass
from enum import Enum


class DownloadStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


@dataclass
class DownloadResult:
    status: DownloadStatus
    message: str
    files_downloaded: int = 0
    files_failed: int = 0
    retry_count: int = 0
