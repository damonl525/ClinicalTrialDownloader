#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Server for Clinical Trial Downloader.

暴露临床试验数据/文档下载的全部功能给 AI agent（ZCode、Claude Desktop、Cursor 等）。
通过 stdio transport 与 MCP 客户端通信。

纯 Python 功能（搜索/下载/提取/文档/FDA 搜索）直接调 service/bridge 层。
Qt 依赖功能（FDA TOC/PDF、CDE 全链路）通过 subprocess 调 qt_helper.py 隔离进程，
规避 MCP asyncio 事件循环与 QApplication 主线程的冲突。

启动：
    python mcp_server.py            # stdio transport（供 MCP 客户端调用）

依赖：pip install mcp>=2.0

设计说明：
- 所有工具为 sync def。MCP SDK v2 自动把 sync 工具丢到 worker 线程执行，
  不会阻塞 asyncio 事件循环。bridge/service 的调用是阻塞的（subprocess + pandas），
  正适合 sync def。
- 不使用 Context 进度报告：2026-07-28 spec 中 ctx.info/log 已废弃，且其方法为 async，
  在 sync 工具里无法直接调用。进度靠返回值（success/failed 计数）传达。
"""

import json
import os
import sys
import subprocess
import logging
from typing import Any

# 初始化 R 环境（复用 main.py 的检测逻辑，GUI 无关）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from main import setup_r_environment
    setup_r_environment()
except Exception as e:
    # R 缺失不阻止 MCP server 启动——部分工具（FDA search）不依赖 R，
    # 用户可能在工具调用时才收到 R 错误提示
    print(f"Warning: R environment setup failed: {e}", file=sys.stderr)

from mcp.server import MCPServer

logger = logging.getLogger(__name__)

# ============================================================
# 全局状态：bridge 单例（首次 connect_db 工具调用时初始化）
# ============================================================

_bridge = None
_db_path = None
_collection = None


def _get_bridge():
    """获取已连接的 bridge 实例，未连接则抛错提示 AI 先调 connect_db。"""
    global _bridge
    if _bridge is None:
        raise RuntimeError(
            "数据库未连接。请先调用 connect_db 工具连接 SQLite 数据库。"
        )
    return _bridge


def _qt_helper(command: str, args: dict) -> dict:
    """通过 subprocess 调 qt_helper.py 跑 Qt 依赖功能（FDA TOC/PDF、CDE）。

    Qt 的 QApplication 必须在主线程跑，而 MCP server 的 asyncio 也在主线程，
    两者冲突。故 Qt 功能放到独立子进程，跑完输出 JSON 退出。

    Args:
        command: qt_helper 子命令（fda_pdf/cde_list/cde_pdf）
        args: 传给 qt_helper 的参数 dict（JSON 序列化后通过 stdin 传入）
    """
    helper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qt_helper.py")
    if not os.path.exists(helper_path):
        return {"ok": False, "error": f"qt_helper.py 不存在: {helper_path}"}

    logger.info("启动 Qt 子进程: %s", command)
    try:
        proc = subprocess.run(
            [sys.executable, helper_path, command],
            input=json.dumps(args, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3600,  # FDA/CDE 操作可能很慢（大结果集 + 限速下载）
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Qt 子进程超时（>1h），可能遭遇限速或网络问题"}
    except Exception as e:
        return {"ok": False, "error": f"Qt 子进程启动失败: {e}"}

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "")[:500]
        return {"ok": False, "error": f"Qt 子进程异常退出 (code={proc.returncode}): {stderr_tail}"}

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        stdout_tail = (proc.stdout or "")[:500]
        return {"ok": False, "error": f"Qt 子进程输出非 JSON: {stdout_tail}"}


# ============================================================
# MCP Server 定义
# ============================================================

mcp = MCPServer(
    name="clinical-trial-downloader",
    title="临床试验数据下载器",
    description=(
        "搜索、下载、提取临床试验数据（CTGOV2/EUCTR/ISRCTN/CTIS）并导出 CSV、"
        "下载文档（protocol/SAP 等）。另含 FDA 审评文档和 CDE 上市药品审评报告下载。"
        "基于 R ctrdata 包 + Python。"
    ),
    instructions=(
        "典型工作流：1) connect_db 连接数据库 → "
        "2) generate_search_urls 生成查询 URL（或 preview_count 预览数量）→ "
        "3) download_to_db 下载数据 → "
        "4) extract_dataframe 提取并导出 CSV → "
        "5) download_documents 下载文档。\n"
        "FDA 审评文档：fda_search 搜索 → fda_download_docs 下载。\n"
        "CDE 上市药品：cde_list_marketed_drugs 列表 → cde_download_docs 下载。\n"
        "注意：大范围下载（>10000 试验）需按年/季分批，否则 CTGOV2 会拒绝。"
    ),
)


# ── 数据库连接 ──

@mcp.tool()
def connect_db(db_path: str, collection: str = "ctrdata") -> dict:
    """连接 SQLite 数据库（不存在则自动创建）。

    所有后续数据操作都基于此连接。一个 MCP 会话只需连接一次。

    Args:
        db_path: SQLite 数据库文件路径（如 "trials.sqlite"）。不存在会自动创建。
        collection: 集合名，默认 "ctrdata"（ctrdata 的命名空间隔离）。

    Returns:
        数据库信息（总记录数、已连接集合等）。
    """
    global _bridge, _db_path, _collection
    from ctrdata.bridge import CtrdataBridge

    _bridge = CtrdataBridge()
    result = _bridge.connect(db_path, collection)
    _db_path = db_path
    _collection = collection
    return {"ok": True, "db_path": db_path, "collection": collection, "info": result}


@mcp.tool()
def get_db_info() -> dict:
    """获取当前数据库的元信息（记录数、集合列表、最后查询时间等）。"""
    bridge = _get_bridge()
    return {"ok": True, "info": bridge.get_db_info()}


@mcp.tool()
def get_query_history() -> dict:
    """获取数据库的查询历史（此前下载过的查询条件、时间、记录数）。"""
    bridge = _get_bridge()
    df = bridge.get_query_history()
    return {"ok": True, "history": df.to_dict(orient="records") if df is not None else []}


# ── 搜索 ──

@mcp.tool()
def generate_search_urls(
    condition: str = "",
    intervention: str = "",
    search_phrase: str = "",
    phase: str = "",
    recruitment: str = "",
    start_after: str = "",
    start_before: str = "",
    completed_after: str = "",
    completed_before: str = "",
    population: str = "",
    countries: str = "",
    only_med_interv_trials: bool = True,
    only_with_results: bool = False,
) -> dict:
    """根据搜索条件生成各注册中心的查询 URL（不下载，仅生成 URL）。

    支持的注册中心：CTGOV2（ClinicalTrials.gov）、EUCTR、ISRCTN、CTIS。
    返回 {register: url} 映射，可用 preview_count 预览数量，或 download_to_db 下载。

    Args:
        condition: 疾病/状况关键词，如 "lung cancer"。
        intervention: 干预措施，如 "aspirin"。
        search_phrase: 精确搜索短语（支持 AND / OR）。
        phase: 试验阶段，须含 "phase" 字样，如 "phase 3"、"phase 2+3"。
        recruitment: 招募状态。
        start_after/start_before: 开始日期范围（YYYY-MM-DD）。EUCTR 为注册日期。
        completed_after/completed_before: 完成日期范围。
        population: 目标人群。
        countries: 国家代码（逗号分隔，如 "US,CN,DE"）。
        only_med_interv_trials: 仅药物/器械干预试验（默认 True）。
        only_with_results: 仅有结果的试验（默认 False）。

    Returns:
        {register_name: query_url} 映射，含所有匹配的注册中心。
    """
    bridge = _get_bridge()
    return {"ok": True, "urls": bridge.generate_queries(
        condition=condition, intervention=intervention, search_phrase=search_phrase,
        phase=phase, recruitment=recruitment,
        start_after=start_after, start_before=start_before,
        completed_after=completed_after, completed_before=completed_before,
        population=population, countries=countries,
        only_med_interv_trials=only_med_interv_trials,
        only_with_results=only_with_results,
    )}


@mcp.tool()
def preview_count(urls: dict) -> dict:
    """预览各注册中心查询 URL 的试验数量（不下载，仅计数）。

    大范围下载前强烈建议先调此工具确认规模。CTGOV2 单次 >10000 会被拒绝，
    数千试验的批次也可能触发 ctrdata 上游 bug，需分小批。

    Args:
        urls: {register: url} 映射（来自 generate_search_urls）。

    Returns:
        {register: count} 映射。
    """
    bridge = _get_bridge()
    counts = bridge.count_trials(urls)
    return {"ok": True, "counts": counts}


# ── 下载 ──

@mcp.tool()
def download_to_db(
    url: str,
    register: str = None,
    euctrresults: bool = False,
    timeout: int = 600,
) -> dict:
    """下载试验数据到数据库（仅数据，不含文档）。

    支持多 URL（换行分隔），每个 URL 对应一个注册中心。
    下载完成后可用 extract_dataframe 提取。

    Args:
        url: 查询 URL（来自 generate_search_urls），多 URL 用换行分隔。
        register: 强制指定注册中心（一般不用，ctrdata 自动识别）。
        euctrresults: EUCTR 是否含结果数据（默认 False）。
        timeout: 单次下载超时秒数（默认 600）。

    Returns:
        {ok, n: 记录数, success: [trial_id...], failed: {...}, warnings: [...]}。
        n==0 时可能是 CTGOV2 >10000 上限 / ctrdata 上游 bug / 无匹配，建议分小批重试。
    """
    bridge = _get_bridge()

    def _on_timeout(elapsed: int, msg: str) -> str:
        return "cancel"  # 超时直接取消，AI 可重试

    result = bridge.load_into_db(
        url, register=register, euctrresults=euctrresults,
        timeout=timeout, on_timeout=_on_timeout,
    )
    n = result.get("n", 0)
    if n == 0:
        result["hint"] = (
            "下载 0 条记录——可能是 CTGOV2 >10000 上限、ctrdata 上游 bug、或无匹配结果。"
            "建议分小批（季度/年度）重试。"
        )
    return result


@mcp.tool()
def download_by_trial_id(trial_id: str, euctrresults: bool = False) -> dict:
    """通过试验 ID 直接下载单条数据（绕过批量下载的 ctrdata 上游 bug）。

    适用于：① 只需少数特定试验 ② 批量下载因 ctrdata bug 失败后的逐条补救。
    注意：大批量逐条下载很慢（每试验一个 R 子进程，~万条约 10 小时）。

    Args:
        trial_id: 试验 ID（如 NCT00001471、EUCTR2020-000123-22、ISRCTN12345678）。
        euctrresults: EUCTR 是否含结果数据。
    """
    bridge = _get_bridge()
    return bridge.load_by_trial_id(trial_id, euctrresults=euctrresults)


@mcp.tool()
def incremental_update(query_index: int = None, force_update: bool = False) -> dict:
    """增量更新：重新执行此前某次查询，仅下载新增或有变更的试验。

    Args:
        query_index: 查询历史索引（从 get_query_history 获取）。None=最后一条。
        force_update: 强制重新下载所有（默认 False，仅新增/变更）。
    """
    bridge = _get_bridge()
    return bridge.update_last_query(query_index=query_index, force_update=force_update)


# ── 提取与导出 ──

@mcp.tool()
def extract_dataframe(
    fields: list = None,
    calculate: list = None,
    deduplicate: bool = True,
    filter_phase: str = "",
    filter_status: str = "",
    filter_date_start: str = "",
    filter_date_end: str = "",
    strict_date: bool = False,
    filter_condition: str = "",
    filter_intervention: str = "",
    output_csv: str = None,
) -> dict:
    """从数据库提取字段到 DataFrame，可选过滤后导出 CSV。

    常用 concept 函数（calculate 参数）：f.trialPhase、f.statusRecruitment、f.startDate、
    f.endDate、f.condition、f.intervention、f.title、f.sponsorSize 等。
    字段名用 R 包名（如 "_id"、"ctrname"），concept 函数输出列用 "." 前缀（如 ".trialPhase"）。

    Args:
        fields: 要提取的原始字段列表（如 ["_id","ctrname","phase"]）。None=自动发现。
        calculate: 要计算的 concept 函数列表（如 ["f.trialPhase","f.startDate"]）。
        deduplicate: 跨注册中心去重（默认 True）。
        filter_phase: 按 phase 过滤，如 "phase 3"。
        filter_status: 按招募状态过滤。
        filter_date_start/filter_date_end: 按开始日期过滤（YYYY-MM-DD）。EUCTR 用注册日期。
        strict_date: 严格日期模式（默认 False，EUCTR/CTIS 日期缺失时用年份近似）。
        filter_condition: 按疾病状况关键词过滤。
        filter_intervention: 按干预措施关键词过滤。
        output_csv: 导出 CSV 路径（如 "output.csv"）。None=不导出，只返回统计。

    Returns:
        {ok, total: 行数, columns: [...], csv_path: ...（若导出）}
    """
    bridge = _get_bridge()
    df = bridge.extract_to_dataframe(
        fields=fields, calculate=calculate, deduplicate=deduplicate,
        filter_phase=filter_phase, filter_status=filter_status,
        filter_date_start=filter_date_start, filter_date_end=filter_date_end,
        strict_date=strict_date,
        filter_condition=filter_condition, filter_intervention=filter_intervention,
    )
    csv_path = None
    if output_csv and df is not None:
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        csv_path = os.path.abspath(output_csv)
    return {
        "ok": True,
        "total": len(df) if df is not None else 0,
        "columns": list(df.columns) if df is not None else [],
        "csv_path": csv_path,
    }


@mcp.tool()
def get_trial_ids() -> dict:
    """获取数据库中所有去重后的试验 ID 列表（用于后续文档下载的 scope）。"""
    bridge = _get_bridge()
    ids = bridge.get_unique_ids()
    return {"ok": True, "count": len(ids), "ids": ids[:200], "total": len(ids)}


# ── 文档下载 ──

@mcp.tool()
def download_documents(
    trial_ids: list,
    documents_path: str,
    documents_regexp: str = None,
    per_trial_timeout: int = 180,
) -> dict:
    """为指定试验 ID 列表下载文档（PDF，如 protocol、SAP、统计报告）。

    按注册中心自动路由：CTGOV2 走批量 R session，ISRCTN 走 HTTP API，
    EUCTR/CTIS 走专用 R 模板。支持断点续传——中断后重调会跳过已完成试验。

    文档类型过滤（documents_regexp）：CTGOV2/ISRCTN/CTIS 支持，EUCTR 不支持（全量下载）。
    常见值："prot"（protocol）、"stat"（统计）、"sap"。

    落盘后自动校验 PDF magic bytes，命中 HTML/SPA 壳（CDN 拦截页）会删除并标记失败。

    Args:
        trial_ids: 试验 ID 列表（来自 get_trial_ids 或 extract 结果）。
        documents_path: 文档保存目录（自动创建）。
        documents_regexp: 文档类型正则过滤（如 "prot|protocol"）。None=全部。
        per_trial_timeout: 单试验超时秒数（默认 180）。

    Returns:
        {ok, success: [...], failed: {tid: err}, skipped: {tid: err}, total: N}
    """
    bridge = _get_bridge()
    os.makedirs(documents_path, exist_ok=True)
    return bridge.download_documents_for_ids(
        trial_ids, documents_path, documents_regexp,
        per_trial_timeout=per_trial_timeout,
    )


# ── FDA 审评文档（独立，无需数据库/R）──

@mcp.tool()
def fda_search(
    drug_name: str = "",
    manufacturer: str = "",
    start_date: str = "",
    end_date: str = "",
    application_type: str = "",
) -> dict:
    """搜索 FDA 审评文档（openFDA drugsfda 端点，无需数据库/R）。

    返回申请记录列表，每条含可下载的文档信息。用 fda_download_docs 下载 PDF。

    注意：宽查询（无日期/药品名）可能返回数千上万条，强烈建议加 drug_name 或日期范围。

    Args:
        drug_name: 药品名（通用名或商品名）。
        manufacturer: 生产企业名。
        start_date/end_date: 申请日期范围（YYYY-MM-DD）。
        application_type: 申请类型（NDA/ANDA/BLA 等）。

    Returns:
        {ok, total, applications: [...]}
    """
    from service.fda_service import FdaSearchService

    svc = FdaSearchService()
    params = {"drug_name": drug_name} if drug_name else {}
    if manufacturer:
        params["manufacturer"] = manufacturer
    if application_type:
        params["application_type"] = application_type
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    return svc.search_all(params)


@mcp.tool()
def fda_download_docs(applications: list, save_dir: str) -> dict:
    """下载 FDA 审评文档 PDF（通过 Qt 子进程，绕过 Akamai CDN 反爬）。

    需要 QWebEngine（PySide6），由 qt_helper.py 在独立进程跑。
    限速下载（随机 8-15s 延迟，连续失败 60s 冷却）。

    支持自动展开 TOC 页面：applications 里的 .html/.cfm 记录会先用
    FdaTocParser 解析（提取 pdfFiles 确认哪些 PDF 真实存在），
    再 expand 为直接 PDF URL 下载。也可先用 fda_expand_toc 单独展开查看。

    Args:
        applications: 申请记录列表（来自 fda_search 的 applications 字段，
                      可含直接 PDF URL 和 TOC 页面 URL）。
        save_dir: PDF 保存目录。
    """
    return _qt_helper("fda_pdf", {"applications": applications, "save_dir": save_dir})


@mcp.tool()
def fda_expand_toc(applications: list) -> dict:
    """展开 FDA TOC 页面 URL 为直接 PDF URL 列表（通过 Qt 子进程）。

    fda_search 返回的 applications 含 TOC 页面（.html/.cfm，一个申请包多个 PDF）。
    此工具用 QWebEngine 加载 TOC 页面提取 pdfFiles JS 对象，确认哪些 PDF 真实
    存在，构造直接下载 URL。

    用途：① 下载前预览可下载的 PDF 列表 ② 分步调试 TOC 解析。
    也可跳过此步直接调 fda_download_docs（它内部会自动展开）。

    Args:
        applications: 申请记录列表（来自 fda_search）。

    Returns:
        {ok, total, applications: [展开后的直接 PDF 记录列表]}
    """
    return _qt_helper("fda_toc", {"applications": applications})


# ── CDE 上市药品审评报告（独立，无需数据库/R）──

@mcp.tool()
def cde_list_marketed_drugs(
    drug_name: str = "",
    start_date: str = "",
) -> dict:
    """爬取 CDE（国家药监局药审中心）上市药品审评报告列表（通过 Qt 子进程绕过瑞数 WAF）。

    需要 QWebEngine（PySide6），由 qt_helper.py 在独立进程跑。

    Args:
        drug_name: 药品名（中文，留空=全量爬取，会很慢）。
        start_date: 批准日期起始（YYYY-MM-DD，留空=不限制）。

    Returns:
        {ok, total, drugs: [{name, approval_date, detail_url, ...}]}
    """
    return _qt_helper("cde_list", {"drug_name": drug_name, "start_date": start_date})


@mcp.tool()
def cde_download_docs(drugs: list, save_dir: str) -> dict:
    """下载 CDE 审评报告/说明书 PDF（通过 Qt 子进程）。

    Args:
        drugs: 药品列表（来自 cde_list_marketed_drugs 的 drugs 字段，含 detail_url）。
        save_dir: PDF 保存目录。
    """
    return _qt_helper("cde_pdf", {"drugs": drugs, "save_dir": save_dir})


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    mcp.run(transport="stdio")
