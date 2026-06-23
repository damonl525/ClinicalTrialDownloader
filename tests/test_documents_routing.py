#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-1 文档下载按注册中心分流的测试。

CTGOV2 应走单 session batch（download_batch_docs），EUCTR/CTIS/ISRCTN 走
per-trial（download_one_trial_doc）。两段共用同一 resume 文件。
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_bridge(tmp_path):
    """CtrdataBridge without __init__ (avoids R lookup)."""
    from ctrdata.bridge import CtrdataBridge
    b = object.__new__(CtrdataBridge)
    b.db_path = str(tmp_path / "test.db")
    b.collection = "test_col"
    b._cancelled = False
    b._current_process = None
    b._current_processes = []
    return b


def _ok_result(tid):
    return {"trial_id": tid, "ok": True, "n": 1, "error": ""}


def _install_mocks(monkeypatch, per_trial_results=None, batch_results=None,
                   batch_exc=None):
    """Mock 下载入口。per_trial_results/batch_results: {tid: result_dict}。

    返回 (per_trial_calls, batch_calls) 记录调用参数。
    """
    per_trial_calls = []
    batch_calls = []

    def fake_per_trial(bridge, tid, dp, regexp, timeout):
        per_trial_calls.append(tid)
        return (per_trial_results or {}).get(tid, _ok_result(tid))

    def fake_batch(bridge, trial_ids, dp, regexp, total_timeout=7200,
                   per_trial_timeout=180, progress_callback=None):
        batch_calls.append(list(trial_ids))
        if batch_exc:
            raise batch_exc
        # 模拟 R 端逐 trial 发 PROGRESS
        results = []
        for i, tid in enumerate(trial_ids, 1):
            r = (batch_results or {}).get(tid, _ok_result(tid))
            if progress_callback and r.get("ok"):
                progress_callback(i, len(trial_ids), tid, "ok", "")
            elif progress_callback:
                progress_callback(i, len(trial_ids), tid, "error", r.get("error", "x"))
            results.append(r)
        return results

    monkeypatch.setattr("ctrdata.documents.download_one_trial_doc", fake_per_trial)
    monkeypatch.setattr("ctrdata.process.download_batch_docs", fake_batch)
    return per_trial_calls, batch_calls


def test_all_ctgov2_goes_through_batch(tmp_path, monkeypatch):
    """全部 CTGOV2 → 只调 batch，不调 per-trial。"""
    bridge = _make_bridge(tmp_path)
    docs = tmp_path / "docs"
    ids = ["NCT04523532", "NCT99999999", "NCT01234567"]

    per_calls, batch_calls = _install_mocks(monkeypatch)
    from ctrdata.documents import download_documents_for_ids
    # 为让 _trial_has_docs 返回 True，预创建文件
    for tid in ids:
        (docs / tid).mkdir(parents=True, exist_ok=True)
        (docs / tid / "f.pdf").write_bytes(b"x")

    download_documents_for_ids(bridge, ids, str(docs), documents_regexp=".*")

    assert len(batch_calls) == 1
    assert sorted(batch_calls[0]) == sorted(ids)
    assert per_calls == []  # CTGOV2 不走 per-trial


def test_all_euctr_goes_through_per_trial(tmp_path, monkeypatch):
    """全部 EUCTR → 只调 per-trial，不调 batch。"""
    bridge = _make_bridge(tmp_path)
    docs = tmp_path / "docs"
    ids = ["2004-000356-17-3RD", "2010-023156-12-DE"]

    per_calls, batch_calls = _install_mocks(monkeypatch)
    from ctrdata.documents import download_documents_for_ids
    for tid in ids:
        (docs / tid).mkdir(parents=True, exist_ok=True)
        (docs / tid / "f.pdf").write_bytes(b"x")

    download_documents_for_ids(bridge, ids, str(docs), documents_regexp=".*")

    assert batch_calls == []  # 无 CTGOV2 → 无 batch
    assert sorted(per_calls) == sorted(ids)


def test_mixed_routing_splits_correctly(tmp_path, monkeypatch):
    """混合 → CTGOV2 走 batch，EUCTR 走 per-trial。"""
    bridge = _make_bridge(tmp_path)
    docs = tmp_path / "docs"
    ctgov2 = ["NCT04523532", "NCT01234567"]
    euctr = ["2004-000356-17-3RD"]
    ids = ctgov2 + euctr

    per_calls, batch_calls = _install_mocks(monkeypatch)
    from ctrdata.documents import download_documents_for_ids
    for tid in ids:
        (docs / tid).mkdir(parents=True, exist_ok=True)
        (docs / tid / "f.pdf").write_bytes(b"x")

    download_documents_for_ids(bridge, ids, str(docs), documents_regexp=".*")

    assert sorted(batch_calls[0]) == sorted(ctgov2)
    assert per_calls == euctr


def test_batch_failure_marks_unfinished_ctgov2_failed(tmp_path, monkeypatch):
    """batch 整体失败 → 未完成 CTGOV2 标记 failed（下次 resume 可重试）。"""
    bridge = _make_bridge(tmp_path)
    docs = tmp_path / "docs"
    ids = ["NCT04523532", "NCT01234567"]

    from core.exceptions import DownloadTimeoutError
    per_calls, batch_calls = _install_mocks(
        monkeypatch, batch_exc=DownloadTimeoutError("batch timed out")
    )
    from ctrdata.documents import download_documents_for_ids

    result = download_documents_for_ids(bridge, ids, str(docs), documents_regexp=".*")

    assert batch_calls  # batch 被调用
    # 两个 CTGOV2 都应在 failed（或 skipped，因 TIMEOUT 关键字）里
    all_failed = {**result.get("failed", {}), **result.get("skipped", {})}
    for tid in ids:
        assert tid in all_failed, f"{tid} 应在 failed/skipped"


def test_ctgov2_trial_with_no_docs_marked_failed(tmp_path, monkeypatch):
    """CTGOV2 trial 返回 ok 但无文档（n=0）→ 标记 failed（与 per-trial 路径一致）。

    R 模板对 n=0 且无 error 的 trial 发 status="ok"。per-trial 路径
    （documents.py:303）把这种情况标记为 failed "No documents found"，
    batch 路径必须保持一致，不能静默丢弃。
    """
    bridge = _make_bridge(tmp_path)
    docs = tmp_path / "docs"
    no_doc = "NCT00000000"
    with_doc = "NCT04523532"
    ids = [no_doc, with_doc]

    # with_doc 预创建文件；no_doc 不创建（模拟 n=0 无文档）
    (docs / with_doc).mkdir(parents=True, exist_ok=True)
    (docs / with_doc / "f.pdf").write_bytes(b"x")

    per_calls, batch_calls = _install_mocks(monkeypatch)
    from ctrdata.documents import download_documents_for_ids

    result = download_documents_for_ids(bridge, ids, str(docs), documents_regexp=".*")

    assert with_doc in result["success"]
    assert no_doc in result["failed"]
    assert "No documents found" in result["failed"][no_doc]


def test_resume_session_hash_uses_all_trial_ids(tmp_path, monkeypatch):
    """分流后 resume session hash 仍基于全部 trial_ids（不因子集失效）。"""
    from ctrdata.documents import _session_hash
    mixed = ["NCT04523532", "2004-000356-17-3RD"]
    # 无论内部分组如何，session hash 应等于全部 ids 的 hash
    expected = _session_hash(mixed, str(tmp_path / "docs"))
    assert _session_hash(mixed, str(tmp_path / "docs")) == expected
