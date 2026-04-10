#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract service — orchestrates data extraction and document download.

Extracted from export_tab._worker closures so that business logic
is testable without Qt dependencies.
"""

import logging
from typing import Callable, List, Optional, Set

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
        scope_ids: Set[str] = None,
    ) -> pd.DataFrame:
        """
        Extract data with optional scope filtering.

        The scope filter normalizes trial IDs for cross-register matching
        (e.g., EUCTR country suffixes, NCT version suffixes).

        Returns filtered DataFrame.
        """
        df = self.bridge.extract_to_dataframe(
            fields=fields if fields else None,
            calculate=concepts if concepts else None,
            deduplicate=deduplicate,
            filter_phase=filter_phase,
            filter_status=filter_status,
            filter_date_start=filter_date_start,
            filter_date_end=filter_date_end,
            filter_condition=filter_condition,
            filter_intervention=filter_intervention,
        )

        # Register filtering by _id prefix
        if filter_register and "_id" in df.columns:
            prefix = _register_prefix(filter_register)
            df = df[df["_id"].astype(str).str.startswith(prefix)]

        # Scope filtering — cross-register ID normalization
        if scope_ids and "_id" in df.columns:
            scope_set = set(str(sid).strip() for sid in scope_ids)
            df_ids = df["_id"].astype(str).str.strip()

            # Step 1: exact match
            mask = df_ids.isin(scope_set)

            # Step 2: loose match for unmatched IDs
            if mask.sum() < len(scope_set):
                loose_scope = set(_norm_id(s) for s in scope_set)
                loose_ids = df_ids.apply(_norm_id)
                loose_mask = loose_ids.isin(loose_scope)
                mask = mask | loose_mask

            df = df[mask]

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
        result = self.bridge.download_documents_for_ids(
            trial_ids=trial_ids,
            documents_path=documents_path,
            documents_regexp=documents_regexp,
            per_trial_timeout=per_trial_timeout,
            callback=on_progress or (lambda c, t, tid, s, err=None: None),
        )
        return result


def _norm_id(tid: str) -> str:
    """Normalize trial ID for loose cross-register matching.

    - EUCTR: strip trailing country code (e.g., "EUCTR-2023-123456-DE" → "EUCTR-2023-123456")
    - NCT: strip version suffix (e.g., "NCT01234567-Phase2" → "NCT01234567")
    """
    tid = str(tid).strip()
    if tid.startswith("EUCTR"):
        parts = tid.rsplit("-", 1)
        if len(parts) > 1 and len(parts[-1]) == 2:
            return parts[0]
    if tid.startswith("NCT") and "-" in tid:
        return tid.split("-")[0]
    return tid


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
