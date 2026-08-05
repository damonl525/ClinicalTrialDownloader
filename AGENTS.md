# AGENTS.md

工作区级 ZCode agent 指南。完整架构/R 集成细节见 **`CLAUDE.md`**（权威、更详尽），本文件只记录关键事实与红线。

## 项目

临床试验数据下载器（PySide6 桌面 GUI + R `ctrdata` 包）。从 CTGOV2 / EUCTR / ISRCTN / EU CTIS 检索、下载、提取临床试验数据，导出 CSV 并按需下载文档（protocol/SAP 等）。另含两个**独立 tab**：FDA（openFDA）和 CDE（国家药监局药审中心），二者**无需 R/数据库**。

- 版本：`APP_VERSION` 在 `core/constants.py`（当前 1.5.3）。`version_info.txt` 与 `build.spec` 由 `build.py` 自动生成——**不要手改**。
- 作者：Damon Liang。UI 文案为中文，变量/函数/文件名用英文。

## 常用命令

```bash
python main.py                 # 启动 PySide6 UI（默认）
python main.py --ui legacy     # 回退到 tkinter 旧 UI
python -m pytest tests/ -v     # 推荐测试入口
python tests/test_suite.py     # 仅覆盖 legacy validators/config
ruff check .                   # lint，无配置文件
pip install -r requirements.txt

# R 依赖（R 控制台，手动）
install.packages(c("ctrdata", "nodbi", "RSQLite", "chromote"))

# 打包 Windows exe（PyInstaller）。新数据文件/隐藏导入必须改 build.py，不要改 build.spec
python build.py                # onedir
python build.py --onefile      # 单 exe
python build.py --clean        # 先清 build/ dist/
```

