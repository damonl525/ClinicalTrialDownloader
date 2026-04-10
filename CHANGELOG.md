# 更新日志 (CHANGELOG)

所有重要的项目更新都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.0.0] - 2026-04-10

### 核心功能
- PySide6 现代化 GUI 界面（3 标签页布局）
  - **数据库管理**：SQLite 连接、查询历史、增量更新
  - **搜索与下载**：表单搜索、粘贴 URL、按试验 ID 下载，支持多注册中心同时搜索
  - **提取与导出**：数据提取、多维度过滤、CSV 导出、文档下载
- 支持多个临床试验注册中心：ClinicalTrials.gov (CTGOV2)、EU CTR (EUCTR)、ISRCTN、EU CTIS
- 多条件组合搜索，一次搜索跨所有注册中心
- 跨注册中心去重（基于 `dbFindIdsUniqueTrials()`）
- 注册中心过滤（提取页按 `_id` 前缀筛选）
- 文档下载支持断点续传（resume/checkpoint）
- 亮色/暗色/跟随系统主题切换
- R 环境自动检测与引导式配置

### 技术架构
- 基于子进程的 R 集成（不依赖 rpy2，解决 Windows 编码冲突）
- 基于 Jinja2 模板的 R 代码生成
- 服务层拆分（`ExtractService`、`DownloadService`）从 UI 中解耦业务逻辑
- `ctrdata/` 子包结构：bridge、process、connection、search_query、search_download、extract、documents、template_loader
- 异常体系：`CtrdataError` → `DatabaseError` / `QueryError` / `NetworkError`
- QSettings 持久化（主题、默认路径、日志设置）

### 技术栈
- Python 3.10+ / PySide6 (LGPL)
- R 4.0+ / ctrdata / nodbi / RSQLite
- pandas, Pillow, qtawesome, pyqtdarktheme
