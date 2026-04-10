#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临床试验数据下载器 - 单元测试套件

运行方式:
    python -m pytest tests/ -v
    或
    python tests/test_suite.py
"""

import unittest
import os
import sys
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from validators import InputValidator, ValidationResult, Sanitizer
    from config_manager import (
        ConfigManager,
        DatabaseConfig,
        DownloadConfig,
        QueryConfig,
    )
except ImportError as e:
    print(f"导入模块失败: {e}")
    sys.exit(1)


class TestInputValidator(unittest.TestCase):
    """输入验证器测试"""

    def test_validate_search_phrase_empty(self):
        """测试空搜索关键词"""
        result = InputValidator.validate_search_phrase("")
        self.assertFalse(result.is_valid)
        self.assertIn("不能为空", result.error_message)

    def test_validate_search_phrase_too_short(self):
        """测试过短的搜索关键词"""
        result = InputValidator.validate_search_phrase("a")
        self.assertFalse(result.is_valid)
        self.assertIn("太短", result.error_message)

    def test_validate_search_phrase_valid(self):
        """测试有效的搜索关键词"""
        result = InputValidator.validate_search_phrase("cancer")
        self.assertTrue(result.is_valid)

    def test_validate_search_phrase_chinese(self):
        """测试中文搜索关键词"""
        result = InputValidator.validate_search_phrase("癌症")
        self.assertTrue(result.is_valid)
        self.assertTrue(any("中文" in w for w in result.warnings))

    def test_validate_database_name_empty(self):
        """测试空数据库名"""
        result = InputValidator.validate_database_name("")
        self.assertFalse(result.is_valid)

    def test_validate_database_name_valid(self):
        """测试有效的数据库名"""
        result = InputValidator.validate_database_name("trials.db")
        self.assertTrue(result.is_valid)

    def test_validate_database_name_invalid_chars(self):
        """测试包含非法字符的数据库名"""
        result = InputValidator.validate_database_name("test:dba.db")
        self.assertFalse(result.is_valid)
        self.assertIn("非法字符", result.error_message)

    def test_validate_nct_id_valid(self):
        """测试有效的NCT ID"""
        result = InputValidator.validate_nct_id("NCT01234567")
        self.assertTrue(result.is_valid)

    def test_validate_nct_id_invalid(self):
        """测试无效的NCT ID"""
        result = InputValidator.validate_nct_id("NCT123")
        self.assertFalse(result.is_valid)

    def test_validate_regex_valid(self):
        """测试有效的正则表达式"""
        result = InputValidator.validate_regex(r".*\.pdf$")
        self.assertTrue(result.is_valid)

    def test_validate_regex_invalid(self):
        """测试无效的正则表达式"""
        result = InputValidator.validate_regex(r"[invalid")
        self.assertFalse(result.is_valid)

    def test_validate_register_selection_empty(self):
        """测试空的注册中心选择"""
        result = InputValidator.validate_register_selection([])
        self.assertFalse(result.is_valid)

    def test_validate_register_selection_valid(self):
        """测试有效的注册中心选择"""
        result = InputValidator.validate_register_selection(["EUCTR", "CTGOV2"])
        self.assertTrue(result.is_valid)

    def test_validate_register_selection_invalid(self):
        """测试无效的注册中心"""
        result = InputValidator.validate_register_selection(["INVALID"])
        self.assertFalse(result.is_valid)


class TestSanitizer(unittest.TestCase):
    """清理器测试"""

    def test_sanitize_search_phrase(self):
        """测试搜索关键词清理"""
        result = Sanitizer.sanitize_search_phrase("  cancer  ")
        self.assertEqual(result, "cancer")

    def test_sanitize_search_phrase_control_chars(self):
        """测试移除控制字符"""
        result = Sanitizer.sanitize_search_phrase("cancer\x00test")
        self.assertEqual(result, "cancertest")

    def test_sanitize_filename(self):
        """测试文件名清理"""
        result = Sanitizer.sanitize_filename("test:file.txt")
        self.assertEqual(result, "test_file.txt")

    def test_sanitize_filename_empty(self):
        """测试空文件名"""
        result = Sanitizer.sanitize_filename("")
        self.assertEqual(result, "unnamed")

    def test_sanitize_path(self):
        """测试路径清理"""
        result = Sanitizer.sanitize_path("C:\\test\\path")
        self.assertIn("test", result)
        self.assertIn("path", result)


class TestConfigManager(unittest.TestCase):
    """配置管理器测试"""

    def setUp(self):
        """创建临时配置目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, "test_config.json")
        self.config_manager = ConfigManager(self.config_path)

    def tearDown(self):
        """清理临时目录"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_default_config(self):
        """测试加载默认配置"""
        config = self.config_manager.load()
        self.assertIsNotNone(config)
        self.assertIn("database", config)

    def test_save_and_load_config(self):
        """测试保存和加载配置"""
        self.config_manager.set("database.default_db_name", "new_trials.db")
        self.config_manager.save()

        new_manager = ConfigManager(self.config_path)
        new_manager.load()

        self.assertEqual(new_manager.get("database.default_db_name"), "new_trials.db")

    def test_get_nested_value(self):
        """测试获取嵌套值"""
        value = self.config_manager.get("database.save_interval_minutes")
        self.assertEqual(value, 30)

    def test_get_nonexistent_value(self):
        """测试获取不存在的值"""
        value = self.config_manager.get("nonexistent.key", "default")
        self.assertEqual(value, "default")

    def test_database_config_property(self):
        """测试数据库配置属性"""
        db_config = self.config_manager.database
        self.assertIsInstance(db_config, DatabaseConfig)
        self.assertEqual(db_config.default_db_name, "trials.db")

    def test_download_config_property(self):
        """测试下载配置属性"""
        download_config = self.config_manager.download
        self.assertIsInstance(download_config, DownloadConfig)
        self.assertEqual(download_config.max_retries, 3)

    def test_reset_config(self):
        """测试重置配置"""
        self.config_manager.set("database.custom_value", "test")
        self.config_manager.save()

        config_before = ConfigManager(self.config_path)
        config_before.load()
        self.assertEqual(config_before.get("database.custom_value"), "test")

        self.config_manager.reset()

        new_manager = ConfigManager(self.config_path)
        new_manager.load()
        self.assertIsNone(new_manager.get("database.custom_value"))


class TestValidationResult(unittest.TestCase):
    """验证结果测试"""

    def test_validation_result_creation(self):
        """测试创建验证结果"""
        result = ValidationResult(True)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.error_message, "")
        self.assertEqual(result.warnings, [])

    def test_validation_result_with_error(self):
        """测试带错误的验证结果"""
        result = ValidationResult(False, "错误信息")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_message, "错误信息")

    def test_validation_result_with_warnings(self):
        """测试带警告的验证结果"""
        result = ValidationResult(True, warnings=["警告1", "警告2"])
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.warnings), 2)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestInputValidator))
    suite.addTests(loader.loadTestsFromTestCase(TestSanitizer))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManager))
    suite.addTests(loader.loadTestsFromTestCase(TestValidationResult))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
