#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""documents.py resume/checkpoint 行为测试（P0-2）。"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_cleanup_trial_partial_docs_removes_subdir_and_prefix_files(tmp_path):
    """清理函数删除 trial 子目录 + 前缀文件，不动其他 trial。"""
    from ctrdata.documents import _cleanup_trial_partial_docs

    # trial 子目录带文件
    trial_dir = tmp_path / "NCT00000001"
    trial_dir.mkdir()
    (trial_dir / "Prot.pdf").write_bytes(b"partial")
    # 扁平前缀文件（中断残留）
    (tmp_path / "NCT00000001_SAP.pdf").write_bytes(b"partial")
    # 无关 trial 必须保留
    (tmp_path / "NCT00000002_other.pdf").write_bytes(b"keep")

    removed = _cleanup_trial_partial_docs(str(tmp_path), "NCT00000001")

    assert removed == 2
    assert not trial_dir.exists()
    assert not (tmp_path / "NCT00000001_SAP.pdf").exists()
    assert (tmp_path / "NCT00000002_other.pdf").exists()


def test_resume_clears_partial_files_for_interrupted_trial(tmp_path, monkeypatch):
    """in_progress 的 trial：重下前必须清理部分文件，避免 ctrdata 跳过残缺文件。"""
    from ctrdata import documents as docs_mod
    from ctrdata.documents import (
        download_documents_for_ids,
        _get_resume_file,
        _save_resume,
        _session_hash,
    )

    documents_path = str(tmp_path / "downloads")
    os.makedirs(documents_path)

    bridge = MagicMock()
    bridge.db_path = str(tmp_path / "trials.sqlite")
    bridge._cancelled = False

    tid = "NCT00000001"
    # 中断残留的部分文件
    partial = os.path.join(documents_path, f"{tid}_Prot.pdf")
    with open(partial, "w") as f:
        f.write("partial-truncated")

    # resume 文件标记 tid 为 in_progress
    resume_file = _get_resume_file(bridge, documents_path)
    session = _session_hash([tid], documents_path)
    _save_resume(
        bridge, resume_file, [], {}, 1,
        skipped_explicitly=[], session=session, in_progress=[tid],
    )

    # mock 真实下载：记录下载发生时部分文件是否已被清理
    seen = {}
    def fake_download(b, t, dp, regexp, timeout):
        seen["partial_exists_at_download"] = os.path.exists(partial)
        with open(os.path.join(dp, f"{t}_Prot.pdf"), "w") as f:
            f.write("complete")
        return {"ok": True, "n": 1}

    monkeypatch.setattr(docs_mod, "download_one_trial_doc", fake_download)

    result = download_documents_for_ids(bridge, [tid], documents_path)

    assert seen["partial_exists_at_download"] is False  # 重下前已清理
    assert result["success"] == [tid]


def test_download_stops_on_cancel(tmp_path, monkeypatch):
    """bridge._cancelled=True 时，循环在 trial 之间中断。"""
    from ctrdata import documents as docs_mod
    from ctrdata.documents import download_documents_for_ids

    documents_path = str(tmp_path / "downloads")
    os.makedirs(documents_path)
    bridge = MagicMock()
    bridge.db_path = str(tmp_path / "trials.sqlite")
    bridge._cancelled = False  # 第一个 trial 后置 True

    calls = []
    def fake_download(b, t, dp, regexp, timeout):
        calls.append(t)
        b._cancelled = True  # 模拟用户在第一个 trial 后取消
        return {"ok": True, "n": 1}

    monkeypatch.setattr(docs_mod, "download_one_trial_doc", fake_download)

    result = download_documents_for_ids(
        bridge, ["NCT00000001", "NCT00000002", "NCT00000003"], documents_path
    )

    assert calls == ["NCT00000001"]  # 只下了第一个就停
