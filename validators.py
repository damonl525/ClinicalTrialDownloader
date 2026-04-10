#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输入验证工具模块

提供各种输入验证功能
"""

import re
import os
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """验证结果"""

    is_valid: bool
    error_message: str = ""
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class InputValidator:
    """输入验证器"""

    @staticmethod
    def validate_search_phrase(phrase: str) -> ValidationResult:
        """验证搜索关键词"""
        warnings = []

        if not phrase or not phrase.strip():
            return ValidationResult(False, "搜索关键词不能为空")

        phrase = phrase.strip()

        if len(phrase) < 2:
            return ValidationResult(False, "搜索关键词太短（至少2个字符）")

        if len(phrase) > 200:
            warnings.append("搜索关键词较长，可能影响查询结果")

        if re.match(r"^[a-zA-Z0-9\s\-\_\.\+\%]+$", phrase):
            pass
        elif re.match(r"^[\u4e00-\u9fff\s\-\_\.\+\%]+$", phrase):
            warnings.append("检测到中文关键词，部分注册中心可能不支持")
        else:
            warnings.append("关键词包含特殊字符，可能需要URL编码")

        return ValidationResult(True, warnings=warnings)

    @staticmethod
    def validate_database_name(name: str) -> ValidationResult:
        """验证数据库名称"""
        if not name or not name.strip():
            return ValidationResult(False, "数据库名称不能为空")

        name = name.strip()

        if len(name) > 255:
            return ValidationResult(False, "数据库名称过长")

        invalid_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
        for char in invalid_chars:
            if char in name:
                return ValidationResult(False, f"数据库名称包含非法字符: {char}")

        if not name.lower().endswith(".db"):
            return ValidationResult(True, warnings=["建议使用 .db 扩展名"])

        return ValidationResult(True)

    @staticmethod
    def validate_file_path(
        path: str, must_exist: bool = False, must_be_writable: bool = False
    ) -> ValidationResult:
        """验证文件路径"""
        if not path or not path.strip():
            return ValidationResult(False, "路径不能为空")

        path = os.path.abspath(path)

        if must_exist and not os.path.exists(path):
            return ValidationResult(False, f"路径不存在: {path}")

        if must_be_writable:
            parent_dir = os.path.dirname(path)
            if not os.path.exists(parent_dir):
                try:
                    os.makedirs(parent_dir, exist_ok=True)
                except Exception as e:
                    return ValidationResult(False, f"无法创建目录: {e}")

            if os.path.exists(path):
                if not os.access(path, os.W_OK):
                    return ValidationResult(False, f"文件不可写: {path}")
            else:
                try:
                    with open(path, "w") as f:
                        pass
                    os.remove(path)
                except Exception as e:
                    return ValidationResult(False, f"无法创建文件: {e}")

        return ValidationResult(True)

    @staticmethod
    def validate_directory_path(
        path: str, must_exist: bool = False, must_be_writable: bool = False
    ) -> ValidationResult:
        """验证目录路径"""
        if not path or not path.strip():
            return ValidationResult(False, "目录路径不能为空")

        path = os.path.abspath(path)

        if must_exist and not os.path.exists(path):
            return ValidationResult(False, f"目录不存在: {path}")

        if must_be_writable or must_exist:
            if os.path.exists(path):
                if not os.access(path, os.W_OK):
                    return ValidationResult(False, f"目录不可写: {path}")
            else:
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    return ValidationResult(False, f"无法创建目录: {e}")

        return ValidationResult(True)

    @staticmethod
    def validate_regex(pattern: str) -> ValidationResult:
        """验证正则表达式"""
        if not pattern:
            return ValidationResult(False, "正则表达式不能为空")

        try:
            re.compile(pattern)
            return ValidationResult(True)
        except re.error as e:
            return ValidationResult(False, f"无效的正则表达式: {e}")

    @staticmethod
    def validate_register_selection(registers: List[str]) -> ValidationResult:
        """验证注册中心选择"""
        if not registers:
            return ValidationResult(False, "请至少选择一个注册中心")

        valid_registers = {"EUCTR", "CTGOV2", "ISRCTN", "CTIS", "JPRN", "NCT"}
        invalid = [r for r in registers if r not in valid_registers]

        if invalid:
            return ValidationResult(False, f"无效的注册中心: {', '.join(invalid)}")

        return ValidationResult(True)

    @staticmethod
    def validate_field_selection(fields: List[str]) -> ValidationResult:
        """验证字段选择"""
        if not fields:
            return ValidationResult(False, "请至少选择一个字段")

        return ValidationResult(True)

    @staticmethod
    def validate_nct_id(nct_id: str) -> ValidationResult:
        """验证NCT ID格式"""
        if not nct_id:
            return ValidationResult(False, "NCT ID不能为空")

        pattern = r"^NCT\d{8}$"
        if not re.match(pattern, nct_id.upper()):
            return ValidationResult(
                False, f"NCT ID格式无效，应为8位数字，如: NCT01234567"
            )

        return ValidationResult(True)

    @staticmethod
    def validate_url(url: str) -> ValidationResult:
        """验证URL格式"""
        if not url:
            return ValidationResult(False, "URL不能为空")

        url_pattern = re.compile(
            r"^https?://"
            r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
            r"localhost|"
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
            r"(?::\d+)?"
            r"(?:/?|[/?]\S+)$",
            re.IGNORECASE,
        )

        if not url_pattern.match(url):
            return ValidationResult(False, f"无效的URL格式: {url}")

        return ValidationResult(True)


class Sanitizer:
    """输入清理器"""

    @staticmethod
    def sanitize_search_phrase(phrase: str) -> str:
        """清理搜索关键词"""
        if not phrase:
            return ""

        phrase = phrase.strip()

        phrase = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", phrase)

        return phrase

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """清理文件名"""
        if not filename:
            return "unnamed"

        filename = filename.strip()

        invalid_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
        for char in invalid_chars:
            filename = filename.replace(char, "_")

        filename = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", filename)

        if len(filename) > 255:
            name, ext = os.path.splitext(filename)
            filename = name[: 255 - len(ext)] + ext

        return filename or "unnamed"

    @staticmethod
    def sanitize_path(path: str) -> str:
        """清理路径"""
        if not path:
            return ""

        path = path.strip()

        path = os.path.normpath(path)

        return path


if __name__ == "__main__":
    print("测试验证器...")

    result = InputValidator.validate_search_phrase("cancer")
    print(f"验证'cancer': {result.is_valid}")

    result = InputValidator.validate_database_name("trials.db")
    print(f"验证'trials.db': {result.is_valid}")

    result = InputValidator.validate_nct_id("NCT01234567")
    print(f"验证'NCT01234567': {result.is_valid}")
