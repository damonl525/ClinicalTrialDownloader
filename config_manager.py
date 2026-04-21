#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
# LEGACY: not wired into PySide6 main app flow. Used by legacy tkinter GUI only.
配置管理和验证模块

提供配置加载、保存和验证功能
"""

import json
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DatabaseConfig:
    """数据库配置"""

    last_save_path: str = ""
    auto_save_enabled: bool = True
    save_interval_minutes: int = 30
    last_auto_save: Optional[str] = None
    default_db_name: str = "trials.db"


@dataclass
class DownloadConfig:
    """下载配置"""

    default_docs_path: str = "./documents"
    default_filter: str = "PDF和协议文档"
    custom_filter: str = r".*\.(pdf|doc|docx)$"
    max_retries: int = 3
    timeout_seconds: int = 30


@dataclass
class QueryConfig:
    """查询配置"""

    default_registers: List[str] = field(default_factory=lambda: ["EUCTR", "CTGOV2"])
    default_phase: str = ""
    default_status: str = ""


class ConfigValidator:
    """配置验证器"""

    @staticmethod
    def validate_db_config(config: Dict[str, Any]) -> tuple[bool, List[str]]:
        """验证数据库配置"""
        errors = []

        if "save_interval_minutes" in config:
            interval = config["save_interval_minutes"]
            if not isinstance(interval, int) or interval < 1:
                errors.append("save_interval_minutes must be a positive integer")

        if "auto_save_enabled" in config:
            if not isinstance(config["auto_save_enabled"], bool):
                errors.append("auto_save_enabled must be a boolean")

        return len(errors) == 0, errors

    @staticmethod
    def validate_download_config(config: Dict[str, Any]) -> tuple[bool, List[str]]:
        """验证下载配置"""
        errors = []

        if "max_retries" in config:
            retries = config["max_retries"]
            if not isinstance(retries, int) or retries < 0:
                errors.append("max_retries must be a non-negative integer")

        if "timeout_seconds" in config:
            timeout = config["timeout_seconds"]
            if not isinstance(timeout, int) or timeout < 1:
                errors.append("timeout_seconds must be a positive integer")

        return len(errors) == 0, errors

    @staticmethod
    def validate_path(path: str, must_exist: bool = False) -> tuple[bool, str]:
        """验证路径"""
        if not path:
            return False, "Path cannot be empty"

        if must_exist and not os.path.exists(path):
            return False, f"Path does not exist: {path}"

        return True, ""


class ConfigManager:
    """配置管理器"""

    DEFAULT_CONFIG = {
        "database": DatabaseConfig().__dict__,
        "download": DownloadConfig().__dict__,
        "query": QueryConfig().__dict__,
        "export": {
            "last_scope": "current_search",
            "last_concepts": [
                "f.statusRecruitment",
                "f.trialPhase",
                "f.trialTitle",
                "f.startDate",
            ],
        },
        "gui": {
            "window_size": [950, 720],
            "advanced_expanded": True,
        },
        "version": "1.2.0",
        "last_modified": None,
    }

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "config.json"
            )
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        """加载配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)

                self._migrate_config()
                return self._config
            except Exception as e:
                print(f"加载配置失败: {e}，使用默认配置")
                import copy

                self._config = copy.deepcopy(self.DEFAULT_CONFIG)
        else:
            import copy

            self._config = copy.deepcopy(self.DEFAULT_CONFIG)

        return self._config

    def save(self) -> bool:
        """保存配置"""
        try:
            self._config["last_modified"] = datetime.now().isoformat()

            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=4)

            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> bool:
        """设置配置值"""
        keys = key.split(".")
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value
        return self.save()

    def _migrate_config(self) -> None:
        """迁移旧版本配置"""
        if "last_save_path" in self._config:
            if "database" not in self._config:
                self._config["database"] = DatabaseConfig().__dict__

            if not self._config["database"].get("last_save_path"):
                self._config["database"]["last_save_path"] = self._config.pop(
                    "last_save_path", ""
                )

            if not self._config["database"].get("auto_save_enabled"):
                self._config["database"]["auto_save_enabled"] = self._config.pop(
                    "auto_save_enabled", True
                )

            if not self._config["database"].get("save_interval_minutes"):
                self._config["database"]["save_interval_minutes"] = self._config.pop(
                    "save_interval_minutes", 30
                )

        if "version" not in self._config:
            self._config["version"] = "1.0.0"

    def reset(self) -> bool:
        """重置为默认配置"""
        import copy

        self._config = copy.deepcopy(self.DEFAULT_CONFIG)
        return self.save()

    @property
    def database(self) -> DatabaseConfig:
        """获取数据库配置"""
        return DatabaseConfig(**self._config.get("database", DatabaseConfig().__dict__))

    @property
    def download(self) -> DownloadConfig:
        """获取下载配置"""
        return DownloadConfig(**self._config.get("download", DownloadConfig().__dict__))

    @property
    def query(self) -> QueryConfig:
        """获取查询配置"""
        return QueryConfig(**self._config.get("query", QueryConfig().__dict__))


if __name__ == "__main__":
    config = ConfigManager()
    print("当前配置:")
    print(json.dumps(config._config, indent=2, ensure_ascii=False))
