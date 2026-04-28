#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document downloads — documents module for CtrdataBridge.

Handles: download_documents_for_ids() with resume/checkpoint logic,
download_one_trial_doc() (in process module), resume file management.
"""

import os
import json
import logging
import shutil
from typing import Any, Callable, Dict, List

from core.exceptions import DatabaseError, CtrdataError
from ctrdata import process as _proc
from ctrdata.process import download_one_trial_doc  # noqa: F401

logger = logging.getLogger(__name__)


# ============================================================
# Flatten trial subdirectories into parent directory
# ============================================================

def _flatten_trial_docs(documents_path: str, trial_id: str):
    """Move files from trial_id/ subdirectory to parent as trial_id_filename.

    E.g. documents_path/NCT06915701/Prot_000.pdf
         → documents_path/NCT06915701_Prot_000.pdf
    """
    trial_dir = os.path.join(documents_path, trial_id)
    if not os.path.isdir(trial_dir):
        return

    for fname in os.listdir(trial_dir):
        src = os.path.join(trial_dir, fname)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(documents_path, f"{trial_id}_{fname}")
        # Handle name collision by appending a counter
        if os.path.exists(dst):
            base, ext = os.path.splitext(fname)
            n = 1
            while os.path.exists(os.path.join(documents_path, f"{trial_id}_{base}_{n}{ext}")):
                n += 1
            dst = os.path.join(documents_path, f"{trial_id}_{base}_{n}{ext}")
        try:
            shutil.move(src, dst)
        except OSError as e:
            logger.warning(f"Failed to flatten {src}: {e}")

    # Remove empty trial directory
    try:
        remaining = os.listdir(trial_dir)
        if not remaining:
            os.rmdir(trial_dir)
    except OSError:
        pass


# ============================================================
# Resume/checkpoint helpers
# ============================================================

def _get_resume_file(bridge, documents_path: str) -> str:
    """Get the checkpoint file path for a documents directory."""
    db_basename = os.path.splitext(os.path.basename(bridge.db_path))[0]
    db_dir = os.path.dirname(bridge.db_path) or "."
    return os.path.join(db_dir, f"{db_basename}_doc_resume.json")


def _session_hash(trial_ids) -> str:
    """Compute a session hash from sorted trial IDs for resume isolation."""
    import hashlib

    sorted_ids = sorted(str(tid) for tid in trial_ids)
    return hashlib.md5(",".join(sorted_ids).encode()).hexdigest()[:16]


def _load_resume(bridge, resume_file: str) -> dict:
    """Load checkpoint data from file."""
    if not os.path.exists(resume_file):
        return {"completed": [], "failed": {}, "skipped_explicitly": [], "in_progress": [], "total": 0, "session": None}
    try:
        with open(resume_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "completed": list(data.get("completed", [])),
            "failed": dict(data.get("failed", {})),
            "skipped_explicitly": list(data.get("skipped_explicitly", [])),
            "in_progress": list(data.get("in_progress", [])),
            "total": data.get("total", 0),
            "session": data.get("session", None),
        }
    except Exception:
        return {"completed": [], "failed": {}, "skipped_explicitly": [], "in_progress": [], "total": 0, "session": None}


def _save_resume(
    bridge,
    resume_file: str,
    completed: list,
    failed: dict,
    total: int,
    skipped_explicitly: list = None,
    session: str = None,
    in_progress: list = None,
):
    """Atomically write checkpoint file."""
    data = {
        "completed": completed,
        "failed": failed,
        "total": total,
        "skipped_explicitly": skipped_explicitly or [],
        "in_progress": in_progress or [],
        "session": session or "",
    }
    tmp_file = resume_file + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_file, resume_file)


def _cleanup_resume(bridge, resume_file: str):
    """Delete checkpoint file."""
    try:
        if os.path.exists(resume_file):
            os.unlink(resume_file)
    except Exception:
        pass


# ============================================================
# Batch document download with resume
# ============================================================

def download_documents_for_ids(
    bridge,
    trial_ids: List[str],
    documents_path: str,
    documents_regexp: str = None,
    timeout_total: int = 86400,
    per_trial_timeout: int = 180,
    callback: Callable = None,
) -> Dict[str, Any]:
    """
    为指定的 trial ID 列表下载文档。

    Through a Python-side loop calling ctrLoadQueryIntoDb(queryterm=trial_id)
    per trial. Supports global timeout, per-trial timeout skip, resume,
    and progress callbacks.
    """
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")
    if not trial_ids:
        return {"ok": True, "success": [], "failed": {}, "skipped": {}, "total": 0}

    os.makedirs(documents_path, exist_ok=True)

    resume_file = _get_resume_file(bridge, documents_path)
    resume_data = _load_resume(bridge, resume_file)

    current_session = _session_hash(trial_ids)
    if resume_data.get("session") and resume_data["session"] != current_session:
        _cleanup_resume(bridge, resume_file)
        resume_data = {"completed": [], "failed": {}, "skipped_explicitly": [], "in_progress": [], "total": 0, "session": None}

    already_done = set(resume_data.get("completed", []))
    skipped_explicit = set(resume_data.get("skipped_explicitly", []))
    in_progress_set = set(resume_data.get("in_progress", []))
    remaining = [tid for tid in trial_ids if tid not in already_done and tid not in skipped_explicit]

    if not remaining:
        requested_set = set(str(tid) for tid in trial_ids)
        return {
            "ok": True,
            "success": [tid for tid in already_done if tid in requested_set],
            "failed": {},
            "skipped": {},
            "total": len(trial_ids),
        }

    total_to_process = len(remaining)
    runtime_completed = list(already_done)
    runtime_failed = dict(resume_data.get("failed", {}))
    runtime_skipped_explicit = list(resume_data.get("skipped_explicitly", []))
    runtime_in_progress = set(in_progress_set & set(remaining))

    def _save_runtime_resume():
        _save_resume(
            bridge,
            resume_file,
            runtime_completed,
            runtime_failed,
            len(trial_ids),
            skipped_explicitly=runtime_skipped_explicit,
            session=current_session,
            in_progress=list(runtime_in_progress),
        )

    for i, tid in enumerate(remaining, 1):
        if callback:
            callback(i, total_to_process, tid, "start", None)

        runtime_in_progress.add(tid)
        _save_runtime_resume()

        try:
            result = download_one_trial_doc(
                bridge, tid, documents_path, documents_regexp, per_trial_timeout
            )
            if result.get("ok"):
                _flatten_trial_docs(documents_path, tid)
                runtime_completed.append(tid)
                if callback:
                    callback(i, total_to_process, tid, "ok", None)
            else:
                err = result.get("error", "unknown")
                runtime_failed[tid] = err
                if callback:
                    callback(i, total_to_process, tid, "error", err)

        except CtrdataError as e:
            err_msg = f"TIMEOUT({per_trial_timeout}s): {e}"
            runtime_failed[tid] = err_msg
            if callback:
                callback(i, total_to_process, tid, "skip", err_msg)

        runtime_in_progress.discard(tid)
        _save_runtime_resume()

    skipped = {}
    failed = {}
    for tid, err in runtime_failed.items():
        if "TIMEOUT" in str(err):
            skipped[tid] = err
        else:
            failed[tid] = err

    if not failed and not skipped:
        _cleanup_resume(bridge, resume_file)

    return {
        "ok": True,
        "success": list(runtime_completed),
        "failed": failed,
        "skipped": skipped,
        "total": len(trial_ids),
    }


# ============================================================
# Batch document download with single R session + resume
# ============================================================

def download_documents_batch(
    bridge,
    trial_ids: list,
    documents_path: str,
    documents_regexp: str = None,
    timeout_total: int = 7200,
    per_trial_timeout: int = 180,
    callback: Callable = None,
) -> dict:
    """Download documents using a single R batch session with resume support.

    Deprecated: use download_documents_for_ids() for per-trial timeout isolation.
    """
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")
    if not trial_ids:
        return {"ok": True, "success": [], "failed": {}, "skipped": {}, "total": 0}

    os.makedirs(documents_path, exist_ok=True)

    resume_file = _get_resume_file(bridge, documents_path)
    resume_data = _load_resume(bridge, resume_file)

    current_session = _session_hash(trial_ids)
    if resume_data.get("session") and resume_data["session"] != current_session:
        _cleanup_resume(bridge, resume_file)
        resume_data = {"completed": [], "failed": {}, "skipped_explicitly": [], "in_progress": [], "total": 0, "session": None}

    already_done = set(resume_data.get("completed", []))
    skipped_explicit = set(resume_data.get("skipped_explicitly", []))
    remaining = [tid for tid in trial_ids if tid not in already_done and tid not in skipped_explicit]

    if not remaining:
        requested_set = set(str(tid) for tid in trial_ids)
        return {
            "ok": True,
            "success": [tid for tid in already_done if tid in requested_set],
            "failed": {},
            "skipped": {},
            "total": len(trial_ids),
        }

    runtime_completed = list(already_done)

    def _on_progress(i, total, tid, status, error):
        if callback:
            callback(i, total, tid, status, error)
        # Update resume after each successful trial
        if status == "ok" and tid not in runtime_completed:
            runtime_completed.append(tid)
            _save_resume(
                bridge, resume_file, runtime_completed,
                resume_data.get("failed", {}), len(trial_ids),
                skipped_explicitly=list(skipped_explicit),
                session=current_session,
            )

    from ctrdata.process import download_batch_docs as _batch
    results = _batch(
        bridge, remaining, documents_path, documents_regexp,
        total_timeout=timeout_total,
        progress_callback=_on_progress,
    )

    # Aggregate results
    success = list(runtime_completed)
    failed = {}
    for r in results:
        tid = r.get("trial_id", "")
        if r.get("ok"):
            if tid not in success:
                success.append(tid)
        else:
            err = r.get("error", "unknown")
            failed[tid] = err

    if not failed:
        _cleanup_resume(bridge, resume_file)

    return {
        "ok": True,
        "success": success,
        "failed": failed,
        "skipped": {},
        "total": len(trial_ids),
    }


# ============================================================
# Resume control
# ============================================================

def clear_resume(bridge, documents_path: str = None):
    """Clear the resume file to start a fresh download session."""
    resume_file = _get_resume_file(bridge, documents_path or "")
    _cleanup_resume(bridge, resume_file)


def mark_trial_skipped(bridge, trial_id: str, documents_path: str):
    """Mark a trial as explicitly skipped in the resume file."""
    resume_file = _get_resume_file(bridge, documents_path)
    resume_data = _load_resume(bridge, resume_file)
    skipped = list(resume_data.get("skipped_explicitly", []))
    if trial_id not in skipped:
        skipped.append(trial_id)
    in_progress = [t for t in resume_data.get("in_progress", []) if t != trial_id]
    _save_resume(
        bridge,
        resume_file,
        resume_data.get("completed", []),
        resume_data.get("failed", {}),
        resume_data.get("total", 0),
        skipped_explicitly=skipped,
        session=resume_data.get("session"),
        in_progress=in_progress,
    )
