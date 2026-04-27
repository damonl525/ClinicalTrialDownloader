#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CtrdataBridge facade — bridge module for ctrdata package.

Main class that delegates to connection, search, extract, documents,
and process submodules. Maintains full backward compatibility.
"""

import json
import os
import logging
from typing import Any, Callable, Dict, List, Optional, Set

import pandas as pd

from core.constants import DEFAULT_DB_NAME, DEFAULT_COLLECTION
from core.exceptions import CtrdataError, DatabaseError, QueryError, DownloadError
from ctrdata import process as _proc
from ctrdata import connection as _conn
from ctrdata import search as _search
from ctrdata import extract as _extract
from ctrdata import documents as _docs

logger = logging.getLogger(__name__)


class CtrdataBridge:
    """
    ctrdata R 包的 Python 桥接（通过 subprocess + RScript）

    Each Python method generates R code, executes it via RScript,
    and returns results via JSON/CSV.
    """

    def __init__(self, rscript_path: str = None):
        self.rscript = rscript_path or _proc._find_rscript()
        if not self.rscript:
            raise CtrdataError("未找到 Rscript，请安装 R")

        self.db_path: Optional[str] = None
        self.collection: str = DEFAULT_COLLECTION
        self._current_process = None  # Current R process (supports cancel)

        _proc.cleanup_temp_files()

    # ============================================================
    # Process control
    # ============================================================

    def cancel(self):
        """取消当前正在运行的 R 进程"""
        if self._current_process is not None:
            try:
                self._current_process.kill()
                self._current_process.wait(timeout=5)
            except Exception:
                pass
            self._current_process = None

    def disconnect(self):
        """断开数据库连接，清除内部状态"""
        self.cancel()
        self.db_path = None
        self.collection = DEFAULT_COLLECTION

    # ============================================================
    # 1. Database connection
    # ============================================================

    def connect(
        self, db_path: str = DEFAULT_DB_NAME, collection: str = DEFAULT_COLLECTION
    ) -> Dict[str, Any]:
        """连接 SQLite 数据库"""
        return _conn.connect(self, db_path, collection)

    def get_db_info(self) -> Dict[str, Any]:
        """获取数据库信息"""
        return _conn.get_db_info(self)

    def get_query_history(self) -> pd.DataFrame:
        """获取所有查询历史"""
        return _conn.get_query_history(self)

    def clear_collection(self) -> Dict[str, Any]:
        """清空当前集合的所有记录（保留数据库文件）"""
        return _conn.clear_collection(self)

    def delete_by_prefix(self, prefix: str) -> Dict[str, Any]:
        """删除 _id 以指定前缀开头的记录"""
        return _conn.delete_by_prefix(self, prefix)

    # ============================================================
    # 2. Search URL generation
    # ============================================================

    def generate_queries(
        self,
        condition: str = "",
        intervention: str = "",
        search_phrase: str = "",
        phase: str = "",
        recruitment: str = "",
        start_after: str = "",
        start_before: str = "",
        completed_after: str = "",
        completed_before: str = "",
        population: str = "",
        countries: str = "",
        only_med_interv_trials: bool = True,
        only_with_results: bool = False,
    ) -> Dict[str, str]:
        """调用 ctrGenerateQueries() 生成各注册中心的搜索 URL"""
        return _search.generate_queries(
            self, condition, intervention, search_phrase, phase, recruitment,
            start_after, start_before, completed_after, completed_before,
            population, countries, only_med_interv_trials, only_with_results,
        )

    def count_trials(self, urls: Dict[str, str], callback: Callable = None) -> Dict[str, int]:
        """预览各注册中心结果数量"""
        return _search.count_trials(self, urls, callback)

    def parse_query_url(self, url: str) -> Dict[str, str]:
        """使用 ctrGetQueryUrl 解析搜索 URL"""
        return _search.parse_query_url(self, url)

    # ============================================================
    # 3. Data download
    # ============================================================

    def load_into_db(
        self,
        url: str,
        callback: Callable = None,
        only_count: bool = False,
        register: str = None,
        euctrresults: bool = False,
        timeout: int = 600,
        skip_parse: bool = False,
        on_timeout: Callable = None,
    ) -> Dict[str, Any]:
        """使用 ctrLoadQueryIntoDb 下载数据到数据库（仅数据，不含文档）"""
        return _search.load_into_db(
            self, url, callback, only_count, register, euctrresults, timeout, skip_parse,
            on_timeout,
        )

    def load_by_trial_id(
        self,
        trial_id: str,
        euctrresults: bool = False,
        callback: Callable = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """通过试验 ID 直接下载单条数据"""
        return _search.load_by_trial_id(self, trial_id, euctrresults, callback, timeout)

    def update_last_query(
        self,
        query_index: int = None,
        callback: Callable = None,
        timeout: int = 600,
    ) -> Dict[str, Any]:
        """增量更新查询（querytoupdate）"""
        return _search.update_last_query(self, query_index, callback, timeout)

    # ============================================================
    # 3b. Document downloads
    # ============================================================

    def download_documents_for_ids(
        self,
        trial_ids: List[str],
        documents_path: str,
        documents_regexp: str = None,
        timeout_total: int = 86400,
        per_trial_timeout: int = 180,
        callback: Callable = None,
    ) -> Dict[str, Any]:
        """为指定的 trial ID 列表下载文档 (per-trial R subprocess with resume)."""
        return _docs.download_documents_for_ids(
            self, trial_ids, documents_path, documents_regexp,
            timeout_total, per_trial_timeout, callback,
        )

    def _get_resume_file(self, documents_path: str) -> str:
        """Get the checkpoint file path for a documents directory."""
        db_basename = os.path.splitext(os.path.basename(self.db_path))[0]
        db_dir = os.path.dirname(self.db_path) or "."
        return os.path.join(db_dir, f"{db_basename}_doc_resume.json")

    @staticmethod
    def _session_hash(trial_ids) -> str:
        """Compute a session hash from sorted trial IDs for resume isolation."""
        import hashlib

        sorted_ids = sorted(str(tid) for tid in trial_ids)
        return hashlib.md5(",".join(sorted_ids).encode()).hexdigest()[:16]

    def _load_resume(self, resume_file: str) -> dict:
        """Load checkpoint data from file."""
        return _docs._load_resume(self, resume_file)

    def _save_resume(
        self, resume_file: str, completed: list, failed: dict, total: int,
        skipped_explicitly: list = None, session: str = None,
        in_progress: list = None,
    ):
        """Atomically write checkpoint file."""
        _docs._save_resume(
            self, resume_file, completed, failed, total,
            skipped_explicitly=skipped_explicitly,
            session=session,
            in_progress=in_progress,
        )

    def _cleanup_resume(self, resume_file: str):
        """Delete checkpoint file."""
        _docs._cleanup_resume(self, resume_file)

    def _download_one_trial_doc(
        self, trial_id: str, documents_path: str,
        documents_regexp: str, timeout: int,
    ) -> Dict[str, Any]:
        """Download documents for a single trial in a separate R process."""
        return _docs.download_one_trial_doc(
            self, trial_id, documents_path, documents_regexp, timeout,
        )

    def clear_resume(self, documents_path: str = None):
        """清除断点续传文件"""
        _docs.clear_resume(self, documents_path)

    def mark_trial_skipped(self, trial_id: str, documents_path: str):
        """将指定 trial 标记为显式跳过"""
        _docs.mark_trial_skipped(self, trial_id, documents_path)

    # ============================================================
    # 4. Field discovery
    # ============================================================

    def find_fields(self, pattern: str = ".*") -> List[str]:
        """查找数据库中可用的字段名"""
        return _extract.find_fields(self, pattern)

    # ============================================================
    # 5. Data extraction
    # ============================================================

    def extract_to_dataframe(
        self,
        fields: List[str] = None,
        calculate: List[str] = None,
        deduplicate: bool = True,
        filter_phase: str = "",
        filter_status: str = "",
        filter_date_start: str = "",
        filter_date_end: str = "",
        filter_condition: str = "",
        filter_intervention: str = "",
        scope_ids: List[str] = None,
    ) -> pd.DataFrame:
        """使用 dbGetFieldsIntoDf 提取数据"""
        return _extract.extract_to_dataframe(
            self,
            fields=fields,
            calculate=calculate,
            deduplicate=deduplicate,
            filter_phase=filter_phase,
            filter_status=filter_status,
            filter_date_start=filter_date_start,
            filter_date_end=filter_date_end,
            filter_condition=filter_condition,
            filter_intervention=filter_intervention,
            scope_ids=scope_ids,
        )

    # ============================================================
    # 6. Deduplication
    # ============================================================

    def get_unique_ids(self) -> List[str]:
        """获取跨注册中心去重后的唯一试验 ID"""
        return _extract.get_unique_ids(self)

    # ============================================================
    # 7. Active substance synonyms
    # ============================================================

    def find_synonyms(self, substance: str) -> List[str]:
        """调用 ctrFindActiveSubstanceSynonyms() 查找活性成分同义词"""
        return _search.find_synonyms(self, substance)

    # ============================================================
    # 8. Open in browser
    # ============================================================

    def open_in_browser(self, url: str = "", registers: List[str] = None) -> None:
        """在浏览器中打开搜索结果"""
        return _search.open_in_browser(self, url, registers)

    # ============================================================
    # 9. Document availability scan
    # ============================================================

    def scan_document_availability(
        self,
        urls: Dict[str, str],
        doc_pattern: str = "prot",
        timeout_per_url: int = 300,
        callback: Callable = None,
    ) -> Set[str]:
        """快速扫描文档可用性"""
        return _search.scan_document_availability(
            self, urls, doc_pattern, timeout_per_url, callback,
        )

    # ============================================================
    # 10. Export
    # ============================================================

    @staticmethod
    def export_csv(df: pd.DataFrame, filename: str) -> str:
        """导出 DataFrame 为 CSV"""
        if not filename.endswith(".csv"):
            filename += ".csv"
        filepath = os.path.abspath(filename)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info(f"数据已导出: {filepath}")
        return filepath