本地 R 4.5.1 路径（Damon 机器）：`C:\Users\Liang JianLin\AppData\Local\Programs\R\R-4.5.1\`。

## 目录与分层（改代码前必读）

- `ui/` — PySide6 主 UI。`main_window.py` 是共享状态枢纽（`bridge` / `filtered_ids` / `current_data` 等）。`ui/tabs/` 五个 tab，`ui/widgets/` 复用控件，`ui/theme.py` QSS 设计系统。
- `ctrdata/` — **Python→R 桥接层**。`bridge.py` 是 facade，按职责拆到 `process.py` / `search*.py` / `extract.py` / `documents.py` / `isrctn_download.py` / `template_loader.py` 等。
- `service/` — **业务逻辑层（在用，非占位）**：FDA / CDE 服务 + 从 tab 抽出的 Qt-free 编排（`download_service.py`、`extract_service.py`），便于脱离 Qt 单测。
- `core/` — `constants.py`（映射 / `APP_VERSION` / `classify_registry()`）、`exceptions.py`（`CtrdataError` + `DownloadTimeoutError`）、`logger.py` / `log_handler.py`。
- `gui/` — 旧 tkinter UI（`--ui legacy` 路径）。`config_manager.py` / `validators.py` 是 **legacy**，PySide6 主流程用 QSettings，勿在新代码里接 `ConfigManager`。
- `ctrdata/templates/` — **`.R` Jinja2 模板**，所有 R 代码来自这里。

**分层红线**：业务逻辑下沉到 `service/`，便于单测；UI 层只保留信号与日志。不要把 R 字符串拼回 tab。

## R 集成（最易踩坑）

- **不用 rpy2**（Windows V8 编码冲突）。用 `subprocess` 调 `Rscript.exe`，封装在 `ctrdata/process.py` 的 `run_r` / `run_r_json` / `run_r_streaming`。
- **R 代码必须走 Jinja2 模板**：`template_loader.render(name, **vars)`。模板用自定义分隔符 `{{ }}` / `{% %}`，让 R 的 `$` / `{` 原样通过。**绝对不要**把 R 写进 Python f-string（命令行编码会炸）。优先把值作为 Jinja2 变量传，少用 `_r_escape()` 手动转义。
- 数据交换：结构化结果用 JSON 行（`run_r_json` 自下而上扫首个 `{`/`[` 行）；表格用临时 CSV。
- 子进程在 Windows 一律 `CREATE_NO_WINDOW` + 隐藏控制台。
- **超时**：`run_r_streaming(timeout=, stall_timeout=, on_timeout=)`；`stall_timeout` 杀无 stdout 的进程；`on_timeout` 回调最多续期 `_MAX_TIMEOUT_CONTINUES=3` 次后强杀（抛 `DownloadTimeoutError`）。独立线程 drain stderr 防 64KB 管道死锁。
- 文档下载按注册中心路由（`classify_registry()`）：ISRCTN→HTTP XML API（不走 R）；EUCTR→R `euctrresults=TRUE`，**不支持 `documents.regexp`**，全量下载；CTIS→R `register="CTIS"`，无公开 API、慢/易超时；CTGOV2→标准 R + `documents.regexp`。

## PySide6 / Qt 红线

- **QWebEngine（FDA/CDE）必须主线程跑**（Qt 事件循环）。FDA 用 QWebEngineProfile 绕 Akamai CDN 反爬，限速下载（随机 8–15s，连续失败 60s 冷却）；CDE 绕瑞数 WAF。
- **跨线程超时对话框**：用 widget 实例上的 `queue.Queue` 传递，**不要**塞进 `Signal.emit(dict)`（PySide6 会深拷贝，破坏 `threading.Event` / 可变引用）。
- R 子进程调用：`threading.Thread(daemon=True)` + Qt Signal/Slot 保证线程安全。`bridge._current_process` 持有当前 R 进程，`cancel()` → `kill()` + `wait(timeout=5)`。
- 持久化用 **QSettings**（Windows 注册表）：org `ClinicalTrialDownloader`/`App`（主题/最近 db）、`ctrdata_downloader`/`MainWindow`（日志/guide）。
- `CollapsibleCard` 用 objectName QSS（`collapsibleHeader`/`collapsibleBody`）适配主题。

## 关键模式

- **两阶段下载**：Phase 1 只下数据（`documents.path=NULL`）；Phase 2 仅为过滤后的 trial 下文档，每个 trial 独立 R 子进程 + 独立超时（CTGOV2 已优化为单 session 批量）。
- **断点续传**：进度存 `{db_dir}/{db_basename}_{path_slug}_doc_resume.json`，`path_slug = md5(abspath(documents_path))[:8]`（目录隔离）；session hash 在 trial 集合变化时失效 checkpoint。`os.replace()` 原子写，每个 trial 完成后更新；落盘前校验文件存在。
- **提取后过滤**：phase/status/date/condition/intervention 在 Python/pandas 做，不在 R。`str.contains` 一律加 `regex=False`（防 `phase 2+4` 的 `+` 被当元字符）。EUCTR 日期缺失时用 `_id` 前 4 位年份近似，严格模式不复原。
- **概念函数**：`f.*`（如 `f.trialPhase`）跨注册中心标准化字段；R 输出列用 `.` 前缀（如 `.trialPhase`）。
- R 进度行协议：`QUERYURL\tname\turl`、`COUNT\tregister\tcount`、`PROGRESS\ti\ttotal\ttid\tstatus\terror`。

## 改动纪律

- 魔法数字（超时/间隔/截断长度等）集中在 `core/constants.py`（`R_TIMEOUT_BUFFER`、`DOC_DOWNLOAD_TIMEOUT_TOTAL`、`RESUME_PATH_SLUG_LENGTH`…），新常量加注释说明依据。
- commit message 用 `<type>(<scope>): <subject>`，关联计划阶段编号（如 `P2-2`）。小步提交，每次 1–3 文件。
- docstring 中文，类型提示 + PEP 8。
- FDA 下载文件名保持英文（doc_type 不映射中文）。
- 删除文件 / 改 `.env` / `git push` / `rebase` / `reset --hard` / 发版前先问 Damon。
