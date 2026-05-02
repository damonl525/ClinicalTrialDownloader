# 更新日志 (CHANGELOG)

所有重要的项目更新都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.4.5] - 2026-05-02

### 修复
- **EUCTR 文档下载全部跳过**：163/163 条 EUCTR 试验文档下载全部显示"跳过"，根因：`download_one_trial_doc.R` 模板缺少 `euctrresults=TRUE` 和 `register="EUCTR"` 参数，且 queryterm 格式错误（传入含国家后缀的完整 _id 而非 `query={eudract_number}` 格式）。新增 `_download_euctr_trial_doc()` 专用函数和 `download_euctr_trial_doc.R` 模板，正确处理 EUCTR 文档下载
- **CTIS 文档下载同样跳过**：与 EUCTR 同理，通用模板未指定 `register="CTIS"`，ctrdata 无法从纯数字 ID 识别注册中心。新增 `_download_ctis_trial_doc()` 和 `download_ctis_trial_doc.R` 模板，显式指定 `register="CTIS"`（支持 `documents.regexp`）
- **EUCTR 日期过滤结果不变**：不同日期范围（如 2026-01-01~ 和 2026-04-01~）提取 EUCTR 数据返回相同行数（163 行），根因：旧代码 `| df[".startDate"].isna()` 保留所有空日期行。改用 _id 年份作为 fallback（`YYYY-07-01`），EUCTR _id 前 4 位即试验年份
- **下载取消摘要对话框**：取消下载后弹出摘要对话框，显示已完成/跳过/失败数量

### 改进
- **CSV 导出默认路径**：导出 CSV 默认保存到文档下载目录，而非数据库所在目录
- **注册中心识别算法改进**：`classify_registry()` 改用第二段首字符区分 EUCTR（`0` 开头）和 CTIS（`5` 开头），不再依赖年份+末段数字的不可靠启发式，避免 EUCTR 2022+ 数字国家代码被误判为 CTIS
- **EUCTR/CTIS 搜索与下载提醒**：搜索页勾选 EUCTR/CTIS 时弹确认窗提醒数据不完整；提取页文档下载时自动过滤 EUCTR/CTIS，弹窗说明限制并仅下载 CTGOV2/ISRCTN 文档
- **右键「在浏览器中打开」**：提取页表格右键菜单新增「在浏览器中打开」，直接打开对应注册中心试验页面（CTGOV2/EUCTR/ISRCTN/CTIS 四个注册中心均支持）
- **空结果提示优化**：提取结果为空时，根据是否勾选 Protocol 显示不同提示消息，避免误导

### 已知限制
- **EUCTR 概念函数字段为空**：`f.startDate`、`f.statusRecruitment`、`interventions` 对 EUCTR 数据全部为空，仅 `f.trialPhase` 有值。这是 ctrdata 限制，EUCTR 字段结构不兼容这些概念函数
- **EUCTR 文档无法按类型筛选**：ctrdata 对 EUCTR 不支持 `documents.regexp`，所有文档都会被下载
- **EUCTR 日期筛选精度有限**：EUCTR `.startDate` 为空，日期筛选使用 `_id` 前四位（注册年份）做近似，精度仅到年份

## [1.4.4] - 2026-04-30

### 新功能
- **下载跳过已有文件**：提取页文档下载、FDA 审评文档下载、CDE 审评文档下载三个模块，遇到目标目录已有同名文件时自动跳过，日志逐条记录，最终统计展示跳过数量
- **Protocol 多注册中心预过滤**：Protocol 文档过滤扩展支持 ISRCTN（通过 `attachedFiles` 文件名匹配），不再仅限于 CTGOV2；新增 `classify_registry()` 辅助函数按 ID 格式识别注册中心
- **Protocol 过滤范围选择对话框**：勾选 Protocol 过滤后弹窗让用户选择「仅 CTGOV2 + ISRCTN（推荐）」或「全部注册中心（含 CTIS/EUCTR）」，CTIS/EUCTR 因无文档元数据将纳入全部记录；搜索后自动提取和手动提取均会弹窗确认，用户取消时有日志反馈
- **ISRCTN 直接文档下载**：ISRCTN 文档下载绕过 R ctrdata 的 chromote 依赖，通过 ISRCTN 公开 XML API (`/api/trial/{id}/format/default`) 获取文件下载 URL，Python urllib 直接下载。不再需要安装 R chromote 包，解决了 ctrdata 对部分 ISRCTN 试验报告"No documents identified"的问题

