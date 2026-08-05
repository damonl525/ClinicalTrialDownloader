# MCP Server — 临床试验数据下载器

本文件说明如何通过 MCP（Model Context Protocol）让 AI agent（ZCode、Claude Desktop、Cursor 等）无 GUI 调用本工具的全部功能。

## 架构

```
AI agent ─stdio─▶ mcp_server.py（主进程，asyncio）
                     │
                     ├─ 纯 Python 工具（直接调 service/bridge）：
                     │    connect_db / generate_search_urls / download_to_db /
                     │    extract_dataframe / download_documents / fda_search ...
                     │
                     └─ Qt 工具（subprocess 调独立进程）：
                          └─ qt_helper.py（QApplication 事件循环）
                               ├─ fda_pdf   → FdaPdfDownloader
                               ├─ cde_list  → CdeListScraper
                               └─ cde_pdf   → CdeListScraper + CdePdfDownloader
```

**为什么 Qt 功能用 subprocess**：MCP server 的 asyncio 事件循环和 Qt 的 `QApplication` 都要求主线程，不能共存。故 Qt 依赖功能（FDA PDF、CDE 全链路）放到独立进程，跑完输出 JSON 退出。

## 配置

### ZCode / Claude Desktop / Cursor

工作区已有 `.mcp.json`（MCP 客户端自动发现）。若用其他客户端，手动配置：

```json
{
  "mcpServers": {
    "clinical-trial-downloader": {
      "command": "/path/to/.venv/Scripts/python.exe",
      "args": ["/path/to/mcp_server.py"],
      "env": { "QT_QPA_PLATFORM": "offscreen" }
    }
  }
}
```

**关键**：`command` 必须指向装了 PySide6 的 Python 解释器（项目 venv），因为 `qt_helper.py` 需要 QWebEngine。

### 依赖

```bash
pip install mcp>=2.0     # MCP SDK（仅 MCP server 用，GUI 不依赖）
# PySide6、pandas、jinja2、requests 等见 requirements.txt（GUI 共用）
```

R 环境：MCP server 启动时会自动检测 R_HOME（复用 main.setup_r_environment）。数据/文档下载工具需 R + ctrdata 包；FDA 搜索/CDE 不需要 R。

## 工具清单（17 个）

### 数据库（3）

| 工具 | 说明 | 关键参数 |
|------|------|---------|
| `connect_db` | 连接 SQLite（首次必调） | `db_path`（如 "trials.sqlite"），`collection`（默认 "ctrdata"） |
| `get_db_info` | 数据库元信息 | — |
| `get_query_history` | 查询历史 | — |

### 搜索（2）

| 工具 | 说明 | 关键参数 |
|------|------|---------|
| `generate_search_urls` | 生成各注册中心查询 URL | `condition`、`intervention`、`phase`（如 "phase 3"）、`start_after/before`（YYYY-MM-DD）、`countries` |
| `preview_count` | 预览试验数量（不下，仅计数） | `urls`（来自 generate_search_urls） |

### 下载（4）

| 工具 | 说明 | 关键参数 |
|------|------|---------|
| `download_to_db` | 下载数据到库（不含文档） | `url`（可多行）、`timeout`（默认 600） |
| `download_to_db_split` | 自动分批下载 CTGOV2（绕过 >10000 上限） | 查询条件 + `start_after/before` 日期范围 + `max_per_batch`（默认 9000） |
| `download_by_trial_id` | 按试验 ID 下载单条（绕过上游 bug） | `trial_id`（如 NCT00001471） |
| `incremental_update` | 增量更新 | `query_index`、`force_update` |

### 提取（2）

| 工具 | 说明 | 关键参数 |
|------|------|---------|
| `extract_dataframe` | 提取字段 → 可选过滤 → 导出 CSV | `calculate`（concept 函数如 ["f.trialPhase","f.startDate"]）、`filter_phase`、`output_csv` |
| `get_trial_ids` | 获取去重试验 ID（文档下载 scope） | — |

### 文档下载（1）

| 工具 | 说明 | 关键参数 |
|------|------|---------|
| `download_documents` | 按试验 ID 下载 PDF（protocol/SAP 等） | `trial_ids`、`documents_path`、`documents_regexp`（如 "prot"） |

按注册中心自动路由，支持断点续传，落盘后自动校验 PDF（删 HTML/SPA 壳）。

### FDA 审评文档（3，无需数据库/R）

| 工具 | 说明 | 关键参数 |
|------|------|---------|
| `fda_search` | 搜索 openFDA | `drug_name`、`manufacturer`、`start_date/end_date` |
| `fda_expand_toc` | 展开 TOC 页面为直接 PDF URL 列表（走 qt_helper） | `applications`（来自 fda_search） |
| `fda_download_docs` | 下载审评 PDF（自动展开 TOC，走 qt_helper） | `applications`、`save_dir` |

### CDE 上市药品（2，无需数据库/R）

| 工具 | 说明 | 关键参数 |
|------|------|---------|
| `cde_list_marketed_drugs` | 爬取 CDE 列表（绕瑞数 WAF） | `drug_name`、`start_date` |
| `cde_download_docs` | 下载审评/说明书 PDF | `drugs`（来自 cde_list）、`save_dir` |

## 典型工作流

### 临床试验数据 + 文档

```
1. connect_db(db_path="trials.sqlite")
2. generate_search_urls(condition="lung cancer", phase="phase 3")  → urls
3. preview_count(urls=urls)                                        → 确认规模
4. download_to_db(url=urls["CTGOV2"])                              → 入库
5. extract_dataframe(calculate=["f.trialPhase","f.startDate"],
                     output_csv="output.csv")                       → 导出
6. get_trial_ids()                                                 → ids
7. download_documents(trial_ids=ids, documents_path="docs/",
                      documents_regexp="prot")                     → PDF
```

### FDA 审评文档

```
1. fda_search(drug_name="pembrolizumab")                           → applications
2. fda_download_docs(applications=applications, save_dir="fda/")   → PDF
   （fda_download_docs 内部自动展开 .html/.cfm 的 TOC 页面为直接 PDF URL；
    如需先预览展开结果，可调 fda_expand_toc）
```

### CDE 上市药品

```
1. cde_list_marketed_drugs(drug_name="阿司匹林")                    → drugs
2. cde_download_docs(drugs=drugs, save_dir="cde/")                 → PDF
```

## 已知限制

- **CTGOV2 >10000 上限**：单次查询超 1 万试验返回 n:0 假成功。用 `download_to_db_split` 自动按年分批（需提供 start_after/start_before 日期范围）。
- **ctrdata rows_update 上游 bug**：某些批次整批失败。用 `download_by_trial_id` 逐条补救，或分小批重试。
- **CDN/SNI 封锁**：clinicaltrials.gov 域名可能被 SNI 层封锁。在 GUI Settings 配代理端口，或终端 `set HTTPS_PROXY` 后启动。
- **FDA TOC 页面**：`fda_download_docs` 当前不展开 .html/.cfm 的 TOC URL（需 FdaTocParser，暂不支持），会直接报错提示。直接 PDF URL 可正常下载。
- **CDE 爬取慢**：全量爬取（无 drug_name）需过瑞数 WAF，耗时长。

## 调试

```bash
# 用 MCP inspector 交互测试（需装 mcp[cli]）
mcp dev mcp_server.py

# 单独测 qt_helper 命令（直接看 JSON 输出）
echo '{"drug_name":"","start_date":""}' | python qt_helper.py cde_list

# 手动发 MCP 请求测 server
python mcp_server.py  # 等 stdin 的 JSON-RPC
```
