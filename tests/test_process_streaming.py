#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_r_streaming 死锁回归测试（P0-1）。需要 R 环境。"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rscript():
    """返回可用的 Rscript 路径，且 jsonlite 可加载（run_r_streaming 依赖它）。

    CI runner 可能预装残缺 R（有 Rscript 但缺 jsonlite/ctrdata），此时跳过。
    """
    import subprocess
    try:
        from ctrdata.process import _find_rscript
        rs = _find_rscript()
        if not rs:
            return None
        # 验证 Rscript 能跑 + jsonlite 可加载（run_r_streaming 的 _wrap_r_code 会 library(jsonlite)）
        check = (
            'suppressMessages(library(jsonlite));'
            'cat("OK")'
        )
        r = subprocess.run([rs, "-e", check], capture_output=True, timeout=15)
        if r.returncode != 0 or b"OK" not in r.stdout:
            return None
        return rs
    except Exception:
        return None


@pytest.mark.skipif(not _rscript(), reason="requires R installation")
def test_run_r_streaming_survives_large_stderr():
    """R 向 stderr 写 >64KB 时，run_r_streaming 不得死锁，且能读到 stdout。

    修复前：stderr 管道写满 → R 阻塞 → 超时（timeout=30s 后失败）。
    修复后：stderr reader 持续消费 → 快速完成，stdout 含 DONE。
    """
    from ctrdata.process import run_r_streaming

    # 20000 次 message，每次 50 字符 + 换行 ≈ 1MB stderr（远超 64KB 管道）
    r_code = (
        'for (i in 1:20000) message(paste(rep("x", 50), collapse=""))\n'
        'cat("DONE\\n")\n'
    )
    bridge = MagicMock()
    bridge._cancelled = False
    bridge.rscript = _rscript()

    proc = run_r_streaming(bridge, r_code, timeout=30)

    assert "DONE" in proc.stdout
