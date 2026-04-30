#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R subprocess management — process submodule for ctrdata package.

Re-exports environment utilities from process_env for backward compatibility.
Provides: run_r(), run_r_json(), run_r_streaming(), download_one_trial_doc(),
cleanup_temp_files().
"""

# Re-export environment utilities for backward compatibility
from ctrdata.process_env import (
    _r_escape,
    _validate_r_input,
    _translate_r_error,
    _find_rscript,
    check_r_environment,
)

import os
import time
import tempfile
import subprocess
import logging
import queue as queue_mod
import threading
from typing import Any, Callable, Optional

from core.exceptions import CtrdataError, DownloadTimeoutError
from ctrdata.template_loader import render as _render

logger = logging.getLogger(__name__)


# ============================================================
# R execution helpers
# ============================================================

def run_r(
    bridge,
    r_code: str,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """Execute R code via temp .R file, return CompletedProcess."""
    wrapped = (
        "suppressMessages({\n"
        "  library(jsonlite)\n"
        "  library(nodbi)\n"
        "  library(ctrdata)\n"
        "})\n"
        "tryCatch({\n" + r_code + "\n"
        "}, error = function(e) {\n"
        "  cat(jsonlite::toJSON(list(\n"
        "    ok = FALSE,\n"
        "    error = as.character(e$message)\n"
        "  ), auto_unbox=TRUE))\n"
        "})\n"
    )

    tmp_r = tempfile.NamedTemporaryFile(
        mode="w", suffix=".R", delete=False, encoding="utf-8"
    )
    try:
        tmp_r.write(wrapped)
        tmp_r.close()

        # CREATE_NO_WINDOW prevents R.exe console flash on Windows
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW

        proc = subprocess.run(
            [bridge.rscript, tmp_r.name],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    finally:
        try:
            os.unlink(tmp_r.name)
        except Exception:
            pass

    if proc.returncode != 0:
        from ctrdata.process_env import _translate_r_error
        translated = _translate_r_error(proc.stderr[:500])
        raise CtrdataError(f"R 执行失败:\n{translated}")

    return proc


def run_r_json(bridge, r_code: str, timeout: int = 600) -> Any:
    """Execute R code and parse JSON result."""
    import json as _json

    proc = run_r(bridge, r_code, timeout)

    output = proc.stdout.strip()
    for line in reversed(output.split("\n")):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            return _json.loads(line)

    return {"ok": True, "raw_output": output}


_MAX_TIMEOUT_CONTINUES = 3  # Max times user can extend timeout before force-kill


def run_r_streaming(
    bridge,
    r_code: str,
    callback: Callable[[str], None] = None,
    timeout: int = 600,
    stall_timeout: int = None,
    on_timeout: Callable[[int], str] = None,
) -> subprocess.CompletedProcess:
    """Execute R code, read stdout line-by-line with progress callbacks."""
    wrapped = (
        "suppressMessages({\n"
        "  library(jsonlite)\n"
        "  library(nodbi)\n"
        "  library(ctrdata)\n"
        "})\n"
        "tryCatch({\n" + r_code + "\n"
        "}, error = function(e) {\n"
        "  cat(sprintf('ERROR\\t%s\\n', as.character(e$message)))\n"
        "})\n"
    )

    tmp_r = tempfile.NamedTemporaryFile(
        mode="w", suffix=".R", delete=False, encoding="utf-8"
    )
    try:
        tmp_r.write(wrapped)
        tmp_r.close()

        # CREATE_NO_WINDOW prevents R.exe console flash on Windows
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            [bridge.rscript, tmp_r.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        bridge._current_process = proc

        line_queue: queue_mod.Queue = queue_mod.Queue()

        def _stdout_reader():
            try:
                for raw_line in proc.stdout:
                    line_queue.put(raw_line.rstrip("\n"))
            finally:
                line_queue.put(None)

        reader = threading.Thread(target=_stdout_reader, daemon=True)
        reader.start()

        stdout_lines = []
        start = time.time()
        last_activity = time.time()
        poll_interval = 0.5
        continue_count = 0

        while True:
            try:
                line = line_queue.get(timeout=poll_interval)
            except queue_mod.Empty:
                if proc.poll() is not None:
                    break
                now = time.time()
                if timeout and (now - start) > timeout:
                    choice = None
                    if on_timeout and continue_count < _MAX_TIMEOUT_CONTINUES:
                        choice = on_timeout(int(now - start))
                        if choice == "continue":
                            start = now
                            last_activity = now
                            continue_count += 1
                            continue
                    proc.kill()
                    proc.wait(timeout=5)
                    reason = "已达到最大续期次数" if continue_count >= _MAX_TIMEOUT_CONTINUES else ""
                    raise DownloadTimeoutError(
                        f"R 执行超时（{timeout}秒）{reason}",
                        elapsed=int(now - start),
                        user_action=choice if on_timeout else "",
                    )
                if stall_timeout and (now - last_activity) > stall_timeout:
                    choice = None
                    if on_timeout and continue_count < _MAX_TIMEOUT_CONTINUES:
                        choice = on_timeout(int(now - start))
                        if choice == "continue":
                            start = now
                            last_activity = now
                            continue_count += 1
                            continue
                    proc.kill()
                    proc.wait(timeout=5)
                    raise DownloadTimeoutError(
                        f"下载无响应超时（{stall_timeout}秒），已自动终止。\n"
                        f"可重新点击下载按钮重新下载。",
                        elapsed=int(now - start),
                        user_action=choice if on_timeout else "",
                    )
                continue

            if line is None:
                break
            last_activity = time.time()
            stdout_lines.append(line)
            if line.startswith("ERROR\t"):
                logger.warning("R subprocess error: %s", line[6:])
            if callback:
                callback(line)
            if timeout and (time.time() - start) > timeout:
                _choice = None
                if on_timeout and continue_count < _MAX_TIMEOUT_CONTINUES:
                    _choice = on_timeout(int(time.time() - start))
                    if _choice == "continue":
                        start = time.time()
                        last_activity = time.time()
                        continue_count += 1
                        # Don't raise — keep reading
                    else:
                        proc.kill()
                        proc.wait(timeout=5)
                        raise DownloadTimeoutError(
                            f"R 执行超时（{timeout}秒）",
                            elapsed=int(time.time() - start),
                            user_action=_choice,
                        )

        proc.wait(timeout=10)
        stdout = "\n".join(stdout_lines)
        from ctrdata.process_env import _translate_r_error
        stderr = _translate_r_error(proc.stderr.read())

        return subprocess.CompletedProcess(
            args=proc.args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        bridge._current_process = None
        try:
            os.unlink(tmp_r.name)
        except Exception:
            pass


# ============================================================
# Single trial document download
# ============================================================

def download_one_trial_doc(
    bridge,
    trial_id: str,
    documents_path: str,
    documents_regexp: str,
    timeout: int,
) -> dict:
    """Download documents for a single trial in a separate R process."""
    db = _r_escape(bridge.db_path)
    col = _r_escape(bridge.collection)
    dp = _r_escape(documents_path)
    doc_re = (
        f', documents.regexp = "{_r_escape(documents_regexp)}"'
        if documents_regexp else ""
    )
    safe_id = _r_escape(trial_id)

    r_code = _render(
        "download_one_trial_doc",
        db=db,
        col=col,
        safe_id=safe_id,
        dp=dp,
        doc_re=doc_re,
    )

    proc = run_r_streaming(
        bridge,
        r_code,
        timeout=timeout + 30,
        stall_timeout=timeout,
    )

    import json as _json

    output = proc.stdout.strip()
    for line in reversed(output.split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                return _json.loads(line)
            except _json.JSONDecodeError:
                pass
            break

    return {"ok": False, "n": 0, "error": "No output from R"}


# ============================================================
# Batch document download (single R session)
# ============================================================

def download_batch_docs(
    bridge,
    trial_ids: list,
    documents_path: str,
    documents_regexp: str,
    total_timeout: int = 7200,
    per_trial_timeout: int = 180,
    progress_callback: Callable = None,
) -> list:
    """Download documents for multiple trials in a single R session.

    Args:
        bridge: CtrdataBridge instance
        trial_ids: List of trial IDs to download
        documents_path: Directory to save documents
        documents_regexp: Optional regex filter for document types
        total_timeout: Maximum total execution time in seconds
        per_trial_timeout: Not used for batch (total_timeout governs)
        progress_callback: Called with (i, total, tid, status, error) for each PROGRESS line

    Returns:
        List of result dicts from R, one per trial.
    """
    import json as _json

    db = _r_escape(bridge.db_path)
    col = _r_escape(bridge.collection)
    dp = _r_escape(documents_path)
    doc_re = (
        f', documents.regexp = "{_r_escape(documents_regexp)}"'
        if documents_regexp else ""
    )
    # Escape single quotes in JSON for embedding in R string
    trial_ids_json = _json.dumps(trial_ids).replace("'", "\\'")

    r_code = _render(
        "download_batch_docs",
        db=db,
        col=col,
        trial_ids_json=trial_ids_json,
        dp=dp,
        doc_re=doc_re,
    )

    def _line_callback(line):
        if line.startswith("PROGRESS\t"):
            parts = line.split("\t")
            if len(parts) >= 5:
                try:
                    i = int(parts[1])
                    total = int(parts[2])
                    tid = parts[3]
                    status = parts[4]
                    error = parts[5] if len(parts) > 5 else ""
                    if progress_callback:
                        progress_callback(i, total, tid, status, error)
                except (ValueError, IndexError):
                    pass

    proc = run_r_streaming(
        bridge,
        r_code,
        callback=_line_callback,
        timeout=total_timeout,
    )

    # Parse final JSON array from output
    output = proc.stdout.strip()
    for line in reversed(output.split("\n")):
        line = line.strip()
        if line.startswith("["):
            try:
                return _json.loads(line)
            except _json.JSONDecodeError:
                pass
            break

    return [{"ok": False, "error": "No batch results from R"}]


# ============================================================
# Temp file cleanup
# ============================================================

def cleanup_temp_files():
    """Clean up orphaned temp .R files older than 24 hours."""
    import glob

    tmp_dir = tempfile.gettempdir()
    stale_threshold = time.time() - 86400
    for f in glob.glob(os.path.join(tmp_dir, "tmp*.R")):
        try:
            if os.path.getmtime(f) < stale_threshold:
                os.unlink(f)
        except Exception:
            pass
