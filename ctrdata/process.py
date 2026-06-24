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
from core.constants import (
    R_POLL_INTERVAL,
    R_TIMEOUT_BUFFER,
    R_TEMP_FILE_MAX_AGE,
    R_TEMP_FILE_PATTERN,
)
from ctrdata.template_loader import render as _render

logger = logging.getLogger(__name__)


# ============================================================
# R execution helpers
# ============================================================

def _extract_json_from_output(output: str, expect: str = "any") -> Optional[Any]:
    """从 R 输出中提取最后一个 JSON 对象/数组。

    从后往前扫描，找第一个以 '{' 或 '[' 开头的非空行并解析。解析失败时
    continue（继续找前一行）而非 break，以容忍 R 打印的含 '{' 的诊断行。

    Args:
        output: R 进程的 stdout
        expect: "object" 只找 '{'，"array" 只找 '['，"any"（默认）两者皆可

    Returns:
        解析后的 dict/list，或 None（无有效 JSON）。
    """
    import json as _json
    if expect == "object":
        prefixes = ("{",)
    elif expect == "array":
        prefixes = ("[",)
    else:
        prefixes = ("{", "[")
    for line in reversed(output.strip().split("\n")):
        line = line.strip()
        if line.startswith(prefixes):
            try:
                return _json.loads(line)
            except _json.JSONDecodeError:
                continue
    return None


def _wrap_r_code(r_code: str, error_format: str = "json") -> str:
    """Wrap R code with library loading and tryCatch error handling.

    Shared by run_r() and run_r_streaming() to eliminate wrapper duplication (P2-9).

    Args:
        r_code: Raw R code to wrap.
        error_format: "json" → toJSON error output (run_r/run_r_json);
                      "streaming" → ERROR\\t line output (run_r_streaming).
    """
    if error_format == "streaming":
        error_handler = (
            "}, error = function(e) {\n"
            "  cat(sprintf('ERROR\\t%s\\n', as.character(e$message)))\n"
            "})\n"
        )
    else:
        error_handler = (
            "}, error = function(e) {\n"
            "  cat(jsonlite::toJSON(list(\n"
            "    ok = FALSE,\n"
            "    error = as.character(e$message)\n"
            "  ), auto_unbox=TRUE))\n"
            "})\n"
        )
    return (
        "suppressMessages({\n"
        "  library(jsonlite)\n"
        "  library(nodbi)\n"
        "  library(ctrdata)\n"
        "})\n"
        "tryCatch({\n" + r_code + "\n"
        + error_handler
    )


