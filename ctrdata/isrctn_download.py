#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISRCTN direct document download — bypasses ctrdata's R-based download.

Uses ISRCTN's public XML API to obtain file download URLs, then downloads
directly via Python urllib. No R, no chromote dependency.
"""

import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_ISRCTN_NS = {"isrctn": "http://www.67bricks.com/isrctn"}
_API_BASE = "https://www.isrctn.com/api/trial/{isrctn_id}/format/default"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _normalize_isrctn_id(trial_id: str) -> str:
    """Strip ISRCTN prefix, return numeric-only ID for API calls."""
    if trial_id.upper().startswith("ISRCTN"):
        return trial_id[6:]
    return trial_id


def fetch_isrctn_file_list(trial_id: str, timeout: int = 15) -> List[Dict]:
    """Fetch file metadata from ISRCTN XML API.

    Returns list of dicts with keys: name, description, url, mime_type, size, md5.
    """
    numeric_id = _normalize_isrctn_id(trial_id)
    url = _API_BASE.format(isrctn_id=numeric_id)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/xml"},
    )

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = resp.read()
    except urllib.error.HTTPError as e:
        logger.warning(f"ISRCTN API HTTP {e.code} for trial {trial_id}")
        return []
    except Exception as e:
        logger.warning(f"ISRCTN API error for trial {trial_id}: {e}")
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        logger.warning(f"ISRCTN XML parse error for trial {trial_id}: {e}")
        return []

    files = []
    for af in root.findall(".//isrctn:attachedFile", _ISRCTN_NS):
        dl_url = af.get("downloadUrl", "")
        if not dl_url:
            continue

        def _text(tag):
            el = af.find(f"isrctn:{tag}", _ISRCTN_NS)
            return el.text if el is not None and el.text else ""

        files.append({
            "name": _text("name"),
            "description": _text("description"),
            "url": dl_url,
            "mime_type": _text("mimeType"),
            "size": _text("length"),
            "md5": _text("md5sum"),
        })

    return files


def download_isrctn_trial_docs(
    trial_id: str,
    documents_path: str,
    documents_regexp: Optional[str] = None,
    timeout: int = 120,
) -> Dict:
    """Download documents for a single ISRCTN trial via direct HTTP.

    Args:
        trial_id: ISRCTN trial ID (with or without ISRCTN prefix)
        documents_path: Directory to save documents
        documents_regexp: Optional regex to filter document filenames
        timeout: Download timeout per file in seconds

    Returns:
        {"ok": bool, "n": int, "error": str, "files": list}
    """
    import os

    files = fetch_isrctn_file_list(trial_id, timeout=15)
    if not files:
        return {
            "ok": False,
            "n": 0,
            "error": "No files found on ISRCTN for this trial",
            "files": [],
        }

    # Filter by regexp if provided
    if documents_regexp:
        pattern = re.compile(documents_regexp, re.IGNORECASE)
        matched = [
            f for f in files
            if pattern.search(f["name"]) or pattern.search(f["description"])
        ]
        if not matched:
            return {
                "ok": False,
                "n": 0,
                "error": f"No files match regexp '{documents_regexp}'",
                "files": [],
            }
        files = matched

    downloaded = []
    errors = []

    for f_info in files:
        # Use trial_id_filename format for consistency with flattened CTGOV2 files
        raw_name = f_info["name"]
        filename = f"{trial_id}_{re.sub(r'[<>:\"/\\\\|?*]', '_', raw_name)}"
        dest = os.path.join(documents_path, filename)

        if os.path.exists(dest):
            logger.info("文件已存在，跳过: %s", filename)
            downloaded.append({"name": filename, "status": "skipped_exists"})
            continue

        try:
            req = urllib.request.Request(
                f_info["url"],
                headers={"User-Agent": _USER_AGENT},
            )
            resp = urllib.request.urlopen(req, timeout=timeout)
            content = resp.read()

            # Verify we got the expected content
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type and not filename.endswith(".html"):
                errors.append(f"{filename}: got HTML instead of expected file")
                continue

            with open(dest, "wb") as f:
                f.write(content)

            downloaded.append({"name": filename, "status": "ok", "bytes": len(content)})
            logger.info("Downloaded: %s (%d bytes)", filename, len(content))

        except Exception as e:
            errors.append(f"{filename}: {e}")
            logger.warning("Failed to download %s: %s", filename, e)

    if downloaded:
        return {
            "ok": True,
            "n": len(downloaded),
            "error": "; ".join(errors) if errors else "",
            "files": downloaded,
        }

    return {
        "ok": False,
        "n": 0,
        "error": "; ".join(errors) if errors else "Download failed",
        "files": [],
    }
