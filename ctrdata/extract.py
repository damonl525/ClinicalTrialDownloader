#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data extraction — extract module for CtrdataBridge.

Handles: find_fields(), extract_to_dataframe(), get_unique_ids().
"""

import os
import tempfile
import logging
from typing import List, Optional

import pandas as pd

from core.constants import CONDITION_FIELDS, INTERVENTION_FIELDS
from core.exceptions import DatabaseError, CtrdataError
from ctrdata import process as _proc
from ctrdata.template_loader import render as _render

logger = logging.getLogger(__name__)


# ============================================================
# Protocol filter via direct SQLite query
# ============================================================

def get_protocol_trial_ids(bridge, scope_ids: Optional[List[str]] = None) -> List[str]:
    """Find trial IDs that have Protocol documents via lightweight R query.

    Only extracts documentSection.largeDocumentModule.largeDocs (single field,
    no concept functions, no dedup). Returns list of _id strings.
    """
    if not bridge.db_path:
        return []

    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)

    r_code = _render("protocol_query", db=db, col=col)

    try:
        result = _proc.run_r_json(bridge, r_code, timeout=300)
    except Exception as e:
        logger.warning(f"Protocol query failed: {e}")
        return []

    if not isinstance(result, dict) or not result.get("ok"):
        logger.warning(f"Protocol query error: {result.get('error', 'unknown')}")
        return []

    all_protocol_ids = result.get("ids", [])
    if isinstance(all_protocol_ids, str):
        all_protocol_ids = [all_protocol_ids]

    # If scope_ids provided, intersect (empty list = no results)
    if scope_ids is not None:
        if not scope_ids:
            return []
        scope_set = set(str(sid) for sid in scope_ids)
        filtered = [
            tid for tid in all_protocol_ids
            if any(str(tid).startswith(str(sid)) for sid in scope_set)
        ]
        logger.info(
            f"Protocol query: {result.get('total', '?')} records, "
            f"{len(all_protocol_ids)} with Protocol, {len(filtered)} in scope"
        )
        return filtered

    logger.info(
        f"Protocol query: {result.get('total', '?')} records, "
        f"{len(all_protocol_ids)} with Protocol docs"
    )
    return all_protocol_ids


# ============================================================
# Field discovery
# ============================================================

def find_fields(bridge, pattern: str = ".*") -> List[str]:
    """查找数据库中可用的字段名"""
    if not bridge.db_path:
        return []

    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    safe_pat = _proc._r_escape(pattern)

    r_code = _render(
        "find_fields",
        db=db,
        col=col,
        pattern=safe_pat,
    )

    try:
        result = _proc.run_r_json(bridge, r_code)
        if isinstance(result, list):
            return result
        return []
    except Exception as e:
        logger.warning(f"查找字段失败: {e}")
        return []


# ============================================================
# Data extraction with filtering
# ============================================================

def extract_to_dataframe(
    bridge,
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
    """
    使用 dbGetFieldsIntoDf 提取数据，通过 CSV 传回 Python

    Args:
        fields: 字段名列表
        calculate: 概念函数列表 (如 ["f.statusRecruitment"])
        deduplicate: 是否去重
        filter_phase: 下载后按阶段过滤 (如 "phase 3")
        filter_status: 下载后按状态过滤 (如 "completed")
        filter_date_start: 起始日期 "YYYY-MM-DD" 或空
        filter_date_end: 结束日期 "YYYY-MM-DD" 或空
        filter_condition: 适应症关键词，空格分隔
        filter_intervention: 干预措施关键词，空格分隔
        scope_ids: 限定提取的试验 ID 列表，空则提取全部

    Returns:
        pandas DataFrame
    """
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")
    if not fields and not calculate:
        raise CtrdataError("请至少指定一个字段或概念函数")

    # Auto-add required fields for filtering
    calculate = list(calculate or [])
    fields = list(fields or [])

    if filter_phase and "f.trialPhase" not in calculate:
        calculate.append("f.trialPhase")
    if filter_status and "f.statusRecruitment" not in calculate:
        calculate.append("f.statusRecruitment")
    if (filter_date_start or filter_date_end) and "f.startDate" not in calculate:
        calculate.append("f.startDate")
    if filter_condition:
        if "f.trialTitle" not in calculate:
            calculate.append("f.trialTitle")
        for f in CONDITION_FIELDS:
            if f not in fields:
                fields.append(f)
    if filter_intervention:
        for f in INTERVENTION_FIELDS:
            if f not in fields:
                fields.append(f)

    # Always include intervention field for FDA matching
    for f in INTERVENTION_FIELDS:
        if f not in fields:
            fields.append(f)

    # Use temp CSV file to transfer data
    tmp_csv = tempfile.mktemp(suffix=".csv")
    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    csv_path = _proc._r_escape(tmp_csv.replace(os.sep, "/"))

    fields_r = ""
    if fields:
        fields_str = ", ".join(f'"{_proc._r_escape(f)}"' for f in fields)
        fields_r = f", fields = c({fields_str})"

    calc_r = ""
    if calculate:
        calc_str = ", ".join(f'"{_proc._r_escape(c)}"' for c in calculate)
        calc_r = f", calculate = c({calc_str})"

    dedup_block = ""
    if deduplicate:
        dedup_block = """
        unique_ids <- ctrdata::dbFindIdsUniqueTrials(con = con, verbose = FALSE)
        if (length(unique_ids) > 0 && "_id" %in% names(df)) {
            df <- df[df$`_id` %in% unique_ids, ]
        }
        """

    scope_block = ""
    if scope_ids:
        ids_str = ", ".join(f'"{_proc._r_escape(sid)}"' for sid in scope_ids)
        # Prefix matching: EUCTR _id includes country suffix (e.g. EUCTRxxx-DE)
        # but ctrLoadQueryIntoDb()$success returns the base ID without suffix.
        scope_block = (
            "if (\"_id\" %in% names(df)) {\n"
            f"    scope_ids <- c({ids_str})\n"
            "    id_col <- as.character(df$`_id`)\n"
            "    mask <- rep(FALSE, length(id_col))\n"
            "    for (sid in scope_ids) {\n"
            "        mask <- mask | startsWith(id_col, sid)\n"
            "    }\n"
            "    df <- df[mask, ]\n"
            "}\n"
        )

    r_code = _render(
        "extract_dataframe",
        db=db,
        col=col,
        fields_r=fields_r,
        calc_r=calc_r,
        dedup_block=dedup_block,
        scope_block=scope_block,
        csv_path=csv_path,
    )

    try:
        # Use run_r_streaming so bridge.cancel() can kill the R process
        proc = _proc.run_r_streaming(bridge, r_code)

        import json as _json
        output = proc.stdout.strip()
        result = {}
        for line in reversed(output.split("\n")):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = _json.loads(line)
                except _json.JSONDecodeError:
                    pass
                break

        if os.path.exists(tmp_csv):
            df = pd.read_csv(tmp_csv, encoding="utf-8-sig", low_memory=False)
            try:
                os.unlink(tmp_csv)
            except Exception:
                pass

            # Diagnostic: log R-layer row counts
            n_r_after_extract = result.get("n_after_extract", "?") if isinstance(result, dict) else "?"
            n_r_final = result.get("rows", "?") if isinstance(result, dict) else "?"
            logger.info(
                f"Extract: R returned {n_r_after_extract} rows, "
                f"after dedup+scope: {n_r_final}, CSV read: {len(df)}"
            )

            # Python-side scope fallback (catches edge cases R prefix match missed)
            if scope_ids and "_id" in df.columns:
                id_col = df["_id"].astype(str)
                mask = id_col.apply(
                    lambda x: any(x.startswith(str(sid)) for sid in scope_ids)
                )
                df = df[mask]

            # Post-download filtering: phase / status
            if filter_phase and ".trialPhase" in df.columns:
                df = df[df[".trialPhase"].astype(str).str.contains(filter_phase, case=False, na=False)]
            if filter_status and ".statusRecruitment" in df.columns:
                df = df[df[".statusRecruitment"].astype(str).str.contains(filter_status, case=False, na=False)]

            # Date range filter — NaT values are preserved
            if (filter_date_start or filter_date_end) and ".startDate" in df.columns:
                df[".startDate"] = pd.to_datetime(df[".startDate"], errors="coerce")
                mask = pd.Series(True, index=df.index)
                if filter_date_start:
                    mask &= (df[".startDate"] >= filter_date_start) | df[".startDate"].isna()
                if filter_date_end:
                    mask &= (df[".startDate"] <= filter_date_end) | df[".startDate"].isna()
                df = df[mask]

            # Condition keyword filter
            if filter_condition:
                keywords = filter_condition.strip().split()
                search_cols = [c for c in [".trialTitle"] + CONDITION_FIELDS if c in df.columns]
                if search_cols:
                    for kw in keywords:
                        kw_mask = pd.Series(False, index=df.index)
                        for col in search_cols:
                            kw_mask |= df[col].astype(str).str.contains(kw, case=False, na=False, regex=False)
                        df = df[kw_mask]

            # Intervention keyword filter
            if filter_intervention:
                keywords = filter_intervention.strip().split()
                search_cols = [c for c in INTERVENTION_FIELDS if c in df.columns]
                if search_cols:
                    for kw in keywords:
                        kw_mask = pd.Series(False, index=df.index)
                        for col in search_cols:
                            kw_mask |= df[col].astype(str).str.contains(kw, case=False, na=False, regex=False)
                        df = df[kw_mask]

            return df
        else:
            return pd.DataFrame()

    except Exception as e:
        if os.path.exists(tmp_csv):
            try:
                os.unlink(tmp_csv)
            except Exception:
                pass
        raise CtrdataError(f"数据提取失败: {e}")


# ============================================================
# Cross-register deduplication
# ============================================================

def get_unique_ids(bridge) -> List[str]:
    """获取跨注册中心去重后的唯一试验 ID"""
    if not bridge.db_path:
        return []

    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)

    r_code = _render(
        "unique_ids",
        db=db,
        col=col,
    )

    try:
        result = _proc.run_r_json(bridge, r_code)
        if isinstance(result, list):
            return result
        return []
    except Exception as e:
        logger.warning(f"去重失败: {e}")
        return []
