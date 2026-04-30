#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R environment and utilities — process_env submodule for ctrdata package.

Provides: _r_escape(), _validate_r_input(), _translate_r_error(),
_find_rscript(), check_r_environment().
"""

import os
import sys
import re
import json
import logging
from typing import Any

from core.constants import R_ERROR_TRANSLATIONS
from core.exceptions import CtrdataError

logger = logging.getLogger(__name__)

# ============================================================
# String escaping
# ============================================================

def _r_escape(s: str) -> str:
    """转义字符串用于嵌入 R 代码中的双引号字符串"""
    return (
        s.replace("\\", "/")       # Windows paths → forward slashes
         .replace('"', '\\"')      # Escape double quotes
         .replace("'", "\\'")      # Escape single quotes
         .replace("$", "\\$")      # Prevent R variable interpolation
         .replace("`", "\\`")      # Prevent R non-standard evaluation injection
         .replace("\n", "\\n")     # Prevent multi-line string breakage
         .replace("\r", "")        # Remove carriage returns
         .replace("\x00", "")      # Remove null bytes
    )


# ============================================================
# Input validation
# ============================================================

_R_DANGEROUS_PATTERNS = [
    r"\bsystem\s*\(",
    r"\bshell\s*\(",
    r"\bfile\.remove\s*\(",
    r"\bunlink\s*\(",
    r"\b\.Internal\s*\(",
    r"\beval\s*\(\s*parse\s*\(",
    r"\bsetwd\s*\(",
    r"\bwriteLines\s*\(",
    r"\bwrite\.table\s*\(",
    r"\bdownload\.file\s*\(",
]

_MAX_INPUT_LENGTH = 2000


def _validate_r_input(value: str, label: str = "输入") -> str:
    """Validate user input before embedding in R code.

    Returns the value if safe, raises CtrdataError if dangerous.
    """
    if len(value) > _MAX_INPUT_LENGTH:
        raise CtrdataError(f"{label}过长（最多 {_MAX_INPUT_LENGTH} 字符）")

    for pattern in _R_DANGEROUS_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            raise CtrdataError(f"{label}包含不允许的内容")

    return value


# ============================================================
# Error translation
# ============================================================

def _translate_r_error(stderr_text: str) -> str:
    """Translate common R error messages to Chinese with resolution hints."""
    if not stderr_text:
        return stderr_text
    for pattern, translation in R_ERROR_TRANSLATIONS:
        if re.search(pattern, stderr_text, re.IGNORECASE):
            return f"{translation}\n（原文：{stderr_text.strip()[:200]}）"
    return stderr_text


# ============================================================
# R path detection
# ============================================================

def _find_rscript() -> str:
    """查找 Rscript 可执行文件路径"""
    import shutil

    # 1. R_HOME 环境变量
    r_home = os.environ.get("R_HOME", "")
    if r_home:
        exe = os.path.join(
            r_home, "bin", "Rscript.exe" if sys.platform == "win32" else "Rscript"
        )
        if os.path.exists(exe):
            return exe

    # 2. Windows 注册表
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\R-core\R")
            path, _ = winreg.QueryValueEx(key, "InstallPath")
            if path:
                exe = os.path.join(path, "bin", "Rscript.exe")
                if os.path.exists(exe):
                    return exe
        except OSError:
            pass

        # 3. 常见路径
        from pathlib import Path

        for base in [r"C:\Program Files\R", r"C:\Program Files (x86)\R"]:
            if os.path.exists(base):
                versions = sorted(Path(base).glob("R-*"), reverse=True)
                if versions:
                    exe = os.path.join(str(versions[0]), "bin", "Rscript.exe")
                    if os.path.exists(exe):
                        return exe

    # 4. PATH
    found = shutil.which("Rscript")
    if found:
        return found

    return ""


# ============================================================
# R environment check
# ============================================================

def check_r_environment() -> dict:
    """
    检测 R 环境和 ctrdata 包

    Returns:
        {"r_available": bool, "r_path": str, "packages": {...}, "error": str}
    """
    rscript = _find_rscript()
    if not rscript:
        return {
            "r_available": False,
            "error": "未找到 R 安装。请安装 R: https://cran.r-project.org/",
        }

    r_code = """\
    library(jsonlite)
    result <- list(
        r_version = R.version.string,
        ctrdata = "",
        nodbi = "",
        RSQLite = "",
        chromote = ""
    )
    tryCatch({
        result$ctrdata <- as.character(packageVersion("ctrdata"))
    }, error = function(e) {})
    tryCatch({
        result$nodbi <- as.character(packageVersion("nodbi"))
    }, error = function(e) {})
    tryCatch({
        result$RSQLite <- as.character(packageVersion("RSQLite"))
    }, error = function(e) {})
    tryCatch({
        result$chromote <- as.character(packageVersion("chromote"))
    }, error = function(e) {})
    cat(toJSON(result, auto_unbox=TRUE))
    """

    import tempfile
    import subprocess

    tmp_r = tempfile.NamedTemporaryFile(
        mode="w", suffix=".R", delete=False, encoding="utf-8"
    )
    try:
        tmp_r.write(r_code)
        tmp_r.close()

        # CREATE_NO_WINDOW prevents R.exe console flash on Windows
        si = None
        cf = 0
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            cf = subprocess.CREATE_NO_WINDOW

        proc = subprocess.run(
            [rscript, tmp_r.name],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
            startupinfo=si,
            creationflags=cf,
        )
    finally:
        try:
            os.unlink(tmp_r.name)
        except Exception:
            pass

    output_lines = [
        l for l in proc.stdout.strip().split("\n") if l.strip().startswith("{")
    ]
    if not output_lines:
        return {
            "r_available": True,
            "r_path": rscript,
            "packages": {},
            "error": "ctrdata 包未安装",
        }

    info = json.loads(output_lines[-1])
    missing = [k for k, v in info.items() if k != "r_version" and not v]
    error_parts = []
    if missing:
        error_parts.append(f'缺少 R 包: {", ".join(missing)}')

    ctrdata_ver = info.get("ctrdata", "")
    if ctrdata_ver:
        try:
            min_ver = tuple(int(x) for x in "1.26.0".split("."))
            cur_ver = tuple(int(x) for x in ctrdata_ver.split("."))
            if cur_ver < min_ver:
                error_parts.append(f"ctrdata {ctrdata_ver} 版本过低（需要 >= 1.26.0）")
        except (ValueError, AttributeError):
            pass

    install_hint = '请运行: install.packages(c("ctrdata", "nodbi", "RSQLite", "chromote"))'
    error_msg = (error_parts[0] + "。" + install_hint) if len(error_parts) == 1 else (
        "；".join(error_parts) + "。" + install_hint
    ) if error_parts else ""

    return {
        "r_available": True,
        "r_path": rscript,
        "r_version": info.get("r_version", "?"),
        "packages": {
            "ctrdata": info.get("ctrdata", ""),
            "nodbi": info.get("nodbi", ""),
            "RSQLite": info.get("RSQLite", ""),
            "chromote": info.get("chromote", ""),
        },
        "error": error_msg,
    }
