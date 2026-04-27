# 更新日志 (CHANGELOG)

所有重要的项目更新都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.4.2] - 2026-04-27

### 新功能
- **Protocol 文档本地过滤**：导出页过滤区新增「仅含Protocol文档」选项，基于数据库元数据过滤（`hasProtocol` 字段），零网络请求，秒级完成
- **搜索页联动**：搜索页的「仅含Protocol文档的试验」勾选后，下载完成自动在导出页启用 Protocol 过滤并显示过滤结果

### 改进
- **文档下载引擎切换**：从单 R session 批量模式切换为逐 trial 独立 R 子进程模式，每个 trial 超时隔离，单个 trial 网络卡死不会阻塞整个下载队列
- **总超时提升**：文档下载总超时从 2 小时（7200 秒）提升至 24 小时（86400 秒），支持大规模下载
- **Resume 断点续传增强**：新增 `in_progress` 状态追踪，进程被 kill 后可精确恢复中断位置，避免重复下载已完成的 trial
- **单 trial 超时上限提升**：设置中单 trial 下载超时上限从 600 秒提升至 900 秒
- **Bridge resume 逻辑去重**：`CtrdataBridge` 的 resume 方法委托到 `documents.py` 模块函数，消除两套并行实现

### 修复
- **Protocol 扫描超时问题**：移除下载阶段基于网络的 `scan_document_availability` 调用（对大数据集会超时失败导致 Protocol 过滤完全失效），改为提取阶段基于数据库元数据的本地过滤
- **提取页取消按钮无反应**：`_cancel_extract()` 现在立即更新 UI（禁用按钮、重置进度条、显示「已取消」），而非只调用 `bridge.cancel()` 不更新界面

## [1.4.1] - 2026-04-25

### 新功能
- **自定义日期输入组件 `DateEdit`**：替换全局 10 个 `QDateEdit`，支持直接输入日期（如 `2025-01-01`），内置日历弹窗和清除按钮
- **日历弹窗年月快速选择**：年份/月份使用下拉框直接选择，替代 Qt 默认的箭头翻页方式
- **主题感知样式**：DateEdit 和日历弹窗自动适配亮色/暗色主题，聚焦时蓝色边框高亮，无效输入红色闪框提示

### 改进
- 统一日期输入外观：DateEdit 整体呈现为单一输入框（内嵌 `▾` 日历按钮 + `×` 清除按钮），与 QComboBox 风格一致
- 简化标签页布局：移除各标签页重复的 `_make_date_edit()` 工厂方法和独立清除按钮，统一使用 `DateEdit` 组件
- 日期值读取简化：`date_str()` / `setDateString()` 替代原有的 `_date_val()` / `_restore_date()` 辅助方法

## [1.4.0] - 2026-04-24

### 新功能
- **CDE 上市药品信息标签页**：新增第 5 个标签页，直接搜索 CDE（国家药监局药审中心）上市药品目录，支持关键词搜索和日期/类型筛选
- **CDE 审评文档下载**：支持批量下载审评报告和说明书 PDF，通过 QWebEngine 绕过瑞数 WAF
- **CDE 客户端筛选**：支持日期范围、药品类型、申请类型、注册分类等客户端筛选条件

### 改进
- CDE 日期筛选字段名修正：API 返回 `createddate`（双 d），修正后日期筛选功能正常
- 详情页加载等待时间从 3 秒增加到 5 秒，附件提取增加重试机制（最多 3 次，每次间隔 3 秒）
- 下载器复用单个 QWebEnginePage 保持 WAF 会话，用 `_active_downloads` 字典追踪下载状态

### 修复
- 修复 CDE 详情页 PDF 链接提取失败：原 JS 查找 `a[href*=".pdf"]` 但 CDE 详情页附件为 `a.textLink` 元素，需读取 `data-fileid`/`data-acceptid` 属性构建下载 URL
- 修复 `_detail_pdf_map` 键不匹配：统一用 detail_url 作 key
- 修复 URL 分类逻辑：使用 scraper 返回的 doc_type 字段而非 URL 内容过滤
- 修复 CDE PDF 下载器每次创建新 QWebEnginePage 导致第二次下载失败
- 修复 `_start_pdf_downloads` 双重调用导致下载量翻倍
- 修复代码中重复的 `docs.append()` 块导致每个文件被添加两次到下载队列

## [1.3.0] - 2026-04-23

### 新功能
- **独立 FDA 标签页**：FDA 审评资料功能从原"提取与导出"标签页中独立出来，成为独立的第 4 个标签页，无需数据库或 R 环境，直接搜索 openFDA 并下载审评文档
- **FDA 审评文档 TOC 解析**：使用 QWebEnginePage 加载 FDA TOC.html 页面，提取 pdfFiles JavaScript 变量精确确认存在的 PDF，取代盲猜 7-suffix 展开方式
- **FDA 审评文档直接下载**：通过 QWebEngineProfile.downloadRequested 绕过 FDA Akamai CDN 的 bot 检测，支持批量下载审评 PDF
- **下载进度条**：FDA 下载集成 ProgressPanel，显示进度、ETA、取消按钮
- **保存路径输入框**：FDA 标签页常驻"保存到"路径输入 + 浏览按钮，默认路径与数据库路径一致，持久化到 QSettings
- **文档类型英文显示**：表格中文档类型列改为显示原始英文名称（如 Medical Review、Statistical Review）

### 改进
- **下载限流策略**：随机 8-15 秒间隔模拟人类操作，连续 2 次失败后自动冷却 60 秒，单文件 150 秒超时
- **TOC 解析重试**：首次加载失败或超时自动重试一次，超时从 20 秒提升到 40 秒
- **右键菜单保留浏览器打开**：主按钮改为"批量下载"，右键菜单仍可单独"在浏览器中打开"
- **所有 FDA 操作记录到运行日志**：搜索、TOC 解析、下载的每个步骤均有日志

### 修复
- 修复 URL 构建缺少路径前缀导致去重失败的问题
- 修复重复的 `_on_search_error` 方法

## [1.2.0] - 2026-04-21

### 新功能
- **ProgressPanel 统一进度组件**：ETA 预计剩余时间、详情行、取消按钮，支持所有标签页
- **无缝衔接流程**：搜索下载完成后自动切换到导出标签页并自动提取数据
- **批量文档下载**：单 R Session 处理 N 个试验，消除逐个试验重复冷启动开销
- **断点续传 UI**：检测到中断下载时弹窗提示用户选择继续或重新开始
- **超时设置生效**：文档下载超时现从设置中读取（之前硬编码 120s）

### 改进
- R 输出轮询间隔从 5s 缩短至 0.5s，响应更快
- 下载前必须确认，避免误操作触发下载

### 修复
- 修复导出页重复取消按钮（独立 QPushButton 与 ProgressPanel 内置取消按钮重复）
- 修复提取完成后进度条继续转圈不停止
- 修复 list 类型列导致提取数据行丢失
- 修复文档下载偶尔卡死无响应（添加 stall_timeout）

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