### 改进
- **R 子进程错误日志增强**：R streaming 输出 `ERROR\t` 行时记录 `logger.warning()`，不再静默丢弃，便于诊断下载失败
- **提取 SQL 输入转义**：scope extraction 的 LIKE 子句对单引号和 SQL 通配符进行转义（防御性编程）
- **移除空实现分页按钮**：CDE 页移除无功能的上一页/下一页按钮，保留「爬取全部页」复选框
- **全选仅操作可见行**：表格全选/取消全选仅操作当前筛选后的可见行，隐藏行保持原状
- **Protocol 查询日志改进**：日志分别显示 CTGOV2 和 ISRCTN 的 Protocol 匹配数量，便于诊断
- **Protocol 查询错误隔离**：CTGOV2 和 ISRCTN 的 R 查询使用独立 tryCatch，单个注册中心查询失败不影响另一个
- **提取后过滤诊断日志**：每个 post-extraction 过滤器（阶段/状态/日期/适应症/干预措施）记录行数变化，便于定位行数骤减原因
- **chromote R 包检测**：环境检测页新增 chromote 包版本显示；安装提示包含 chromote

### 修复
- **Protocol 预过滤遗漏非 CTGOV2 记录**：搜索 4508 条跨 4 个注册中心的试验，Protocol 过滤仅返回 63 条 CTGOV2 记录，ISRCTN 的 Protocol 记录完全丢失。根因：`protocol_query.R` 仅查询 CTGOV2 独有的 `hasProtocol` 字段
- **ISRCTN Protocol 查询列名错误**：`dbGetFieldsIntoDf` 返回列名 `"attachedFiles.attachedFile"` 而非 `"attachedFiles"`，导致 ISRCTN 文件检测始终为 0
- **ISRCTN 文档下载失败**：ctrdata 对部分 ISRCTN 试验报告"No documents identified"，但 ISRCTN 网站实际有 Protocol 文件。改用 Python 直接下载绕过此问题
- **全库模式 Protocol 过滤缺少 EUCTR/CTIS**：全库模式下选择「全部注册中心」时，使用 `get_all_trial_ids()` 获取所有 ID（非去重），确保 EUCTR/CTIS 记录被正确纳入
- **缺失 jinja2 依赖**：`requirements.txt` 未列出 `jinja2`，全新环境 `pip install -r requirements.txt` 后 import 直接崩溃
- **仓库清理**：删除根目录 debug 脚本和临时日志文件，`.gitignore` 增加规则防止再次提交

## [1.4.3] - 2026-04-29

### 改进
- **增量更新支持取消**：Database Tab 增量更新运行中显示「取消更新」按钮，通过 `bridge.cancel()` 终止 R 子进程；更新期间禁用所有「增量更新」按钮防止并发
- **增量更新 EUCTR/CTIS 限制提示**：确认对话框新增注册中心特定警告（EUCTR 7 天窗口限制、CTIS 无高效增量 API）
- **Database Tab UI 线程安全**：`get_db_info()` 调用移至后台线程（`_on_update_complete` 和 `_on_delete_complete`），通过 `_db_info_loaded` 信号回传，避免主线程冻结
- **CLAUDE.md 更新**：补充五标签页架构、per-trial R 子进程、queue-based 超时 IPC、QWebEngine 等关键设计说明
- **FDA 搜索支持纯日期查询**：移除药物名称必填限制，支持仅输入日期范围、高级筛选条件进行搜索（药物名称、日期、高级筛选至少填一个）

