#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download service — orchestrates search/download business logic.

Extracted from search_tab._worker closures so that business logic
is testable without Qt dependencies.
"""

import logging
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
        protocol_filter: bool = False,
        is_cancelled: Callable[[], bool] = lambda: False,
        on_log: Callable[[str], None] = None,
        on_progress: Callable[[int, int, str], None] = None,
        on_timeout: Callable[[int, str], str] = None,
    ) -> DownloadResult:
        """
        Full form-download pipeline:
        generate queries → download per register → aggregate → protocol filter.

        Returns DownloadResult with all aggregated data.
        """
        _log = on_log or (lambda m: None)
        _prog = on_progress or (lambda c, t, m: None)

        # 1. Generate queries
        _log("正在通过 ctrGenerateQueries() 生成查询...")
        urls = self.bridge.generate_queries(**params)
        filtered_urls = {k: v for k, v in urls.items() if k in selected_regs}

        _log(f"生成了 {len(filtered_urls)} 个 URL")
        for reg, url in filtered_urls.items():
            _log(f"  {reg}: {url[:100]}...")

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
                    _log("  用户取消下载")
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

        # 3. Protocol filter
        protocol_skipped = 0
        protocol_skipped_ids = []
        if protocol_filter and all_success and filtered_urls:
            _log("─" * 50)
            _log("正在扫描 Protocol 文档可用性...")
            try:
                protocol_ids = self.bridge.scan_document_availability(
                    urls=filtered_urls,
                    doc_pattern="prot",
                    callback=lambda msg: _log(f"  {msg}"),
                )
                before = len(all_success)
                kept = [tid for tid in all_success if tid in protocol_ids]
                protocol_skipped_ids = [tid for tid in all_success if tid not in protocol_ids]
                all_success = kept
                protocol_skipped = len(protocol_skipped_ids)
                _log(f"  Protocol 过滤: {before} → {len(all_success)} (跳过 {protocol_skipped})")
            except Exception as e:
                _log(f"  Protocol 扫描失败: {e}")

        # 4. Get updated DB info
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
            protocol_skipped=protocol_skipped,
            protocol_skipped_ids=protocol_skipped_ids,
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
        _log = on_log or (lambda m: None)
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
        _log = on_log or (lambda m: None)

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
        _log = on_log or (lambda m: None)

        result = self.bridge.update_last_query(
            query_index=query_idx,
            callback=lambda line: _log(line),
        )

        n = result.get("n", 0)
        s_count = len(result.get("success", []))
        f_count = len(result.get("failed", []))
        _log(f"更新完成: 新增 {n} 条, 成功 {s_count}, 失败 {f_count}")

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
        _log = on_log or (lambda m: None)

        synonyms = self.bridge.find_synonyms(intervention)

        if synonyms:
            _log(f"找到 {len(synonyms)} 个同义词")
        else:
            _log("未找到同义词")

        return synonyms
