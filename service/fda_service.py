#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FDA review document search and download via openFDA API.

Direct search mode — no trial data dependency.
Uses requests to query the openFDA drugsfda endpoint,
flatten results into table rows, and download review PDFs.
"""

import logging
import os
import time
from typing import Callable, Dict, List, Optional

import requests

from core.constants import (
    FDA_API_BASE,
    FDA_API_RATE_LIMIT,
    FDA_REVIEW_DOC_TYPES,
)

logger = logging.getLogger(__name__)


class FdaSearchService:
    """Direct search against openFDA drugsfda endpoint."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._min_interval = FDA_API_RATE_LIMIT if not api_key else 0.06
        self._last_call_time = 0.0
        self._cancel_flag = False

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _rate_limit(self):
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    # ------------------------------------------------------------------
    # Search — build params and query
    # ------------------------------------------------------------------

    def _build_search_params(self, params: dict) -> dict:
        """Build openFDA API query parameters from UI search params.

        UI params dict keys:
            drug_name, date_from, date_to, manufacturer, route,
            application_type, review_priority, submission_class
        """
        search_parts = []
        query_params = {"limit": "100"}

        # Drug name: search generic_name OR brand_name
        drug_name = params.get("drug_name", "").strip()
        if drug_name:
            search_parts.append(
                f"(openfda.generic_name:{drug_name}+openfda.brand_name:{drug_name})"
            )

        # Date range: single-sided supported
        date_from = params.get("date_from", "").strip()
        date_to = params.get("date_to", "").strip()
        if date_from or date_to:
            # Convert YYYY-MM-DD to YYYYMMDD
            from_val = date_from.replace("-", "") if date_from else "*"
            to_val = date_to.replace("-", "") if date_to else "*"
            search_parts.append(
                f"submissions.submission_status_date:[{from_val}+TO+{to_val}]"
            )

        # Advanced filters
        manufacturer = params.get("manufacturer", "").strip()
        if manufacturer:
            search_parts.append(f"openfda.manufacturer_name:{manufacturer}")

        route = params.get("route", "").strip()
        if route:
            search_parts.append(f"openfda.route:{route}")

        pharm_class = params.get("pharm_class", "").strip()
        if pharm_class:
            search_parts.append(f"openfda.pharm_class_epc:{pharm_class}")

        app_type = params.get("application_type", "").strip()
        if app_type:
            search_parts.append(f"openfda.application_number:{app_type}*")

        review_priority = params.get("review_priority", "").strip()
        if review_priority:
            search_parts.append(f"submissions.review_priority:{review_priority}")

        submission_class = params.get("submission_class", "").strip()
        if submission_class:
            search_parts.append(
                f"submissions.submission_class_code:{submission_class}"
            )

        if search_parts:
            query_params["search"] = "+".join(search_parts)

        if self.api_key:
            query_params["api_key"] = self.api_key

        return query_params

    def _build_url(self, query_params: dict, skip: int) -> str:
        """Build full URL manually to preserve + signs in search query.

        requests.get(params=) encodes + as %2B, which breaks openFDA's
        Lucene parser. Manual URL construction keeps + literal.
        """
        from urllib.parse import quote
        parts = []
        for key, val in query_params.items():
            if key == "search":
                # Don't encode + — it's the Lucene AND operator
                parts.append(f"search={val}")
            else:
                parts.append(f"{key}={quote(str(val), safe='')}")
        parts.append(f"skip={skip}")
        return f"{FDA_API_BASE}?{'&'.join(parts)}"

    def search(
        self,
        params: dict,
        skip: int = 0,
        on_cancel: Callable[[], bool] = None,
    ) -> dict:
        """Search openFDA. Returns {rows: [...], total: N}.

        Each row is a flat dict with denormalized fields for table display.
        """
        self._cancel_flag = False
        query_params = self._build_search_params(params)
        url = self._build_url(query_params, skip)

        self._rate_limit()

        try:
            resp = self._session.get(url, timeout=30)
            if resp.status_code == 404:
                return {"rows": [], "total": 0}
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("openFDA search failed: %s", e)
            raise

        total = data.get("meta", {}).get("results", {}).get("total", 0)
        results = data.get("results", [])
        rows = self._flatten_results(results)

        return {"rows": rows, "total": total}

    # ------------------------------------------------------------------
    # Result flattening
    # ------------------------------------------------------------------

    def _flatten_results(self, results: list) -> List[dict]:
        """Flatten nested API response into one row per review document.

        Walks: results[].submissions[].application_docs[]
        Only includes documents whose type matches FDA_REVIEW_DOC_TYPES or "Review".
        """
        rows = []
        review_keywords = [k.lower() for k in FDA_REVIEW_DOC_TYPES]

        for result in results:
            openfda = result.get("openfda", {})
            brand_names = openfda.get("brand_name", [])
            generic_names = openfda.get("generic_name", [])
            app_numbers = openfda.get("application_number", [])
            manufacturers = openfda.get("manufacturer_name", [])

            brand_name = brand_names[0] if brand_names else ""
            generic_name = generic_names[0] if generic_names else ""
            app_number = result.get("application_number", app_numbers[0] if app_numbers else "")
            manufacturer = manufacturers[0] if manufacturers else ""

            for submission in result.get("submissions", []):
                sub_type = submission.get("submission_type", "")
                sub_date = submission.get("submission_status_date", "")

                for doc in submission.get("application_docs", []):
                    doc_type = doc.get("type", "")
                    doc_url = doc.get("url", "")
                    if not doc_url:
                        continue

                    # Only include review documents
                    doc_type_lower = doc_type.lower()
                    is_review = any(kw in doc_type_lower for kw in review_keywords)
                    is_review = is_review or doc_type == "Review"
                    if not is_review:
                        continue

                    rows.append({
                        "brand_name": brand_name,
                        "generic_name": generic_name,
                        "application_number": app_number,
                        "manufacturer_name": manufacturer,
                        "submission_type": sub_type,
                        "submission_status_date": sub_date,
                        "doc_type": doc_type,
                        "doc_url": doc_url,
                    })

        return rows

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_docs(
        self,
        docs: List[dict],
        save_dir: str,
        on_progress: Callable[[int, int, str], None] = None,
        is_cancelled: Callable[[], bool] = None,
    ) -> dict:
        """Download review documents.

        Args:
            docs: List of row dicts (must have doc_url, brand_name, etc.)
            save_dir: Target directory (flat, no subdirectories)
            on_progress: Called with (current, total, filename)
            is_cancelled: Checked before each download

        Returns:
            {"success": [filepaths], "failed": [{url, error, filename}]}
        """
        os.makedirs(save_dir, exist_ok=True)

        # Clean stale .tmp files from previous interrupted runs
        import glob
        for tmp_file in glob.glob(os.path.join(save_dir, "*.tmp")):
            try:
                os.remove(tmp_file)
            except OSError:
                pass

        success = []
        failed = []
        total = len(docs)

        for i, doc in enumerate(docs):
            if is_cancelled and is_cancelled():
                break

            url = doc.get("doc_url", "")

            # Skip HTML TOC pages
            if url.lower().endswith((".html", ".cfm")):
                failed.append({
                    "url": url,
                    "filename": "",
                    "error": "HTML TOC page, not direct PDF",
                })
                continue

            filename = _make_download_filename(
                brand_name=doc.get("brand_name", ""),
                submission_type=doc.get("submission_type", ""),
                date=doc.get("submission_status_date", ""),
                doc_type=doc.get("doc_type", ""),
            )
            filepath = os.path.join(save_dir, filename)

            # Avoid name collision
            if os.path.exists(filepath):
                base, ext = os.path.splitext(filepath)
                n = 2
                while os.path.exists(f"{base}({n}){ext}"):
                    n += 1
                filepath = f"{base}({n}){ext}"

            try:
                if not os.path.exists(filepath):
                    self._rate_limit()
                    resp = self._session.get(url, timeout=120, stream=True)
                    resp.raise_for_status()
                    tmp_path = filepath + ".tmp"
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    os.replace(tmp_path, filepath)

                success.append(filepath)
            except Exception as e:
                failed.append({
                    "url": url,
                    "filename": filename,
                    "error": str(e),
                })

            if on_progress:
                on_progress(i + 1, total, filename)

        return {"success": success, "failed": failed}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_download_filename(
    brand_name: str,
    submission_type: str,
    date: str,
    doc_type: str,
) -> str:
    """Generate filename: {brand_name}_{submission_type}_{date}_{doc_type_cn}.pdf"""
    import re
    # Chinese abbreviation for doc type
    cn_type = FDA_REVIEW_DOC_TYPES.get(doc_type, doc_type.replace(" ", "_"))
    # Sanitize for filesystem
    cn_type = cn_type.replace("/", "_").replace("\\", "_")
    cn_type = re.sub(r'[:*?"<>|]', '', cn_type)

    prefix = brand_name if brand_name else cn_type
    prefix = prefix.replace("/", "_").replace("\\", "_").replace(" ", "_")
    prefix = re.sub(r'[:*?"<>|]', '', prefix)

    return f"{prefix}_{submission_type}_{date}_{cn_type}.pdf"
