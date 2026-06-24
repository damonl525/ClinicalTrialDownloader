#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1-8: ExtractService.resolve_protocol_scope — Protocol 多注册中心 scope 决策。

测 4 个分支组合 + all_db_ids 空回退 + 去重保序。无需 R/Qt，用 FakeBridge。
"""

import unittest

from service.extract_service import ExtractService


class _FakeBridge:
    """替身：按预设返回 protocol_ids / all_db_ids。"""

    def __init__(self, protocol_ids=None, all_ids=None):
        self._protocol = list(protocol_ids or [])
        self._all = list(all_ids or [])
        self.protocol_calls = []  # 记录调用参数，便于断言

    def get_protocol_trial_ids(self, scope_ids=None):
        self.protocol_calls.append(scope_ids)
        return list(self._protocol)

    def get_all_trial_ids(self):
        return list(self._all)


def _no_log(*args, **kwargs):
    pass


class TestResolveProtocolScope(unittest.TestCase):
    def test_scoped_ctgov_isrctn_only(self):
        """scoped + ctgov_isrctn_only → 仅 protocol_ids。"""
        bridge = _FakeBridge(protocol_ids=["NCT04523532", "ISRCTN12345678"])
        svc = ExtractService(bridge)
        scope = svc.resolve_protocol_scope(
            ["NCT04523532", "ISRCTN12345678", "2014-000356-17-DE"],
            "ctgov_isrctn_only",
            _no_log,
        )
        self.assertEqual(scope, ["NCT04523532", "ISRCTN12345678"])
        # get_protocol_trial_ids 必须收到原始 scope_ids（scoped 模式）
        self.assertEqual(bridge.protocol_calls[-1],
                         ["NCT04523532", "ISRCTN12345678", "2014-000356-17-DE"])

    def test_scoped_all_registries(self):
        """scoped + all_registries → protocol_ids + scope 中的 EUCTR/CTIS，去重保序。"""
        bridge = _FakeBridge(protocol_ids=["NCT04523532"])
        svc = ExtractService(bridge)
        scope = svc.resolve_protocol_scope(
            ["NCT04523532", "2014-000356-17-DE", "NCT09999999", "2022-500123-42-XX"],
            "all_registries",
            _no_log,
        )
        # protocol_ids 在前，EUCTR/CTIS 按出现顺序追加
        self.assertEqual(scope, ["NCT04523532", "2014-000356-17-DE", "2022-500123-42-XX"])

    def test_full_db_ctgov_isrctn_only(self):
        """full-db(scope_ids=None) + ctgov_isrctn_only → 仅 protocol_ids。"""
        bridge = _FakeBridge(protocol_ids=["NCT04523532", "ISRCTN12345678"])
        svc = ExtractService(bridge)
        scope = svc.resolve_protocol_scope(None, "ctgov_isrctn_only", _no_log)
        self.assertEqual(scope, ["NCT04523532", "ISRCTN12345678"])

    def test_full_db_all_registries(self):
        """full-db + all_registries → protocol_ids + all_db_ids 中的 EUCTR/CTIS。"""
        bridge = _FakeBridge(
            protocol_ids=["NCT04523532"],
            all_ids=["NCT04523532", "2014-000356-17-DE", "ISRCTN12345678", "2022-500123-42-XX"],
        )
        svc = ExtractService(bridge)
        scope = svc.resolve_protocol_scope(None, "all_registries", _no_log)
        self.assertEqual(scope, ["NCT04523532", "2014-000356-17-DE", "2022-500123-42-XX"])

    def test_full_db_all_registries_empty_fallback(self):
        """full-db + all_registries，get_all_trial_ids 返回空 → 回退到 protocol_ids，发 warning。"""
        bridge = _FakeBridge(protocol_ids=["NCT04523532"], all_ids=[])
        svc = ExtractService(bridge)
        logs = []
        scope = svc.resolve_protocol_scope(
            None, "all_registries", lambda lvl, msg: logs.append((lvl, msg))
        )
        self.assertEqual(scope, ["NCT04523532"])  # 回退
        self.assertTrue(any("获取全部试验ID失败" in msg for _, msg in logs),
                        f"应发 warning，实际 logs={logs}")

    def test_dedup_preserves_order_on_overlap(self):
        """去重保序：protocol_ids 与 EUCTR/CTIS 源重叠时不重复（防御性，覆盖 dedup 分支）。"""
        # 模拟 get_protocol_trial_ids 防御性返回了一个 EUCTR（理论上不该，但 dedup 要兜住）
        bridge = _FakeBridge(protocol_ids=["NCT04523532", "2014-000356-17-DE"])
        svc = ExtractService(bridge)
        scope = svc.resolve_protocol_scope(
            ["2014-000356-17-DE", "NCT04523532"], "all_registries", _no_log
        )
        # "2014-000356-17-DE" 只出现一次，protocol 顺序优先
        self.assertEqual(scope, ["NCT04523532", "2014-000356-17-DE"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
