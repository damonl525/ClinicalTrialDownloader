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
    ) -> Dict[str, Any]:
        """使用 ctrLoadQueryIntoDb 下载数据到数据库（仅数据，不含文档）"""
        return _search.load_into_db(
            self, url, callback, only_count, register, euctrresults, timeout, skip_parse,
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
        timeout_total: int = 7200,
        per_trial_timeout: int = 180,
        callback: Callable = None,
    ) -> Dict[str, Any]:
        """
        为指定的 trial ID 列表下载文档。

        Through a Python-side loop calling ctrLoadQueryIntoDb(queryterm=trial_id)
        per trial. Supports global timeout, per-trial timeout skip, resume,
        and progress callbacks.
        """
        if not self.db_path:
            raise DatabaseError("请先连接数据库")
        if not trial_ids:
            return {"ok": True, "success": [], "failed": {}, "skipped": {}, "total": 0}

        # Ensure documents directory exists
        os.makedirs(documents_path, exist_ok=True)

        # Resume file
        resume_file = self._get_resume_file(documents_path)
        resume_data = self._load_resume(resume_file)

        # Session isolation: if trial_ids differ from last session, clear resume
        current_session = self._session_hash(trial_ids)
        if resume_data.get("session") and resume_data["session"] != current_session:
            self._cleanup_resume(resume_file)
            resume_data = {"completed": [], "failed": {}, "skipped_explicitly": [], "total": 0, "session": None}

        # Filter already completed and explicitly skipped IDs
        already_done = set(resume_data.get("completed", []))
        skipped_explicit = set(resume_data.get("skipped_explicitly", []))
        remaining = [tid for tid in trial_ids if tid not in already_done and tid not in skipped_explicit]

        if not remaining:
            # All IDs were already completed in this session
            requested_set = set(str(tid) for tid in trial_ids)
            return {
                "ok": True,
                "success": [tid for tid in already_done if tid in requested_set],
                "failed": {},
                "skipped": {},
                "total": len(trial_ids),
            }

        total_to_process = len(remaining)
        runtime_completed = list(already_done)
        runtime_failed = dict(resume_data.get("failed", {}))
        runtime_skipped_explicit = list(resume_data.get("skipped_explicitly", []))

        for i, tid in enumerate(remaining, 1):
            if callback:
                callback(i, total_to_process, tid, "start", None)

            try:
                result = self._download_one_trial_doc(
                    tid, documents_path, documents_regexp, per_trial_timeout
                )
                if result.get("ok"):
                    runtime_completed.append(tid)
                    if callback:
                        callback(i, total_to_process, tid, "ok", None)
                else:
                    err = result.get("error", "unknown")
                    runtime_failed[tid] = err
                    if callback:
                        callback(i, total_to_process, tid, "error", err)

            except CtrdataError as e:
                # Stall timeout — skip this trial, continue with next
                err_msg = f"TIMEOUT({per_trial_timeout}s): {e}"
                runtime_failed[tid] = err_msg
                if callback:
                    callback(i, total_to_process, tid, "skip", err_msg)

            self._save_resume(
                resume_file,
                runtime_completed,
                runtime_failed,
                len(trial_ids),
                skipped_explicitly=runtime_skipped_explicit,
                session=current_session,
            )

        # Separate skipped (timeout) from failed
        skipped = {}
        failed = {}
        for tid, err in runtime_failed.items():
            if "TIMEOUT" in str(err):
                skipped[tid] = err
            else:
                failed[tid] = err

        # Cleanup resume if all succeeded
        if not failed and not skipped:
            self._cleanup_resume(resume_file)

        return {
            "ok": True,
            "success": list(runtime_completed),
            "failed": failed,
            "skipped": skipped,
            "total": len(trial_ids),
        }

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
        if not os.path.exists(resume_file):
            return {"completed": [], "failed": {}, "skipped_explicitly": [], "total": 0, "session": None}
        try:
            with open(resume_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "completed": list(data.get("completed", [])),
                "failed": dict(data.get("failed", {})),
                "skipped_explicitly": list(data.get("skipped_explicitly", [])),
                "total": data.get("total", 0),
                "session": data.get("session", None),
            }
        except Exception:
            return {"completed": [], "failed": {}, "skipped_explicitly": [], "total": 0, "session": None}

    def _save_resume(
        self, resume_file: str, completed: list, failed: dict, total: int,
        skipped_explicitly: list = None, session: str = None,
    ):
        """Atomically write checkpoint file."""
        data = {
            "completed": completed,
            "failed": failed,
            "total": total,
            "skipped_explicitly": skipped_explicitly or [],
            "session": session or "",
        }
        tmp_file = resume_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_file, resume_file)

    def _cleanup_resume(self, resume_file: str):
        """Delete checkpoint file."""
        try:
            if os.path.exists(resume_file):
                os.unlink(resume_file)
        except Exception:
            pass

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
        resume_file = self._get_resume_file(documents_path or "")
        self._cleanup_resume(resume_file)

    def mark_trial_skipped(self, trial_id: str, documents_path: str):
        """将指定 trial 标记为显式跳过"""
        resume_file = self._get_resume_file(documents_path)
        resume_data = self._load_resume(resume_file)
        skipped = list(resume_data.get("skipped_explicitly", []))
        if trial_id not in skipped:
            skipped.append(trial_id)
        self._save_resume(
            resume_file,
            resume_data.get("completed", []),
            resume_data.get("failed", {}),
            resume_data.get("total", 0),
            skipped_explicitly=skipped,
            session=resume_data.get("session"),
        )

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
    ) -> pd.DataFrame:
        """使用 dbGetFieldsIntoDf 提取数据"""
        return _extract.extract_to_dataframe(
            self, fields, calculate, deduplicate,
            filter_phase, filter_status, filter_date_start, filter_date_end,
            filter_condition, filter_intervention,
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
