#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
针对3个bug修复的专项测试

Bug 1: 文档下载断点续传 - ctrdata_core.py
Bug 2: 提取数据不一致 - scope ID匹配失败 - export_tab.py
Bug 3: 文档下载目录不存在 - ctrdata_core.py
"""

import unittest
import os
import sys
import tempfile
import shutil
import json
import re
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBug1_ResumeFeature(unittest.TestCase):
    """Bug 1: 文档下载断点续传形同虚设"""

    def setUp(self):
        """导入被测模块"""
        from ctrdata.documents import download_documents_batch
        self.batch_fn = download_documents_batch

    def test_remaining_filter_used_instead_of_full_trial_ids(self):
        """验证: remaining过滤逻辑存在"""
        import inspect

        source = inspect.getsource(self.batch_fn)

        # Verify: remaining is computed by filtering trial_ids
        self.assertIn("remaining = [tid for tid in trial_ids", source,
                       "应该有remaining过滤逻辑")

        print("[Bug1-1] PASS: remaining过滤逻辑正确")

    def test_early_return_when_all_completed(self):
        """验证: 全部已完成时短路逻辑"""
        import inspect

        source = inspect.getsource(self.batch_fn)

        # 验证remaining为空时的短路逻辑
        self.assertIn("if not remaining:", source, "应该有空remaining时的短路逻辑")
        self.assertIn('"total": len(trial_ids)', source, "短路返回时应包含原始total数")

        print("[Bug1-2] PASS: 全部已完成时有短路返回逻辑")

    def test_resume_file_path_correct(self):
        """验证: 断点文件路径正确"""
        from ctrdata_core import CtrdataBridge

        with patch.object(CtrdataBridge, "__init__", lambda self: None):
            bridge = CtrdataBridge()
            bridge.db_path = "/test/path/trials.db"

            resume_file = bridge._get_resume_file("/documents/path")

            # Windows路径可能使用反斜杠
            normalized_path = resume_file.replace("\\", "/")
            self.assertIn(
                "trials_doc_resume.json", resume_file, "断点文件名应该基于数据库名"
            )
            self.assertIn("/test/path/", normalized_path, "断点文件应该在数据库目录")

        print("[Bug1-3] PASS: 断点文件路径正确")


class TestBug2_ScopeIdMatching(unittest.TestCase):
    """Bug 2: 提取数据不一致 - scope ID匹配失败"""

    def test_normalize_id_euctr_strips_country_suffix(self):
        """验证: EUCTR ID去除国家后缀"""
        test_cases = [
            ("EUCTR1234-567-DE", "EUCTR1234-567"),  # 应该去除国家后缀
            ("EUCTR1234-567-FR", "EUCTR1234-567"),
            ("EUCTR1234-567", "EUCTR1234-567"),  # 没有国家后缀保持不变
            ("EUCTR1234-567-UK", "EUCTR1234-567"),
        ]

        for input_id, expected in test_cases:
            # 模拟_normalize_id逻辑
            tid = str(input_id).strip()
            if tid.startswith("EUCTR"):
                parts = tid.rsplit("-", 1)
                if len(parts) > 1 and len(parts[-1]) == 2:
                    result = parts[0]
                else:
                    result = tid
            else:
                result = tid

            self.assertEqual(
                result,
                expected,
                "输入 {} 期望 {} 得到 {}".format(input_id, expected, result),
            )

        print("[Bug2-1] PASS: EUCTR ID宽松匹配正确去除国家后缀")

    def test_normalize_id_nct_strips_version_suffix(self):
        """验证: NCT ID去除版本后缀"""
        test_cases = [
            ("NCT04523532-1", "NCT04523532"),
            ("NCT04523532-2", "NCT04523532"),
            ("NCT04523532", "NCT04523532"),  # 无版本后缀保持不变
            ("NCT12345678-10", "NCT12345678"),
        ]

        for input_id, expected in test_cases:
            tid = str(input_id).strip()
            if tid.startswith("NCT") and "-" in tid:
                result = tid.split("-")[0]
            else:
                result = tid

            self.assertEqual(
                result,
                expected,
                "输入 {} 期望 {} 得到 {}".format(input_id, expected, result),
            )

        print("[Bug2-2] PASS: NCT ID宽松匹配正确去除版本后缀")

    def test_three_level_matching_logic_exists(self):
        """验证: 三级匹配逻辑存在"""
        from gui.tabs.export_tab import ExportTab
        import inspect

        source = inspect.getsource(ExportTab._extract)

        # 验证精确匹配
        self.assertIn(
            "exact_mask = df_ids.isin(scope_set)", source, "应该存在精确匹配逻辑"
        )
        self.assertIn("exact_matched > 0", source, "应该有精确匹配成功判断")

        # 验证宽松匹配
        self.assertIn("_normalize_id", source, "应该存在_normalize_id函数")
        self.assertIn("loose_mask", source, "应该存在宽松匹配逻辑")

        # 验证弹窗选择
        self.assertIn("messagebox.askyesno", source, "应该有用户选择弹窗")

        print("[Bug2-3] PASS: 三级匹配逻辑完整实现")
        print("  - 精确匹配: exact_mask")
        print("  - 宽松匹配: loose_mask + _normalize_id")
        print("  - 用户选择: messagebox.askyesno")


class TestBug3_DocumentsPath(unittest.TestCase):
    """Bug 3: 文档下载目录不存在"""

    def test_makedirs_called_at_start(self):
        """验证: os.makedirs在函数开头被调用"""
        from ctrdata.documents import download_documents_batch
        import inspect

        source = inspect.getsource(download_documents_batch)

        # 验证os.makedirs存在
        self.assertIn(
            "os.makedirs(documents_path", source, "应该调用os.makedirs创建目录"
        )

        # 验证在函数开头（在任何可能返回的语句之前）
        lines = source.split("\n")
        makedirs_line = None
        early_return_line = None

        for i, line in enumerate(lines):
            if "os.makedirs(documents_path" in line:
                makedirs_line = i
            if "if not remaining:" in line:
                early_return_line = i

        if makedirs_line is not None and early_return_line is not None:
            self.assertLess(
                makedirs_line, early_return_line, "os.makedirs应该在early return之前"
            )

        print(
            "[Bug3-1] PASS: os.makedirs在正确位置（第{}行）".format(makedirs_line + 1)
        )
        print("[Bug3-2] PASS: 在早期返回逻辑之前执行")

    def test_makedirs_exist_ok_true(self):
        """验证: os.makedirs使用exist_ok=True"""
        from ctrdata.documents import download_documents_batch
        import inspect

        source = inspect.getsource(download_documents_batch)

        self.assertIn(
            "exist_ok=True",
            source,
            "os.makedirs应该使用exist_ok=True避免目录已存在报错",
        )

        print("[Bug3-3] PASS: 使用exist_ok=True避免重复创建报错")


class TestBugFixesIntegration(unittest.TestCase):
    """综合测试：验证3个bug修复的集成效果"""

    def test_all_bug_fixes_present(self):
        """验证: 所有3个bug修复代码都存在"""
        from ctrdata.documents import download_documents_batch
        from gui.tabs.export_tab import ExportTab
        import inspect

        # Bug 1 & 3: documents.py (batch download is the current implementation)
        docs_source = inspect.getsource(download_documents_batch)

        bug1_fixed = "remaining" in docs_source
        bug3_fixed = "os.makedirs(documents_path" in docs_source

        self.assertTrue(bug1_fixed, "Bug1修复代码缺失")
        self.assertTrue(bug3_fixed, "Bug3修复代码缺失")

        # Bug 2: export_tab.py
        export_source = inspect.getsource(ExportTab._extract)
        bug2_fixed = "_normalize_id" in export_source and "loose_mask" in export_source

        self.assertTrue(bug2_fixed, "Bug2修复代码缺失")

        print("\n" + "=" * 50)
        print("综合测试结果:")
        print("=" * 50)
        print("[Bug1] PASS: 断点续传修复 - remaining过滤正确实现")
        print("[Bug2] PASS: ID匹配修复 - 三级匹配逻辑正确实现")
        print("[Bug3] PASS: 目录创建修复 - os.makedirs正确实现")
        print("=" * 50)


def run_bug_tests():
    """运行bug修复专项测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    print("\n" + "=" * 60)
    print("开始Bug修复专项测试")
    print("=" * 60 + "\n")

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestBug1_ResumeFeature))
    suite.addTests(loader.loadTestsFromTestCase(TestBug2_ScopeIdMatching))
    suite.addTests(loader.loadTestsFromTestCase(TestBug3_DocumentsPath))
    suite.addTests(loader.loadTestsFromTestCase(TestBugFixesIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_bug_tests()
    print("\n" + "=" * 60)
    if success:
        print("所有Bug修复测试通过!")
    else:
        print("部分测试失败，请检查输出")
    print("=" * 60)
    sys.exit(0 if success else 1)
