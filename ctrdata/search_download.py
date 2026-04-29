#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search trial download — search_download submodule.

Handles: load_into_db() (single + multi URL), load_by_trial_id(),
update_last_query(), scan_document_availability().
"""

import json
import os
import re
import shutil
import tempfile
import logging
from typing import Any, Callable, Dict, List, Set

from core.exceptions import DatabaseError, DownloadError, CtrdataError
from ctrdata import process as _proc
from ctrdata.template_loader import render as _render

logger = logging.getLogger(__name__)


# ============================================================
# Data download — single URL
# ============================================================

def _load_single_url(
    bridge,
    url: str,
    callback: Callable = None,
    only_count: bool = False,
    register: str = None,
    euctrresults: bool = False,
    timeout: int = 600,
    skip_parse: bool = False,
    on_timeout: Callable = None,
) -> dict:
    """Download a single URL into the database."""
    safe_url = _proc._r_escape(url)
    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    only_count_r = ", only.count = TRUE" if only_count else ""
    register_r = f', register = "{_proc._r_escape(register)}"' if register else ""
    euctr_r = ", euctrresults = TRUE" if euctrresults else ""

    if skip_parse:
        query_block = f'''
        result <- tryCatch({{
            suppressWarnings(suppressMessages({{
                ctrdata::ctrLoadQueryIntoDb(
                    queryterm = "{safe_url}",
                    con = con{only_count_r}{register_r}{euctr_r}, verbose = FALSE
                )
            }}))
        }}, error = function(e) {{
            cat(sprintf("ERROR\\t%s\\n", as.character(e$message)))
            list(n = 0L, success = character(0), failed = character(0))
        }})'''
    else:
        query_block = f'''
        query <- ctrdata::ctrGetQueryUrl(url="{safe_url}")
        result <- tryCatch({{
            suppressWarnings(suppressMessages({{
                ctrdata::ctrLoadQueryIntoDb(
                    queryterm = query,
                    con = con{only_count_r}{register_r}{euctr_r}, verbose = FALSE
                )
            }}))
        }}, error = function(e) {{
            cat(sprintf("ERROR\\t%s\\n", as.character(e$message)))
            list(n = 0L, success = character(0), failed = character(0))
        }})'''

    r_code = _render(
        "load_single_url",
        db=db,
        col=col,
        query_block=query_block,
    )

    if callback:
        proc = _proc.run_r_streaming(
            bridge, r_code, callback=callback,
            timeout=timeout, stall_timeout=timeout,
            on_timeout=on_timeout,
        )
        output = proc.stdout.strip()
        for line in reversed(output.split("\n")):
            line = line.strip()
            if line.startswith("{"):
                result = json.loads(line)
                if isinstance(result, dict) and result.get("ok") is False:
                    raise DownloadError(f"数据下载失败: {result.get('error', '')}")
                return result
        return {"ok": True, "raw_output": output}
    else:
        result = _proc.run_r_json(bridge, r_code, timeout=timeout)
        if isinstance(result, dict) and result.get("ok") is False:
            raise DownloadError(f"数据下载失败: {result.get('error', '')}")
        return result


# ============================================================
# Data download — multi-URL
# ============================================================

def _load_multi_url(
    bridge,
    urls: list,
    callback: Callable = None,
    only_count: bool = False,
    register: str = None,
    euctrresults: bool = False,
    timeout: int = 600,
    skip_parse: bool = False,
    on_timeout: Callable = None,
) -> dict:
    """Download multiple URLs (multi-register search) into the database."""
    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    only_count_r = ", only.count = TRUE" if only_count else ""
    euctr_r = ", euctrresults = TRUE" if euctrresults else ""

    download_blocks = []
    for i, url in enumerate(urls):
        safe_url = _proc._r_escape(url)
        if skip_parse:
            query_logic = f'ctrdata::ctrLoadQueryIntoDb(queryterm = "{safe_url}", con = con{only_count_r}{euctr_r}, verbose = FALSE)'
        else:
            query_logic = f'{{ query <- ctrdata::ctrGetQueryUrl(url="{safe_url}"); ctrdata::ctrLoadQueryIntoDb(queryterm = query, con = con{only_count_r}{euctr_r}, verbose = FALSE) }}'

        download_blocks.append(f'''
        {{
            cat(sprintf("REGISTER\\t{i}\\tstart\\n"))
            flush.console()
            r <- tryCatch({{
                suppressWarnings(suppressMessages({{
                    {query_logic}
                }}))
            }}, error = function(e) {{
                list(n = 0L, success = character(0), failed = character(0), error = as.character(e$message))
            }})
            n_r <- ifelse("n" %in% names(r), r$n, 0L)
            s_ids <- if ("success" %in% names(r)) as.character(r$success) else character(0)
            f_ids <- if ("failed" %in% names(r)) as.character(names(r$failed)) else character(0)
            err_r <- if ("error" %in% names(r)) r$error else ""
            cat(sprintf("REGISTER\\t{i}\\t%d\\t%d\\t%d\\t%s\\n", n_r, length(s_ids), length(f_ids), err_r))
            flush.console()
            total_n <- total_n + n_r
            total_success <- c(total_success, s_ids)
            total_failed <- c(total_failed, f_ids)
        }}
        ''')

    download_block = "\n".join(download_blocks)

    r_code = _render(
        "load_multi_url",
        db=db,
        col=col,
        download_blocks=download_block,
    )

    if callback:
        proc = _proc.run_r_streaming(
            bridge, r_code, callback=callback,
            timeout=timeout, stall_timeout=timeout,
            on_timeout=on_timeout,
        )
        output = proc.stdout.strip()
        for line in reversed(output.split("\n")):
            line = line.strip()
            if line.startswith("{"):
                result = json.loads(line)
                if isinstance(result, dict) and result.get("ok") is False:
                    raise DownloadError(f"数据下载失败: {result.get('error', '')}")
                return result
        return {"ok": True, "raw_output": output}
    else:
        result = _proc.run_r_json(bridge, r_code, timeout=timeout)
        if isinstance(result, dict) and result.get("ok") is False:
            raise DownloadError(f"数据下载失败: {result.get('error', '')}")
        return result


def load_into_db(
    bridge,
    url: str,
    callback: Callable = None,
    only_count: bool = False,
    register: str = None,
    euctrresults: bool = False,
    timeout: int = 600,
    skip_parse: bool = False,
    on_timeout: Callable = None,
) -> dict:
    """使用 ctrLoadQueryIntoDb 下载数据到数据库（仅数据，不含文档）"""
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")

    urls = [u.strip() for u in url.strip().split("\n") if u.strip()]

    if len(urls) == 1:
        return _load_single_url(
            bridge, urls[0], callback, only_count, register, euctrresults, timeout, skip_parse,
            on_timeout,
        )
    else:
        return _load_multi_url(
            bridge, urls, callback, only_count, register, euctrresults, timeout, skip_parse,
            on_timeout,
        )


# ============================================================
# Single trial ID download
# ============================================================

def load_by_trial_id(
    bridge,
    trial_id: str,
    euctrresults: bool = False,
    callback: Callable = None,
    timeout: int = 120,
) -> dict:
    """通过试验 ID 直接下载单条数据"""
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")

    _proc._validate_r_input(trial_id, "试验 ID")
    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    safe_id = _proc._r_escape(trial_id)
    euctr_r = ", euctrresults = TRUE" if euctrresults else ""

    r_code = _render(
        "load_by_trial_id",
        db=db,
        col=col,
        safe_id=safe_id,
        euctr_r=euctr_r,
    )

    if callback:
        proc = _proc.run_r_streaming(bridge, r_code, callback=callback, timeout=timeout)
        output = proc.stdout.strip()
        for line in reversed(output.split("\n")):
            line = line.strip()
            if line.startswith("{"):
                result = json.loads(line)
                if isinstance(result, dict) and result.get("ok") is False:
                    raise DownloadError(f"试验下载失败: {result.get('error', '')}")
                return result
        return {"ok": True, "raw_output": output}
    else:
        result = _proc.run_r_json(bridge, r_code, timeout=timeout)
        if isinstance(result, dict) and result.get("ok") is False:
            raise DownloadError(f"试验下载失败: {result.get('error', '')}")
        return result


# ============================================================
# Incremental update
# ============================================================

def update_last_query(
    bridge,
    query_index: int = None,
    callback: Callable = None,
    timeout: int = 600,
    force_update: bool = False,
) -> dict:
    """增量更新查询（querytoupdate）"""
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")

    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    force = "TRUE" if force_update else "FALSE"

    if query_index is not None:
        update_val = str(query_index)
    else:
        update_val = '"last"'

    r_code = _render(
        "update_last_query",
        db=db,
        col=col,
        update_val=update_val,
        force=force,
    )

    if callback:
        proc = _proc.run_r_streaming(bridge, r_code, callback=callback, timeout=timeout)
        output = proc.stdout.strip()
        for line in reversed(output.split("\n")):
            line = line.strip()
            if line.startswith("{"):
                result = json.loads(line)
                if isinstance(result, dict) and result.get("ok") is False:
                    raise DownloadError(f"更新失败: {result.get('error', '')}")
                return result
        return {"ok": True, "raw_output": output}
    else:
        result = _proc.run_r_json(bridge, r_code, timeout=timeout)
        if isinstance(result, dict) and result.get("ok") is False:
            raise DownloadError(f"更新失败: {result.get('error', '')}")
        return result


# ============================================================
# Document availability scan
# ============================================================

def scan_document_availability(
    bridge,
    urls: Dict[str, str],
    doc_pattern: str = "prot",
    timeout_per_url: int = 300,
    callback: Callable = None,
) -> Set[str]:
    """
    快速扫描文档可用性（使用占位文件模式）。

    利用 ctrdata 的 documents.regexp=NULL 特性：
    创建空占位文件而非实际下载，扫描文件名匹配文档模式。
    """
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")
    if not urls:
        return set()

    scan_dir = tempfile.mkdtemp(prefix="ctrdata_doc_scan_")

    try:
        db = _proc._r_escape(bridge.db_path)
        col = _proc._r_escape(bridge.collection)
        dp = _proc._r_escape(scan_dir.replace("\\", "/"))

        for reg, url in urls.items():
            if callback:
                callback(f"扫描 {reg} 文档可用性...")
            safe_url = _proc._r_escape(url)
            r_code = _render(
                "scan_document_availability",
                db=db,
                col=col,
                safe_url=safe_url,
                dp=dp,
            )
            _proc.run_r(bridge, r_code, timeout=timeout_per_url)

        pattern_re = re.compile(doc_pattern, re.IGNORECASE)
        matched_trials = set()

        for root, dirs, files in os.walk(scan_dir):
            for f in files:
                if pattern_re.search(f):
                    trial_id = os.path.basename(root)
                    if trial_id and trial_id != os.path.basename(scan_dir):
                        matched_trials.add(trial_id)

        if callback:
            callback(f"扫描完成: {len(matched_trials)} 条试验有 [{doc_pattern}] 文档")

        return matched_trials

    finally:
        shutil.rmtree(scan_dir, ignore_errors=True)
