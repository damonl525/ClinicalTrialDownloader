#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database connection management — connection module for CtrdataBridge.

Handles: connect(), get_db_info(), get_query_history().
"""

import os
import tempfile
import logging
from typing import Any

import pandas as pd

from core.constants import DEFAULT_DB_NAME, DEFAULT_COLLECTION
from core.exceptions import DatabaseError, CtrdataError
from ctrdata import process as _proc
from ctrdata.template_loader import render as _render

logger = logging.getLogger(__name__)


# ============================================================
# Connection
# ============================================================

def connect(bridge, db_path: str = DEFAULT_DB_NAME, collection: str = DEFAULT_COLLECTION) -> dict:
    """连接 SQLite 数据库"""
    bridge.db_path = os.path.abspath(db_path).replace("\\", "/")
    bridge.collection = collection
    os.makedirs(os.path.dirname(bridge.db_path) or ".", exist_ok=True)

    # Verify nodbi can connect
    info = get_db_info(bridge)
    logger.info(f"数据库就绪: {bridge.db_path} ({info.get('total_records', '?')} 条)")
    return {"ok": True, "path": bridge.db_path, **info}


def get_db_info(bridge) -> dict:
    """获取数据库信息"""
    if not bridge.db_path:
        return {"connected": False}

    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    r_code = _render(
        "db_info",
        db=db,
        col=col,
    )

    try:
        result = _proc.run_r_json(bridge, r_code)
        if isinstance(result, dict) and result.get("ok") is False:
            return {"connected": False, "error": result.get("error", "")}
        return result
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ============================================================
# Query history
# ============================================================

def get_query_history(bridge) -> pd.DataFrame:
    """获取所有查询历史"""
    if not bridge.db_path:
        return pd.DataFrame()

    tmp_csv = tempfile.mktemp(suffix=".csv")
    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)
    csv_path = _proc._r_escape(tmp_csv.replace(os.sep, "/"))

    r_code = _render(
        "query_history",
        db=db,
        col=col,
        csv_path=csv_path,
    )

    try:
        result = _proc.run_r_json(bridge, r_code)

        if isinstance(result, dict) and result.get("empty"):
            return pd.DataFrame()

        if os.path.exists(tmp_csv):
            df = pd.read_csv(tmp_csv, encoding="utf-8-sig")
            try:
                os.unlink(tmp_csv)
            except Exception:
                pass
            return df

        return pd.DataFrame()

    except Exception as e:
        if os.path.exists(tmp_csv):
            try:
                os.unlink(tmp_csv)
            except Exception:
                pass
        logger.warning(f"获取查询历史失败: {e}")
        return pd.DataFrame()
