#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDA review document matching and download via openFDA API.

Pure Python service — no R dependency. Uses requests to query the
openFDA drugsfda endpoint and download review PDFs.
"""

import logging
import os
import time
from typing import Callable, Dict, List, Optional

import requests

from core.constants import FDA_API_BASE, FDA_API_RATE_LIMIT, FDA_REVIEW_DOC_TYPES

logger = logging.getLogger(__name__)


class FdaMatchService:
    """Matches drug names against openFDA drugsfda endpoint."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._min_interval = FDA_API_RATE_LIMIT if not api_key else 0.06
        self._last_call_time = 0.0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _rate_limit(self):
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    # ------------------------------------------------------------------
    # Drug name matching
    # ------------------------------------------------------------------

    def match_drug_names(
        self,
        drug_names: List[str],
        on_progress: Callable[[int, int, str], None] = None,
        is_cancelled: Callable[[], bool] = None,
    ) -> Dict[str, dict]:
        """Match unique drug names against openFDA API.

        Returns dict mapping drug_name_lower -> match result dict.
        Each result has: {"matched": bool, "review_docs": [...], ...}
        """
        results = {}
        total = len(drug_names)

        for i, drug_name in enumerate(drug_names):
            if is_cancelled and is_cancelled():
                break

            self._rate_limit()

            try:
                result = self._query_openfda(drug_name)
                results[drug_name] = result
            except Exception as e:
                results[drug_name] = {"matched": False, "reason": str(e)}

            if on_progress:
                on_progress(i + 1, total, drug_name)

        return results

    def _query_openfda(self, drug_name: str) -> dict:
        """Query openFDA for a single drug name. Returns match result."""
        params = {"limit": "10"}

        # Try generic_name first, then brand_name
        for search_field in ["openfda.generic_name", "openfda.brand_name"]:
            params["search"] = f"{search_field}:{drug_name}"
            if self.api_key:
                params["api_key"] = self.api_key

            try:
                resp = self._session.get(
                    FDA_API_BASE, params=params, timeout=15
                )
                if resp.status_code == 200:
                    data = resp.json()
                    review_docs = self._extract_review_urls(data)
                    if review_docs:
                        # Collect metadata
                        results = data.get("results", [])
                        brand_names = set()
                        generic_names = set()
                        app_numbers = []
                        for r in results:
                            ofda = r.get("openfda", {})
                            brand_names.update(ofda.get("brand_name", []))
                            generic_names.update(ofda.get("generic_name", []))
                            an = r.get("application_number", "")
                            if an:
                                app_numbers.append(an)

                        return {
                            "matched": True,
                            "review_docs": review_docs,
                            "brand_names": sorted(brand_names),
                            "generic_names": sorted(generic_names),
                            "application_numbers": app_numbers,
                        }
                elif resp.status_code == 404:
                    continue  # Not found, try next field
                else:
                    logger.warning(
                        "openFDA returned %d for %s", resp.status_code, drug_name
                    )
            except requests.RequestException as e:
                logger.warning("openFDA request failed for %s: %s", drug_name, e)

        return {"matched": False, "reason": "未在FDA数据库中找到"}

    def _extract_review_urls(self, api_response: dict) -> List[dict]:
        """Extract review document URLs from openFDA response.

        Walks: results[].submissions[].application_docs[]
        Filters for review document types defined in FDA_REVIEW_DOC_TYPES.
        """
        docs = []
        results = api_response.get("results", [])
        review_type_keywords = [k.lower() for k in FDA_REVIEW_DOC_TYPES]

        for result in results:
            submissions = result.get("submissions", [])
            for submission in submissions:
                app_docs = submission.get("application_docs", [])
                sub_type = submission.get("submission_type", "")
                sub_status = submission.get("submission_status", "")
                sub_date = submission.get("submission_status_date", "")

                for doc in app_docs:
                    doc_type = doc.get("type", "")
                    url = doc.get("url", "")

                    if not url:
                        continue

                    # Include review docs and summary reviews
                    doc_type_lower = doc_type.lower()
                    is_review = any(
                        kw in doc_type_lower for kw in review_type_keywords
                    )
                    # Also include the general "Review" type (links to TOC page)
                    is_review = is_review or doc_type == "Review"

                    if is_review:
                        docs.append({
                            "url": url,
                            "doc_type": doc_type,
                            "submission_type": sub_type,
                            "submission_status": sub_status,
                            "submission_date": sub_date,
                        })

        return docs

    # ------------------------------------------------------------------
    # PDF download
    # ------------------------------------------------------------------

    def download_review_docs(
        self,
        matched_results: Dict[str, dict],
        save_dir: str,
        on_progress: Callable[[int, int, str], None] = None,
        is_cancelled: Callable[[], bool] = None,
    ) -> dict:
        """Download all matched FDA review PDFs.

        Saves to {save_dir}/{drug_name}/ subdirectories.
        Returns {"success": [filepaths], "failed": {url: error}}.
        """
        os.makedirs(save_dir, exist_ok=True)
        success = []
        failed = {}

        # Collect all downloadable docs (exclude TOC pages)
        all_docs = []
        for drug_name, result in matched_results.items():
            if not result.get("matched") or not result.get("review_docs"):
                continue
            for doc in result["review_docs"]:
                url = doc.get("url", "")
                if not url:
                    continue
                # Skip HTML/CFM TOC pages — only download PDFs
                if url.lower().endswith((".html", ".cfm")):
                    continue
                all_docs.append((drug_name, doc))

        total = len(all_docs)

        for i, (drug_name, doc) in enumerate(all_docs):
            if is_cancelled and is_cancelled():
                break

            url = doc.get("url", "")
            doc_type = doc.get("doc_type", "review")
            sub_date = doc.get("submission_date", "")

            try:
                drug_dir = os.path.join(save_dir, _safe_dirname(drug_name))
                os.makedirs(drug_dir, exist_ok=True)

                filename = _make_filename(doc_type, sub_date)
                filepath = os.path.join(drug_dir, filename)

                if not os.path.exists(filepath):
                    resp = self._session.get(url, timeout=120, stream=True)
                    resp.raise_for_status()
                    tmp_path = filepath + ".tmp"
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    os.replace(tmp_path, filepath)

                success.append(filepath)

            except Exception as e:
                failed[url] = str(e)

            if on_progress:
                on_progress(i + 1, total, drug_name)

        return {"success": success, "failed": failed}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _safe_dirname(drug_name: str) -> str:
    """Make a filesystem-safe directory name from a drug name."""
    return drug_name.replace(" ", "_").replace("/", "_").replace("\\", "_")


def _make_filename(doc_type: str, date_str: str) -> str:
    """Generate a descriptive PDF filename from doc type and date."""
    safe_type = doc_type.replace(" ", "_").replace("(", "").replace(")", "")
    if date_str:
        # date_str is YYYYMMDD, format as YYYY-MM-DD
        if len(date_str) == 8 and date_str.isdigit():
            date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            date_fmt = date_str
        return f"{safe_type}_{date_fmt}.pdf"
    return f"{safe_type}.pdf"
