#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_extract_json_from_output 单测（P1-6）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctrdata.process import _extract_json_from_output


def test_finds_last_object():
    out = "进度信息\n{\"ok\": true, \"n\": 5}\n"
    assert _extract_json_from_output(out, "object") == {"ok": True, "n": 5}


def test_finds_array():
    out = "[{\"trial_id\": \"NCT1\"}]\n"
    assert _extract_json_from_output(out, "array") == [{"trial_id": "NCT1"}]


def test_any_mode_finds_object_or_array():
    assert _extract_json_from_output("{\"a\": 1}", "any") == {"a": 1}
    assert _extract_json_from_output("[1, 2, 3]", "any") == [1, 2, 3]


def test_skips_invalid_brace_line_then_finds_valid():
    """关键健壮性：含 { 的诊断行解析失败后，继续找前一行真 JSON（continue 而非 break）。"""
    out = "{\"ok\": true}\n{broken diagnostic line\n"
    assert _extract_json_from_output(out, "object") == {"ok": True}


def test_returns_none_when_no_json():
    assert _extract_json_from_output("no json here\n", "object") is None


def test_object_mode_ignores_arrays():
    assert _extract_json_from_output("[1, 2, 3]", "object") is None


def test_empty_output_returns_none():
    assert _extract_json_from_output("", "any") is None


def test_default_expect_is_any():
    assert _extract_json_from_output("[1]") == [1]
    assert _extract_json_from_output("{\"x\": 1}") == {"x": 1}