def run_r(
    bridge,
    r_code: str,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """Execute R code via temp .R file, return CompletedProcess."""
    wrapped = _wrap_r_code(r_code, error_format="json")

    tmp_r = tempfile.NamedTemporaryFile(
        mode="w", prefix="ctrdata_", suffix=".R", delete=False, encoding="utf-8"
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
    proc = run_r(bridge, r_code, timeout)

    output = proc.stdout.strip()
    result = _extract_json_from_output(output, expect="any")
    if result is not None:
        return result

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
    wrapped = _wrap_r_code(r_code, error_format="streaming")

    tmp_r = tempfile.NamedTemporaryFile(
        mode="w", prefix="ctrdata_", suffix=".R", delete=False, encoding="utf-8"
    )
    proc = None  # Popen 失败时 finally 引用未绑定 proc 会 UnboundLocalError 掩盖原异常
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
        bridge._current_processes.append(proc)

        line_queue: queue_mod.Queue = queue_mod.Queue()
        stderr_chunks: list = []

        def _stdout_reader():
            try:
                for raw_line in proc.stdout:
                    line_queue.put(raw_line.rstrip("\n"))
            finally:
                line_queue.put(None)

        def _stderr_reader():
            """持续消费 stderr，防止管道写满导致 R 进程死锁。

            ctrdata 用 message() 输出进度到 stderr；若不消费，超 64KB 后
            R 的 write 阻塞 → R 永久挂起 → stdout reader 收不到 EOF。
            """
            try:
                for raw_line in proc.stderr:
                    stderr_chunks.append(raw_line)
            except Exception:
                pass

        reader = threading.Thread(target=_stdout_reader, daemon=True)
        err_reader = threading.Thread(target=_stderr_reader, daemon=True)
        reader.start()
        err_reader.start()

        stdout_lines = []
        start = time.time()
        last_activity = time.time()
        poll_interval = R_POLL_INTERVAL
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
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.warning("R process did not terminate within 5s after kill (timeout)")
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
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.warning("R process did not terminate within 5s after kill (stall)")
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
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            logger.warning("R process did not terminate within 5s after kill (line timeout)")
                        raise DownloadTimeoutError(
                            f"R 执行超时（{timeout}秒）",
                            elapsed=int(time.time() - start),
                            user_action=_choice,
                        )

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("R process did not exit within 10s after EOF, forcing kill")
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        # 等 stderr reader 消费完（proc 退出后 stderr EOF，线程自然结束）
        err_reader.join(timeout=5)
        stdout = "\n".join(stdout_lines)
        from ctrdata.process_env import _translate_r_error
        stderr = _translate_r_error("".join(stderr_chunks))

        return subprocess.CompletedProcess(
            args=proc.args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        bridge._current_process = None
        try:
            bridge._current_processes.remove(proc)
        except (ValueError, AttributeError):
            pass
        try:
            os.unlink(tmp_r.name)
        except Exception:
            pass


# ============================================================
# Single trial document download
# ============================================================

def _is_isrctn_trial(trial_id: str) -> bool:
    """Check if a trial ID belongs to ISRCTN registry."""
    import re as _re
    return trial_id.startswith("ISRCTN") or _re.match(r"^\d{8}$", trial_id)


def _is_euctr_trial(trial_id: str) -> bool:
    """Check if a trial ID belongs to EUCTR registry."""
    from core.constants import classify_registry
    return classify_registry(trial_id) == "EUCTR"


def _is_ctis_trial(trial_id: str) -> bool:
    """Check if a trial ID belongs to CTIS registry."""
    from core.constants import classify_registry
    return classify_registry(trial_id) == "CTIS"


def _euctr_id_to_query(trial_id: str) -> str:
    """Convert EUCTR _id to ctrdata queryterm format.

    EUCTR _id: "2004-000356-17-3RD"  (with country suffix)
    queryterm: "query=2004-000356-17" (EudraCT number, no country)
    """
    parts = trial_id.split("-")
    if len(parts) >= 3:
        eudract = "-".join(parts[:3])
        return f"query={eudract}"
    return f"query={trial_id}"


def download_one_trial_doc(
    bridge,
    trial_id: str,
    documents_path: str,
    documents_regexp: str,
    timeout: int,
) -> dict:
    """Download documents for a single trial.

    ISRCTN trials use direct HTTP download via ISRCTN XML API.
    EUCTR trials use ctrdata with euctrresults=TRUE (no documents.regexp).
    CTGOV2 / CTIS use standard ctrdata with documents.regexp.
    """
    if _is_isrctn_trial(trial_id):
        from ctrdata.isrctn_download import download_isrctn_trial_docs
        return download_isrctn_trial_docs(
            trial_id, documents_path, documents_regexp, timeout=timeout
        )

    if _is_euctr_trial(trial_id):
        return _download_euctr_trial_doc(
            bridge, trial_id, documents_path, timeout,
        )

    if _is_ctis_trial(trial_id):
        return _download_ctis_trial_doc(
            bridge, trial_id, documents_path, documents_regexp, timeout,
        )

    # R-based download for CTGOV2
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
        timeout=timeout + R_TIMEOUT_BUFFER,
        stall_timeout=timeout,
    )

    result = _extract_json_from_output(proc.stdout, expect="object")
    if result is not None:
        return result

    return {"ok": False, "n": 0, "error": "No output from R"}


def _download_euctr_trial_doc(
    bridge,
    trial_id: str,
    documents_path: str,
    timeout: int,
) -> dict:
    """Download EUCTR documents using euctrresults=TRUE.

    EUCTR downloads ALL documents (documents.regexp is not supported).
    queryterm must be "query={eudract_number}" format (no country suffix).
    """
    db = _r_escape(bridge.db_path)
    col = _r_escape(bridge.collection)
    dp = _r_escape(documents_path)
    queryterm = _r_escape(_euctr_id_to_query(trial_id))

    r_code = _render(
        "download_euctr_trial_doc",
        db=db,
        col=col,
        queryterm=queryterm,
        dp=dp,
    )

    proc = run_r_streaming(
        bridge,
        r_code,
        timeout=timeout + R_TIMEOUT_BUFFER,
        stall_timeout=timeout,
    )

    result = _extract_json_from_output(proc.stdout, expect="object")
    if result is not None:
        return result

    return {"ok": False, "n": 0, "error": "No output from R"}


def _download_ctis_trial_doc(
    bridge,
    trial_id: str,
    documents_path: str,
    documents_regexp: str,
    timeout: int,
) -> dict:
    """Download CTIS documents with register="CTIS" specified.

    CTIS trial ID is passed directly; documents.regexp is supported.
    """
    db = _r_escape(bridge.db_path)
    col = _r_escape(bridge.collection)
    dp = _r_escape(documents_path)
    doc_re = (
        f', documents.regexp = "{_r_escape(documents_regexp)}"'
        if documents_regexp else ""
    )
    safe_id = _r_escape(trial_id)

    r_code = _render(
        "download_ctis_trial_doc",
        db=db,
        col=col,
        safe_id=safe_id,
        dp=dp,
        doc_re=doc_re,
    )

    proc = run_r_streaming(
        bridge,
        r_code,
        timeout=timeout + R_TIMEOUT_BUFFER,
        stall_timeout=timeout,
    )

    result = _extract_json_from_output(proc.stdout, expect="object")
    if result is not None:
        return result

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

    result = _extract_json_from_output(proc.stdout, expect="array")
    if result is not None:
        return result

    return [{"ok": False, "error": "No batch results from R"}]


# ============================================================
# Temp file cleanup
# ============================================================

def cleanup_temp_files():
    """Clean up orphaned temp .R files older than 24 hours."""
    import glob

    tmp_dir = tempfile.gettempdir()
    stale_threshold = time.time() - R_TEMP_FILE_MAX_AGE
    # Clean both new ctrdata_*.R files and legacy tmp*.R files (pre-P2-5 naming)
    for pattern in (R_TEMP_FILE_PATTERN, "tmp*.R"):
        for f in glob.glob(os.path.join(tmp_dir, pattern)):
            try:
                if os.path.getmtime(f) < stale_threshold:
                    os.unlink(f)
            except Exception:
                pass
