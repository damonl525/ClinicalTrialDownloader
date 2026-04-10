#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search facade — search submodule for ctrdata package.

Delegates to search_query and search_download submodules.
Kept for backward compatibility; new code should import from submodules directly.
"""

from ctrdata.search_query import generate_queries, count_trials, parse_query_url
from ctrdata.search_download import (
    load_into_db, load_by_trial_id, update_last_query, scan_document_availability,
)
from ctrdata.search_query import find_synonyms, open_in_browser

__all__ = [
    "generate_queries",
    "count_trials",
    "parse_query_url",
    "load_into_db",
    "load_by_trial_id",
    "update_last_query",
    "scan_document_availability",
    "find_synonyms",
    "open_in_browser",
]
