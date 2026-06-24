#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract service — orchestrates data extraction and document download.

Extracted from export_tab._worker closures so that business logic
is testable without Qt dependencies.
"""

import logging
from typing import Callable, List, Optional

import pandas as pd

from core.constants import classify_registry

logger = logging.getLogger(__name__)


class ExtractService:
    """Orchestrates extract/export operations via CtrdataBridge."""

    def __init__(self, bridge):
        self.bridge = bridge

    # ================================================================
    # Data extraction with scope filtering
    # ================================================================

    def extract(
        self,
        fields: List[str] = None,
        concepts: List[str] = None,
        deduplicate: bool = True,
        filter_phase: str = "",
        filter_status: str = "",
        filter_date_start: str = "",
        filter_date_end: str = "",
        strict_date: bool = False,
        filter_condition: str = "",
        filter_intervention: str = "",
        filter_register: str = "",
        scope_ids: List[str] = None,
    ) -> pd.DataFrame:
        """
        Extract data with optional scope filtering.

        The scope filter is applied at the R level (before CSV write) for
        performance.  A Python-level fallback with loose ID matching handles
        edge cases (e.g., EUCTR country suffixes).

        Returns filtered DataFrame.
        """
        # When scope_ids is provided, skip R-level deduplication — the
        # cross-register dedup may remove IDs that the scope filter needs,
        # resulting in 0 rows.  Scope filtering already limits records to
        # the user's chosen trials, so whole-database dedup is unnecessary.
        effective_dedup = deduplicate and not scope_ids

        logger.info(
            f"Extract: scope={'current' if scope_ids else 'all'}, "
            f"dedup={effective_dedup}, fields={len(fields or [])}, "
            f"concepts={len(concepts or [])}"
        )

        df = self.bridge.extract_to_dataframe(
            fields=fields if fields else None,
            calculate=concepts if concepts else None,
            deduplicate=effective_dedup,
            filter_phase=filter_phase,
            filter_status=filter_status,
            filter_date_start=filter_date_start,
            filter_date_end=filter_date_end,
            strict_date=strict_date,
            filter_condition=filter_condition,
            filter_intervention=filter_intervention,
            scope_ids=scope_ids,
        )

        # Register filtering — use vectorized startswith for CTGOV2/ISRCTN,
        # classify_registry for EUCTR/CTIS (no simple prefix distinguishable)
        if filter_register and "_id" in df.columns:
            before = len(df)
            id_col = df["_id"].astype(str)
            if filter_register == "CTGOV2":
                df = df[id_col.str.startswith("NCT")]
            elif filter_register == "ISRCTN":
                df = df[id_col.str.startswith("ISRCTN")]
            else:
                df = df[id_col.apply(classify_registry) == filter_register]
            logger.info(f"Register filter ({filter_register}): {before} → {len(df)} rows")

        logger.info(f"Extract complete: {len(df)} rows × {len(df.columns)} cols")
        return df

    # ================================================================
    # Protocol scope resolution
    # ================================================================

    def resolve_protocol_scope(
        self,
        scope_ids: Optional[List[str]],
        scope_choice: str,
        on_log: Optional[Callable[[str, str], None]] = None,
    ) -> List[str]:
        """Resolve effective scope IDs when the Protocol-only filter is active.

        CTGOV2 和 ISRCTN 有 Protocol 文档元数据，get_protocol_trial_ids()
        返回有 Protocol 文档的精确子集；EUCTR/CTIS 无此元数据，"all_registries"
        下需把其在范围内的 ID 整体并入。

        scope_choice:
          - "ctgov_isrctn_only": effective = protocol_ids
          - "all_registries":    effective = dedup(protocol_ids + EUCTR/CTIS IDs)

        scope_ids 为 None 表示全库模式（EUCTR/CTIS 取自 get_all_trial_ids()；
        若后者为空则回退到 protocol_ids 并发 warning）。

        返回去重保序列表；空列表 = 无匹配（调用方应 emit 空 DataFrame）。
        """
        protocol_ids = self.bridge.get_protocol_trial_ids(scope_ids)

        if scope_choice == "ctgov_isrctn_only":
            return list(protocol_ids)

        # "all_registries": 并入 EUCTR/CTIS
        if scope_ids is not None:
            source_ids = scope_ids
        else:
            source_ids = self.bridge.get_all_trial_ids()
            if not source_ids and on_log:
                on_log("warning", "获取全部试验ID失败，仅使用Protocol查询结果")

        euctr_ctis_ids = [
            sid for sid in (source_ids or [])
            if classify_registry(sid) in ("EUCTR", "CTIS")
        ]
        effective_scope = list(dict.fromkeys(protocol_ids + euctr_ctis_ids))

        if on_log:
            on_log(
                "info",
                f"Protocol scope breakdown: {len(protocol_ids)} CTGOV2+ISRCTN, "
                f"{len(euctr_ctis_ids)} EUCTR/CTIS, "
                f"{len(effective_scope)} total",
            )
        return effective_scope

    # ================================================================
    # Document download
    # ================================================================

    def download_documents(
        self,
        trial_ids: list,
        documents_path: str,
        documents_regexp: str = None,
        per_trial_timeout: int = 120,
        on_progress: Callable = None,
    ) -> dict:
        """
        Download documents for filtered trials.

        Returns raw result dict from bridge.
        """
        logger.info(f"Document download: {len(trial_ids)} trials → {documents_path}")
        result = self.bridge.download_documents_for_ids(
            trial_ids=trial_ids,
            documents_path=documents_path,
            documents_regexp=documents_regexp,
            per_trial_timeout=per_trial_timeout,
            callback=on_progress or (lambda c, t, tid, s, detail="": None),
        )
        return result
