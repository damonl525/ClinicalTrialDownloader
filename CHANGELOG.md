# 更新日志 (CHANGELOG)

所有重要的项目更新都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.1.0] - 2026-04-13

### 新功能
- 导出页新增 FDA 审评资料匹配：提取数据后可一键匹配 openFDA 数据库，查询临床试验对应的 FDA 审评报告
- FDA 匹配后导出 CSV 自动增加 "FDA审评资料" 和 "FDA审评资料链接" 列
- 新增 "下载FDA审评资料" 按钮，支持批量下载匹配到的 FDA 审评报告 PDF
- "全部下载(含FDA)" 同时下载试验文档和 FDA 审评资料
- 数据库页新增记录管理：支持清空所有记录和按注册中心删除记录（自动 VACUUM 回收磁盘空间）

### 改进
- 搜索页允许不填写疾病/状况、干预措施、搜索短语，仅用高级条件（阶段、招募状态、日期等）进行搜索
- 数据预览分页从 500 条/页调整为 50 条/页，改善浏览体验
- 下载超时时弹出交互对话框，支持继续等待（保持进程不中断）、跳过当前注册中心、取消全部下载
- 提取性能优化：scope_ids 过滤移至 R 层（写 CSV 前执行），仅写入目标记录而非全库数据
- 提取时始终自动包含干预措施字段，确保 FDA 匹配可用
- FDA 匹配失败时显示当前可用列名，方便排查

### 修复
- 修复"仅本次搜索结果"模式提取返回 0 行：R 层全库去重会删除 scope 需要的试验 ID，现在 scope_ids 存在时跳过 R 层去重
- 修复数据库已连接但导出页仍提示"请先连接数据库"：R 环境检测完成后不再覆盖已连接的 bridge 实例（竞态条件）
- 修复提取数据时 `.str` accessor 类型错误：phase/status 列可能为非字符串类型，添加 `.astype(str)` 前缀
- 修复"仅本次搜索结果"提取行数不足：EUCTR `_id` 含国家后缀（如 `-DE`），但 scope_ids 无后缀导致精确匹配失败，改为前缀匹配（`startsWith`）
- 修复提取数据行数丢失且概念函数值为空：`dbGetFieldsIntoDf()` 返回的原始数据库字段可能包含 list 类型（嵌套 JSON），`write.csv()` 无法处理导致 CSV 只写入部分行；现在在写入前自动将 list 列转为 JSON 字符串

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
