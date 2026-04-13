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
            filter_condition=filter_condition,
            filter_intervention=filter_intervention,
            scope_ids=scope_ids,
        )

        # Register filtering by _id prefix
        if filter_register and "_id" in df.columns:
            prefix = _register_prefix(filter_register)
            before = len(df)
            df = df[df["_id"].astype(str).str.startswith(prefix)]
            logger.info(f"Register filter ({filter_register}): {before} → {len(df)} rows")

        logger.info(f"Extract complete: {len(df)} rows × {len(df.columns)} cols")
        return df

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
            callback=on_progress or (lambda c, t, tid, s, err=None: None),
        )
        return result


# Register key → _id prefix mapping
_REGISTER_PREFIXES = {
    "CTGOV2": "NCT",
    "EUCTR": "EUCTR",
    "ISRCTN": "ISRCTN",
    "CTIS": "EU",
}


def _register_prefix(register_key: str) -> str:
    """Return the _id prefix for a register key (e.g. 'CTGOV2' → 'NCT')."""
    return _REGISTER_PREFIXES.get(register_key, register_key)
