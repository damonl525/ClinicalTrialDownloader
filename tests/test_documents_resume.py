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

    tid = "2004-000356-17-3RD"  # EUCTR：P1-1 分流后走 per-trial 路径
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

    # EUCTR trials：P1-1 分流后走 per-trial 路径（该测试验证 per-trial 循环的 trial 间 cancel）
    euctr_ids = ["2004-000356-17-3RD", "2010-023156-12-DE", "2012-005148-21-GB"]
    result = download_documents_for_ids(bridge, euctr_ids, documents_path)

    assert calls == [euctr_ids[0]]  # 只下了第一个就停


def test_find_resume_files_glob_matches_hashed_names(tmp_path):
    """_find_resume_files_for_db 返回该 db 的所有 hash 命名 resume 文件。"""
    from ctrdata.documents import _find_resume_files_for_db

    db_path = str(tmp_path / "trials.sqlite")
    # 真实 resume 文件模式: {db_basename}_{8-hex path_slug}_doc_resume.json
    f1 = tmp_path / "trials_a1b2c3d4_doc_resume.json"
    f2 = tmp_path / "trials_e5f6a7b8_doc_resume.json"
    f1.write_text("{}")
    f2.write_text("{}")
    # 干扰项必须被忽略
    (tmp_path / "trials.sqlite").write_text("db")          # db 文件本身
    (tmp_path / "other_a1b2c3d4_doc_resume.json").write_text("{}")  # 另一个 db
    (tmp_path / "trials_doc_resume.json").write_text("{}")  # legacy 无 hash（非生产格式）

    found = {os.path.basename(p) for p in _find_resume_files_for_db(db_path)}
    assert found == {
        "trials_a1b2c3d4_doc_resume.json",
        "trials_e5f6a7b8_doc_resume.json",
    }


def test_find_resume_files_empty_when_none(tmp_path):
    """无 resume 文件时返回空列表，不报错。"""
    from ctrdata.documents import _find_resume_files_for_db

    db_path = str(tmp_path / "trials.sqlite")
    assert _find_resume_files_for_db(db_path) == []
