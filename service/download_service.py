#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download service — orchestrates search/download business logic.

Extracted from search_tab._worker closures so that business logic
is testable without Qt dependencies.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from core.exceptions import DownloadTimeoutError

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Structured result from a download operation."""
    n: int = 0
    success: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    failed_detail: list = field(default_factory=list)
    skipped: int = 0
    skipped_detail: list = field(default_factory=list)
    protocol_skipped: int = 0
    protocol_skipped_ids: list = field(default_factory=list)
    db_total: str = "?"
    cancelled: bool = False
    urls: dict = field(default_factory=dict)


class DownloadService:
    """Orchestrates download operations via CtrdataBridge.

    All methods accept ``on_log`` and ``on_progress`` callbacks
    so the UI layer can wire them to Qt signals.
    """

    def __init__(self, bridge):
        self.bridge = bridge

    # ================================================================
    # Form-based multi-register download (largest worker, 120 lines)
    # ================================================================

    def form_download(
        self,
        params: dict,
        selected_regs: list,
        is_cancelled: Callable[[], bool] = lambda: False,
        on_log: Callable[[str], None] = None,
        on_progress: Callable[[int, int, str], None] = None,
        on_timeout: Callable[[int, str], str] = None,
    ) -> DownloadResult:
        """
        Full form-download pipeline:
        generate queries → download per register → aggregate.

        Returns DownloadResult with all aggregated data.
        """
        _ui_log = on_log or (lambda m: None)
        _prog = on_progress or (lambda c, t, m: None)

        def _log(msg):
            _ui_log(msg)
            logger.info(msg)

        # 1. Generate queries
        _log("正在通过 ctrGenerateQueries() 生成查询...")
        urls = self.bridge.generate_queries(**params)
        filtered_urls = {k: v for k, v in urls.items() if k in selected_regs}

        _log(f"生成了 {len(filtered_urls)} 个 URL")
        for reg, url in filtered_urls.items():
            _log(f"  {reg}: {url[:200]}")

        if not filtered_urls:
            return DownloadResult(cancelled=False, urls=filtered_urls)

        _log("─" * 50)

        # 2. Download per register
        total_n = 0
        all_success = []
        all_failed = []
        all_failed_detail = []
        all_skipped = 0
        all_skipped_detail = []
        n_urls = len(filtered_urls)

        _prog(0, n_urls, "正在下载...")

        for i, (reg, url) in enumerate(filtered_urls.items()):
            if is_cancelled():
                _log("用户已取消")
                return DownloadResult(cancelled=True)

            _log(f"[{i+1}/{n_urls}] 正在下载 {reg}...")
            _prog(i, n_urls, f"正在下载 {reg}... ({i+1}/{n_urls})")

            # Per-register timeout callback closure
            reg_on_timeout = None
            if on_timeout:
                def reg_on_timeout(elapsed, _reg=reg):
                    return on_timeout(elapsed, _reg)

            try:
                result = self.bridge.load_into_db(
                    url=url,
                    callback=lambda line: _log(f"  {line}") if line and not line.startswith("{") and not line.startswith("ERROR") else None,
                    skip_parse=True,
                    on_timeout=reg_on_timeout,
                )
                n = result.get("n", 0)
                s = result.get("success", [])
                f = result.get("failed", [])
                sk = result.get("skipped", 0)
                sk_ids = []
                if isinstance(sk, dict):
                    sk_ids = list(sk.keys()) if sk else []
                    sk = len(sk_ids)
                elif isinstance(sk, list):
                    sk_ids = sk
                    sk = len(sk)
                if not isinstance(sk, int):
                    sk = 0
                if not isinstance(s, list):
                    s = [s] if s else []
                if not isinstance(f, list):
                    f = [f] if f else []

                total_n += n
                all_success.extend(s)
                all_failed.extend(f)
                for fid in (f if isinstance(f, list) else []):
                    all_failed_detail.append({"register": reg, "id": str(fid)})
                all_skipped += sk
                if sk_ids:
                    all_skipped_detail.append({"register": reg, "ids": sk_ids})

                parts = [f"{reg}: {n} 条", f"成功 {len(s)}"]
                if sk:
                    parts.append(f"跳过 {sk}")
                if f:
                    parts.append(f"失败 {len(f)}")
                _log(f"  {', '.join(parts)}")
                _prog(i + 1, n_urls, f"{reg} 完成 ({i+1}/{n_urls})")

            except DownloadTimeoutError as e:
                if e.user_action == "cancel":
                    _log(f"  {reg}: 用户取消下载")
                    return DownloadResult(cancelled=True)
                elif e.user_action == "skip":
                    _log(f"  {reg}: 用户跳过（已运行 {e.elapsed}秒）")
                    all_failed.append(f"{reg}: 超时（用户跳过）")
                    all_failed_detail.append({"register": reg, "error": f"超时（已运行 {e.elapsed}秒）"})
                else:
                    _log(f"  {reg}: 超时 — {e}")
                    all_failed.append(f"{reg}: {e}")
                    all_failed_detail.append({"register": reg, "error": str(e)})

            except Exception as e:
                _log(f"  {reg}: 失败 — {e}")
                all_failed.append(f"{reg}: {e}")
                all_failed_detail.append({"register": reg, "error": str(e)})

        # 3. Get updated DB info
        try:
            db_info = self.bridge.get_db_info()
            db_total = db_info.get("total_records", "?")
        except Exception:
            db_total = "?"

        _log("─" * 50)
        _log(f"下载完成! 本次 {len(all_success)} 条, 数据库共 {db_total} 条")

        return DownloadResult(
            n=total_n,
            success=all_success,
            failed=all_failed,
            failed_detail=all_failed_detail,
            skipped=all_skipped,
            skipped_detail=all_skipped_detail,
            db_total=str(db_total),
            cancelled=False,
            urls=filtered_urls,
        )

    # ================================================================
    # URL-based download
    # ================================================================

    def url_download(
        self,
        url: str,
        on_log: Callable[[str], None] = None,
        on_progress: Callable[[int, int, str], None] = None,
    ) -> dict:
        """Parse URL → download → return raw result dict."""
        _ui_log = on_log or (lambda m: None)
        def _log(msg):
            _ui_log(msg)
            logger.info(msg)
        _prog = on_progress or (lambda c, t, m: None)

        _prog(0, 2, "正在解析 URL...")
        _log(f"正在解析 URL: {url[:80]}...")
        parsed = self.bridge.parse_query_url(url)
        reg = parsed.get("register", "?")
        _log(f"注册中心: {reg}")

        _prog(1, 2, f"正在下载 {reg}...")
        _log("开始下载...")
        result = self.bridge.load_into_db(
            url=url,
            callback=lambda line: _log(f"  {line}") if line and not line.startswith("{") and not line.startswith("ERROR") else None,
        )

        # Normalize success/failed lists
        s = result.get("success", [])
        if not isinstance(s, list):
            s = [s] if s else []
        result["success"] = s

        f = result.get("failed", [])
        if not isinstance(f, list):
            f = [f] if f else []
        result["failed"] = f

        _prog(2, 2, "下载完成")
        return result

    # ================================================================
    # Trial ID download
    # ================================================================

    def id_download(
        self,
        trial_id: str,
        on_log: Callable[[str], None] = None,
    ) -> dict:
        """Download single trial by ID → return result dict."""
        _ui_log = on_log or (lambda m: None)
        def _log(msg):
            _ui_log(msg)
            logger.info(msg)

        result = self.bridge.load_by_trial_id(
            trial_id,
            callback=lambda line: _log(f"  {line}") if line else None,
        )

        s = result.get("success", [])
        if not isinstance(s, list):
            s = [s] if s else []
        result["success"] = s

        _log(f"下载完成: {result.get('n', 0)} 条")
        return result

    # ================================================================
    # Update last query
    # ================================================================

    def update_query(
        self,
        query_idx: int = None,
        on_log: Callable[[str], None] = None,
    ) -> dict:
        """Incremental update of a historical query → return result."""
        _ui_log = on_log or (lambda m: None)
        def _log(msg):
            _ui_log(msg)
            logger.info(msg)

        # Auto-detect 0-record queries and force full re-download
        force_update = False
        try:
            history = self.bridge.get_query_history()
            if history is not None and not history.empty:
                row = history.iloc[-1] if query_idx is None else history.iloc[query_idx - 1]
                n_records = row.get("query-records", 0)
                if n_records == 0 or n_records == "?" or n_records == "0" or (
                        isinstance(n_records, float) and math.isnan(n_records)):
                    force_update = True
                    _log("上次查询记录数为 0，将强制重新下载")
        except Exception:
            pass

        result = self.bridge.update_last_query(
            query_index=query_idx,
            callback=lambda line: _log(line),
            force_update=force_update,
        )

        # Normalize success/failed types (same as form_download)
        s = result.get("success", [])
        if not isinstance(s, list):
            s = [s] if s else []
        result["success"] = s

        f = result.get("failed", [])
        if not isinstance(f, list):
            f = [f] if f else []
        result["failed"] = f

        n = result.get("n", 0)
        _log(f"更新完成: 新增 {n} 条, 成功 {len(s)}, 失败 {len(f)}")

        return result

    # ================================================================
    # Synonym lookup
    # ================================================================

    def find_synonyms(
        self,
        intervention: str,
        on_log: Callable[[str], None] = None,
    ) -> list:
        """Find active substance synonyms → return list of strings."""
        _ui_log = on_log or (lambda m: None)
        def _log(msg):
            _ui_log(msg)
            logger.info(msg)

        synonyms = self.bridge.find_synonyms(intervention)

        if synonyms:
            _log(f"找到 {len(synonyms)} 个同义词")
        else:
            _log("未找到同义词")

        return synonyms
