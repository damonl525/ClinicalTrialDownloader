#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document downloads — documents module for CtrdataBridge.

Handles: download_documents_for_ids() with resume/checkpoint logic,
download_one_trial_doc() (in process module), resume file management.
"""

import hashlib
import os
import json
import logging
import re
import shutil
from typing import Any, Callable, Dict, List

from core.exceptions import DatabaseError, CtrdataError, DownloadTimeoutError
from ctrdata import process as _proc
from ctrdata.process import download_one_trial_doc  # noqa: F401

logger = logging.getLogger(__name__)


# ============================================================
# Flatten trial subdirectories into parent directory
# ============================================================

def _flatten_trial_docs(documents_path: str, trial_id: str) -> int:
    """Move files from trial_id/ subdirectory to parent as trial_id_filename.

    E.g. documents_path/NCT06915701/Prot_000.pdf
         -> documents_path/NCT06915701_Prot_000.pdf

    Returns:
        Number of files skipped (already existed at destination).
    """
    trial_dir = os.path.join(documents_path, trial_id)
    if not os.path.isdir(trial_dir):
        return 0

    skipped = 0
    for fname in os.listdir(trial_dir):
        src = os.path.join(trial_dir, fname)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(documents_path, f"{trial_id}_{fname}")
        # Skip if destination already exists
        if os.path.exists(dst):
            logger.info("文件已存在，跳过: %s", os.path.basename(dst))
            skipped += 1
            try:
                os.unlink(src)
            except OSError:
                pass
            continue
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

    if skipped:
        logger.info("Trial %s: 跳过 %d 个已存在文件", trial_id, skipped)

    return skipped


# ============================================================
# Resume/checkpoint helpers
# ============================================================

def _get_resume_file(bridge, documents_path: str) -> str:
    """Get the checkpoint file path scoped to database + download directory."""
    db_basename = os.path.splitext(os.path.basename(bridge.db_path))[0]
    db_dir = os.path.dirname(bridge.db_path) or "."
    path_slug = hashlib.md5(os.path.abspath(documents_path).encode()).hexdigest()[:8]
    return os.path.join(db_dir, f"{db_basename}_{path_slug}_doc_resume.json")


def _session_hash(trial_ids, documents_path: str = "") -> str:
    """Compute a session hash from trial IDs + download path for resume isolation."""
    sorted_ids = sorted(str(tid) for tid in trial_ids)
    payload = ",".join(sorted_ids) + "|" + os.path.abspath(documents_path)
    return hashlib.md5(payload.encode()).hexdigest()[:16]


def _trial_has_docs(documents_path: str, trial_id: str) -> bool:
    """Check if a trial has actual document files on disk."""
    trial_dir = os.path.join(documents_path, trial_id)
    if os.path.isdir(trial_dir) and os.listdir(trial_dir):
        return True
    # Also check for flattened files (trial_id_ prefix)
    if os.path.isdir(documents_path):
        prefix = f"{trial_id}_"
        for fname in os.listdir(documents_path):
            if fname.startswith(prefix):
                return True
    return False


def _cleanup_trial_partial_docs(documents_path: str, trial_id: str) -> int:
    """Remove partial documents for a trial so it can be fully re-downloaded.

    Interrupted downloads (timeout/cancel) may leave truncated files that ctrdata
    will skip on re-download (it does not overwrite existing files). Deleting them
    forces a clean re-download. Removes both the trial_id/ subdirectory and
    flattened trial_id_* files. Returns the number of files removed.
    """
    removed = 0
    trial_dir = os.path.join(documents_path, trial_id)
    if os.path.isdir(trial_dir):
        for fname in os.listdir(trial_dir):
            try:
                os.unlink(os.path.join(trial_dir, fname))
                removed += 1
            except OSError:
                pass
        try:
            os.rmdir(trial_dir)
        except OSError:
            pass
    if os.path.isdir(documents_path):
        prefix = f"{trial_id}_"
        for fname in os.listdir(documents_path):
            if fname.startswith(prefix):
                try:
                    os.unlink(os.path.join(documents_path, fname))
                    removed += 1
                except OSError:
                    pass
    return removed


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

    current_session = _session_hash(trial_ids, documents_path)
    if resume_data.get("session") and resume_data["session"] != current_session:
        _cleanup_resume(bridge, resume_file)
        resume_data = {"completed": [], "failed": {}, "skipped_explicitly": [], "in_progress": [], "total": 0, "session": None}

    # Validate resume: a trial is only "already done" if docs exist on disk
    resume_completed_raw = set(resume_data.get("completed", []))
    already_done = {tid for tid in resume_completed_raw if _trial_has_docs(documents_path, tid)}
    stale_done = resume_completed_raw - already_done
    if stale_done:
        logger.info(f"Resume: {len(stale_done)} trials in resume have no docs on disk, re-downloading")

    skipped_explicit = set(resume_data.get("skipped_explicitly", []))
    in_progress_set = set(resume_data.get("in_progress", []))
    remaining = [tid for tid in trial_ids if tid not in already_done and tid not in skipped_explicit]

    # 中断的 trial（in_progress）：重下前清理部分文件，避免 ctrdata 跳过残缺文件
    interrupted = in_progress_set & set(remaining)
    for tid in interrupted:
        removed = _cleanup_trial_partial_docs(documents_path, tid)
        if removed:
            logger.info(f"Resume: trial {tid} 中断残留，清理 {removed} 个部分文件后重新下载")

    if not remaining:
        _cleanup_resume(bridge, resume_file)
        return {
            "ok": True,
            "success": [],
            "failed": {},
            "skipped": {},
            "skipped_existing": list(already_done),
            "total": len(trial_ids),
        }

    total_to_process = len(remaining)
    # P1-1: 按注册中心分流——CTGOV2 走单 session batch 省 per-trial 进程启动税
    # （100 trial 省 ~10 分钟）。EUCTR/CTIS 需特殊参数 + 超时隔离，ISRCTN 走 HTTP，
    # 三者保持 per-trial。batch 模板（download_batch_docs.R）用通用 queryterm，
    # 不支持 EUCTR/CTIS 特殊参数，故 batch 只适用 CTGOV2。
    from core.constants import classify_registry
    ctgov2_remaining = [t for t in remaining if classify_registry(t) == "CTGOV2"]
    other_remaining = [t for t in remaining if classify_registry(t) != "CTGOV2"]

    runtime_completed = []
    runtime_failed = {}
    resume_completed = list(already_done)  # For checkpoint only
    runtime_skipped_explicit = list(resume_data.get("skipped_explicitly", []))
    runtime_in_progress = set(in_progress_set & set(remaining))

    def _save_runtime_resume():
        _save_resume(
            bridge,
            resume_file,
            resume_completed + runtime_completed,
            runtime_failed,
            len(trial_ids),
            skipped_explicitly=runtime_skipped_explicit,
            session=current_session,
            in_progress=list(runtime_in_progress),
        )

    # ── CTGOV2 batch 段：单 R session 处理所有 CTGOV2 trial（省进程税）──
    if ctgov2_remaining and not bridge._cancelled:
        from ctrdata.process import download_batch_docs as _batch_docs

        def _ctgov2_progress(i, total, tid, status, error):
            # i 是 batch 内 1-based 索引；CTGOV2 先跑，即全局进度索引。
            # R 模板对每个 trial 发两条 PROGRESS：start（R line 12）+ ok/error（R line 32）。
            # ok 但 n=0（无文档）的 trial：与 per-trial 路径（documents.py:303）一致，标记 failed。
            if callback:
                callback(i, total_to_process, tid, status, error)
            if status == "start":
                return
            if status == "ok":
                _flatten_trial_docs(documents_path, tid)
                if _trial_has_docs(documents_path, tid):
                    if tid not in runtime_completed:
                        runtime_completed.append(tid)
                    _save_runtime_resume()
                else:
                    runtime_failed[tid] = "No documents found for this trial"
                    _save_runtime_resume()
            elif status == "error":
                runtime_failed[tid] = error or "unknown"
                _save_runtime_resume()

        try:
            _batch_docs(
                bridge, ctgov2_remaining, documents_path, documents_regexp,
                total_timeout=timeout_total,
                progress_callback=_ctgov2_progress,
            )
        except (CtrdataError, DownloadTimeoutError) as e:
            logger.warning(f"CTGOV2 batch failed: {e}; marking unfinished as failed")
            for tid in ctgov2_remaining:
                if tid not in runtime_completed:
                    runtime_failed[tid] = f"TIMEOUT({timeout_total}s) batch: {e}"
            _save_runtime_resume()

    for i, tid in enumerate(other_remaining, 1):
        global_i = len(ctgov2_remaining) + i  # CTGOV2 batch 已占前 N 个进度位
        # Check cancel flag between trials
        if bridge._cancelled:
            logger.info(f"Download cancelled after {global_i-1}/{total_to_process} trials")
            break

        if callback:
            callback(global_i, total_to_process, tid, "start", None)

        runtime_in_progress.add(tid)
        _save_runtime_resume()

        try:
            result = download_one_trial_doc(
                bridge, tid, documents_path, documents_regexp, per_trial_timeout
            )
            if result.get("ok"):
                file_skips = _flatten_trial_docs(documents_path, tid)
                if _trial_has_docs(documents_path, tid):
                    runtime_completed.append(tid)
                    if callback:
                        callback(global_i, total_to_process, tid, "ok", None)
                        if file_skips:
                            callback(global_i, total_to_process, tid, "file_skip", str(file_skips))
                else:
                    runtime_failed[tid] = "No documents found for this trial"
                    if callback:
                        callback(global_i, total_to_process, tid, "skip", "No documents found")
            else:
                err = result.get("error", "unknown")
                runtime_failed[tid] = err
                if callback:
                    callback(global_i, total_to_process, tid, "error", err)

        except CtrdataError as e:
            err_msg = f"TIMEOUT({per_trial_timeout}s): {e}"
            runtime_failed[tid] = err_msg
            if callback:
                callback(global_i, total_to_process, tid, "skip", err_msg)

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
        "skipped_existing": list(already_done),
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

    current_session = _session_hash(trial_ids, documents_path)
    if resume_data.get("session") and resume_data["session"] != current_session:
        _cleanup_resume(bridge, resume_file)
        resume_data = {"completed": [], "failed": {}, "skipped_explicitly": [], "in_progress": [], "total": 0, "session": None}

    resume_completed_raw = set(resume_data.get("completed", []))
    already_done = {tid for tid in resume_completed_raw if _trial_has_docs(documents_path, tid)}
    skipped_explicit = set(resume_data.get("skipped_explicitly", []))
    remaining = [tid for tid in trial_ids if tid not in already_done and tid not in skipped_explicit]

    if not remaining:
        return {
            "ok": True,
            "success": [tid for tid in already_done if tid in set(str(t) for t in trial_ids)],
            "failed": {},
            "skipped": {},
            "total": len(trial_ids),
        }

    runtime_completed = list(already_done)

    def _on_progress(i, total, tid, status, error):
        if callback:
            callback(i, total, tid, status, error)
        if status == "ok":
            _flatten_trial_docs(documents_path, tid)
            if tid not in runtime_completed and _trial_has_docs(documents_path, tid):
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
        "skipped_existing": list(already_done),
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