### 修复
- **增量更新成功后 UI 无反馈**：Search Tab 的 `_update_last_query` 成功后未发射 `_download_complete` 信号，状态永远卡在「正在更新上次查询」。修复：捕获返回结果并发射信号，同时调用 `_set_downloading(True)` 防止并发操作
- **增量更新 R 错误被静默吞掉**：`update_last_query.R` 模板的 tryCatch 错误分支输出 `ERROR` 行后继续执行到模板底部的 JSON 输出，返回 `ok=TRUE` 的假成功。重构为 `err_msg <<-` 模式 + if/else 分支，错误时输出 `ok=FALSE` JSON
- **Service 层 `update_query()` 类型未归一化**：`success`/`failed` 字段未做类型归一化（`dict→list`, `str→[str]`），与 `form_download()` 不一致
- **增量更新 0 条记录查询瞬间无新增**：CTIS/EUCTR 查询上次下载 0 条记录时，增量更新立即返回「无新增」而非重新下载。根因：`ctrLoadQueryIntoDb(querytoupdate)` 基于时间戳增量检查，0 条记录的查询无有效基线。修复：检测 `query-records == 0` 时自动传递 `forcetoupdate = TRUE` 强制重新执行查询；处理 `NaN`/`"?"` 边界条件；Database Tab 确认对话框区分「强制重新下载」和「增量更新」文案；Search Tab 通过 Service 层查询历史自动检测

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
- **导出页操作日志**：提取（开始/完成/取消/失败）和文档下载（开始/每个trial进度/完成/取消/失败）全部写入应用日志，与搜索页一致
- **超时回调诊断日志**：搜索超时对话框增加 debug 级别日志，记录用户实际选择，便于排查超时相关问题

### 修复
- **Protocol 扫描超时问题**：移除下载阶段基于网络的 `scan_document_availability` 调用（对大数据集会超时失败导致 Protocol 过滤完全失效），改为提取阶段基于数据库元数据的本地过滤
- **提取页取消按钮无反应**：`_cancel_extract()` 现在立即更新 UI（禁用按钮、重置进度条、显示「已取消」），而非只调用 `bridge.cancel()` 不更新界面
- **搜索超时取消后 UI 卡死**：修复下载因超时被取消后 worker 线程静默返回、不触发任何 signal 导致界面永久停留在「下载中」状态的问题；现在正确发出 `_download_complete` signal 并显示「下载已取消」
- **超时对话框缺少即时反馈**：点击「跳过此注册中心」或「取消全部下载」后立即显示「正在跳过...」/「正在取消...」，而非无任何视觉反馈等待后台清理
- **Protocol 提取性能瓶颈**：修复 Protocol 过滤后提取 10 条记录仍需 84 秒的问题。原因是 SQL 临时表预过滤因 R 代码引号嵌套错误静默失败（`sprintf` 中的单引号与 LIKE 子句单引号冲突），导致 `dbGetFieldsIntoDf()` 提取全库 2026 条记录后再过滤。改用 R 双引号字符串避免引号冲突，临时表预过滤生效后提取仅处理目标记录
- **文档下载 resume 文件不区分下载目录**：断点续传文件命名仅基于数据库名，未包含下载目录标识。换目录后旧 resume 仍然生效，导致新目录跳过已完成的 trial 且不下载任何文件，但结果却显示全部成功。修复：resume 文件名纳入 `documents_path` 哈希（不同目录独立 resume），session hash 纳入目录路径，恢复时验证目标目录确实存在文件才标记为已完成
- **R 报告成功但实际无文档被误标为已下载**：`download_one_trial_doc` 的 R 子进程返回 `ok=true` 仅表示查询未报错，不代表文档已保存。现增加文件系统验证：下载后检查目标目录是否确实存在该 trial 的文档文件，无文件则标记为「未找到文档」而非「成功」
- **超时对话框「继续等待」被误判为「取消」**：根因是跨线程 Signal 通信使用 `threading.Event` + 可变 `ctx` dict 传递。PySide6 跨线程 `Signal.emit(dict)` 会对 dict 深拷贝，导致 GUI 线程修改的 `ctx["choice"]` 与 worker 线程等待的 `ctx["event"]` 属于不同对象。`event.wait()` 因拷贝隔离永远等不到信号，`ctx["choice"]` 仍为 None，`None or "cancel"` → 即使用户点击「继续」，结果也是「取消」。重写为 `queue.Queue` 机制：Signal 仅传递不可变数据（elapsed/register），queue 存储在 SearchTab 实例上（不走 Signal payload），彻底消除深拷贝问题。同时增加：dialog 异常关闭默认为 continue（非 cancel）、queue.get(timeout=300) 防止死锁、重入防护避免同时弹出多个 dialog

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
