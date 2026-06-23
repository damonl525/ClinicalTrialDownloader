#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bridge.cancel() 进程跟踪测试（P1-2）。"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_bridge():
    """Create a CtrdataBridge without running __init__ (avoids R lookup)."""
    from ctrdata.bridge import CtrdataBridge
    b = object.__new__(CtrdataBridge)
    b._current_process = None
    b._current_processes = []
    b._cancelled = False
    return b


def test_cancel_kills_all_active_processes():
    """cancel() 必须 kill 集合里的全部进程，不只最后一个。"""
    b = _make_bridge()
    p1 = MagicMock()
    p2 = MagicMock()
    b._current_processes = [p1, p2]

    b.cancel()

    p1.kill.assert_called_once()
    p1.wait.assert_called_once()
    p2.kill.assert_called_once()
    p2.wait.assert_called_once()
    assert b._current_processes == []


def test_cancel_with_no_processes_is_safe():
    b = _make_bridge()
    b.cancel()  # 不应抛
    assert b._current_processes == []


def test_cancel_sets_cancelled_flag():
    b = _make_bridge()
    b.cancel()
    assert b._cancelled is True


def test_cancel_survives_kill_exception():
    """单个进程 kill 失败不应阻止 kill 其余进程。"""
    b = _make_bridge()
    p1 = MagicMock()
    p1.kill.side_effect = OSError("already dead")
    p2 = MagicMock()
    b._current_processes = [p1, p2]

    b.cancel()

    p2.kill.assert_called_once()  # p2 仍被 kill
    assert b._current_processes == []
