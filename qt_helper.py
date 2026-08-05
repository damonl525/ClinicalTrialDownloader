#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qt helper for headless MCP tools.

在独立进程里跑 Qt 依赖功能（FDA PDF 下载、CDE 列表爬取、CDE PDF 下载），
规避 MCP server 的 asyncio 事件循环与 QApplication 主线程的冲突。

调用方式（由 mcp_server._qt_helper 调用）：
    python qt_helper.py <command>   # 参数 JSON 从 stdin 读入

支持的 command：
    fda_toc    解析 FDA TOC 页面，展开为直接 PDF URL 列表（FdaTocParser）
    fda_pdf    下载 FDA 审评 PDF（含 TOC 自动展开 → FdaPdfDownloader）
    cde_list   爬取 CDE 上市药品列表（CdeListScraper）
    cde_pdf    下载 CDE 审评 PDF（drugs 列表 → CdePdfDownloader）

输出：成功时 stdout 输出一行 JSON 结果，退出码 0；
      失败时 stdout 输出 {"ok": false, "error": "..."}，退出码 1。

headless：全部用隐藏 QWebEnginePage（_SilentPage），不创建/显示任何 QWidget。
Windows 直接跑；Linux 无头服务器需 QT_QPA_PLATFORM=offscreen。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _emit(result: dict, exit_code: int = 0) -> None:
    """输出 JSON 到 stdout 并退出。"""
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(exit_code)


def _run_qt_app(app_factory) -> dict:
    """创建 QApplication 并跑一个工厂函数（返回要等结果的 QObject 操作）。

    app_factory 接收 QEventLoop，在其中实例化 service、连信号、触发操作。
    返回操作完成后的结果 dict。
    """
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEventLoop, QTimer

    app = QApplication.instance() or QApplication(sys.argv)
    loop = QEventLoop()

    state = {"result": None}

    def _run():
        try:
            app_factory(loop, state)
        except Exception as e:
            state["result"] = {"ok": False, "error": f"Qt 操作启动失败: {e}"}
            loop.quit()

    # 用 QTimer.singleShot(0, ...) 确保 service 实例化发生在事件循环启动后
    QTimer.singleShot(0, _run)
    loop.exec()

    # 退出前释放 QWebEngine 默认 profile（Chromium 子进程）
    try:
        from PySide6.QtWebEngineCore import QWebEngineProfile
        profile = QWebEngineProfile.defaultProfile()
        QTimer.singleShot(0, profile.deleteLater)
    except Exception:
        pass

    return state["result"] or {"ok": False, "error": "Qt 操作未返回结果（可能超时或信号未触发）"}


# ============================================================
# fda_pdf — 下载 FDA 审评 PDF
# ============================================================

def cmd_fda_pdf(args: dict) -> dict:
    """下载 FDA 审评 PDF。

    args:
        applications: 申请记录列表（来自 fda_search 的 rows，含 doc_url 等字段）
        save_dir: PDF 保存目录
    """
    applications = args.get("applications", [])
    save_dir = args.get("save_dir", "")

    if not applications:
        return {"ok": False, "error": "applications 列表为空"}
    if not save_dir:
        return {"ok": False, "error": "save_dir 未指定"}

    os.makedirs(save_dir, exist_ok=True)

    # 分离 TOC 页面 URL（.html/.cfm）与直接 PDF URL
    direct_docs = [r for r in applications if not str(r.get("doc_url", "")).lower().endswith((".html", ".cfm"))]
    toc_rows = [r for r in applications if str(r.get("doc_url", "")).lower().endswith((".html", ".cfm"))]

    def factory(loop, state):
        from service.fda_pdf_downloader import FdaPdfDownloader

        def _do_download(docs_to_download):
            """实际下载阶段。"""
            if not docs_to_download:
                state["result"] = {
                    "ok": True, "success": [], "failed": [], "skipped": [],
                    "total_input": len(applications),
                    "toc_rows": len(toc_rows), "toc_expanded_to": 0,
                    "direct_pdfs": len(direct_docs), "downloaded": 0,
                }
                loop.quit()
                return

            downloader = FdaPdfDownloader()

            def on_complete(result_dict):
                state["result"] = {
                    "ok": True,
                    "success": result_dict.get("success", []),
                    "failed": result_dict.get("failed", []),
                    "skipped": result_dict.get("skipped", []),
                    "total_input": len(applications),
                    "toc_rows": len(toc_rows),
                    "toc_expanded_to": len(docs_to_download) - len(direct_docs),
                    "direct_pdfs": len(direct_docs),
                    "downloaded": len(docs_to_download),
                }
                loop.quit()

            downloader.download_complete.connect(on_complete)
            downloader.download(docs_to_download, save_dir)

        if not toc_rows:
            # 无 TOC，直接下载
            _do_download(direct_docs)
            return

        # 有 TOC：先解析 TOC 页面拿到 pdfFiles，再 expand_from_pdffiles 展开为直接 PDF
        from service.fda_toc_parser import FdaTocParser
        from service.fda_service import FdaSearchService

        toc_urls = [r["doc_url"] for r in toc_rows if r.get("doc_url")]
        parser = FdaTocParser()

        def on_parse_complete(toc_data):
            """TOC 解析完成 → 展开 → 下载。"""
            try:
                svc = FdaSearchService()
                all_rows = direct_docs + toc_rows
                expanded = svc.expand_from_pdffiles(all_rows, toc_data)
                # expand 后全为直接 PDF URL（TOC 已展开或回退构造）
                _do_download(expanded)
            except Exception as e:
                state["result"] = {"ok": False, "error": f"TOC 展开失败: {e}"}
                loop.quit()

        def on_parse_error(msg):
            state["result"] = {"ok": False, "error": f"FdaTocParser 解析失败: {msg}"}
            loop.quit()

        parser.parse_complete.connect(on_parse_complete)
        parser.parse_error.connect(on_parse_error)
        parser.parse(toc_urls)

    return _run_qt_app(factory)


# ============================================================
# fda_toc — 解析 FDA TOC 页面，展开为直接 PDF URL 列表
# ============================================================

def cmd_fda_toc(args: dict) -> dict:
    """解析 FDA TOC 页面（.html/.cfm），返回展开后的直接 PDF URL 列表。

    用于 fda_search → fda_download_docs 之间：fda_search 返回的 applications
    含 TOC 页面 URL（一个申请包多个 PDF），此命令用 QWebEngine 加载 TOC 页面
    提取 pdfFiles JS 对象，确认哪些 PDF 真实存在，构造直接下载 URL。

    args:
        applications: 申请记录列表（来自 fda_search，含 doc_url 等）
    Returns:
        {ok, total, applications: [展开后的直接 PDF 记录列表]}
    """
    applications = args.get("applications", [])
    if not applications:
        return {"ok": False, "error": "applications 列表为空"}

    toc_rows = [r for r in applications if str(r.get("doc_url", "")).lower().endswith((".html", ".cfm"))]
    direct_docs = [r for r in applications if not str(r.get("doc_url", "")).lower().endswith((".html", ".cfm"))]

    if not toc_rows:
        return {"ok": True, "total": len(direct_docs), "applications": direct_docs,
                "note": "无 TOC 页面，原样返回直接 PDF 记录"}

    def factory(loop, state):
        from service.fda_toc_parser import FdaTocParser
        from service.fda_service import FdaSearchService

        parser = FdaTocParser()
        toc_urls = [r["doc_url"] for r in toc_rows if r.get("doc_url")]

        def on_parse_complete(toc_data):
            try:
                svc = FdaSearchService()
                expanded = svc.expand_from_pdffiles(direct_docs + toc_rows, toc_data)
                state["result"] = {
                    "ok": True,
                    "total": len(expanded),
                    "applications": expanded,
                    "toc_parsed": len(toc_urls),
                    "toc_data_keys": [k for k, v in toc_data.items() if v is not None],
                }
            except Exception as e:
                state["result"] = {"ok": False, "error": f"TOC 展开失败: {e}"}
            loop.quit()

        def on_parse_error(msg):
            state["result"] = {"ok": False, "error": f"FdaTocParser 解析失败: {msg}"}
            loop.quit()

        parser.parse_complete.connect(on_parse_complete)
        parser.parse_error.connect(on_parse_error)
        parser.parse(toc_urls)

    return _run_qt_app(factory)


# ============================================================
# cde_list — 爬取 CDE 上市药品列表
# ============================================================

def cmd_cde_list(args: dict) -> dict:
    """爬取 CDE 上市药品审评报告列表。

    args:
        drug_name: 药品名关键词（留空=全量）
        start_date: 批准日期起始 YYYY-MM-DD（留空=不限制）
    """
    drug_name = args.get("drug_name", "")
    start_date = args.get("start_date", "")

    def factory(loop, state):
        from service.cde_scraper import CdeListScraper

        scraper = CdeListScraper()

        def on_complete(rows):
            state["result"] = {
                "ok": True,
                "total": len(rows),
                "drugs": rows,
            }
            loop.quit()

        def on_error(msg):
            state["result"] = {"ok": False, "error": f"CDE 爬取失败: {msg}"}
            loop.quit()

        scraper.scrape_complete.connect(on_complete)
        scraper.scrape_error.connect(on_error)
        scraper.scrape(keyword=drug_name, date_from=start_date)

    return _run_qt_app(factory)


# ============================================================
# cde_pdf — 下载 CDE 审评 PDF
# ============================================================

def cmd_cde_pdf(args: dict) -> dict:
    """下载 CDE 审评报告/说明书 PDF。

    args:
        drugs: 药品列表（来自 cde_list 的 drugs 字段）
              每条需含 detail_url；本命令会先解析详情页提取 PDF 链接，再下载。
        save_dir: PDF 保存目录
    """
    drugs = args.get("drugs", [])
    save_dir = args.get("save_dir", "")

    if not drugs:
        return {"ok": False, "error": "drugs 列表为空"}
    if not save_dir:
        return {"ok": False, "error": "save_dir 未指定"}

    os.makedirs(save_dir, exist_ok=True)

    # 收集 detail_url（过滤空值）
    detail_urls = [d.get("detail_url") for d in drugs if d.get("detail_url")]
    if not detail_urls:
        return {"ok": False, "error": "drugs 列表中无有效 detail_url"}

    # 建立 accept_id / drug_name 查找表（下载文件名需用）
    drug_map = {d.get("detail_url"): d for d in drugs if d.get("detail_url")}

    def factory(loop, state):
        from service.cde_scraper import CdeListScraper
        from service.cde_pdf_downloader import CdePdfDownloader

        scraper = CdeListScraper()

        def on_detail_complete(detail_map):
            """详情页解析完成 → 组装 docs → 下载 PDF。"""
            # 组装下载队列：每个附件补上 drug_name/accept_id/doc_type（中文）
            docs = []
            for detail_url, data in detail_map.items():
                if not data:
                    continue
                drug_info = drug_map.get(detail_url, {})
                drug_name = drug_info.get("drug_name", "unknown")
                accept_id = drug_info.get("accept_id", "")
                for att in data.get("attachments", []):
                    doc_type_cn = {"review_report": "审评报告", "instructions": "说明书"}.get(
                        att.get("doc_type", "other"), att.get("doc_type", "other")
                    )
                    docs.append({
                        "url": att.get("url"),
                        "filename": att.get("filename"),
                        "drug_name": drug_name,
                        "accept_id": accept_id,
                        "doc_type": doc_type_cn,
                    })

            if not docs:
                state["result"] = {"ok": True, "success": [], "failed": [], "skipped": [],
                                   "total_drugs": len(drugs), "detail_parsed": len(detail_map),
                                   "docs_found": 0}
                loop.quit()
                return

            # 切换到 PDF 下载器
            pdf_dl = CdePdfDownloader()

            def on_pdf_complete(result_dict):
                state["result"] = {
                    "ok": True,
                    "success": result_dict.get("success", []),
                    "failed": result_dict.get("failed", []),
                    "skipped": result_dict.get("skipped", []),
                    "total_drugs": len(drugs),
                    "detail_parsed": len(detail_map),
                    "docs_found": len(docs),
                }
                loop.quit()

            pdf_dl.download_complete.connect(on_pdf_complete)
            pdf_dl.download(docs, save_dir)

        def on_detail_error(detail_url, err):
            # 单个详情页失败不致命，等 detail_complete 聚合
            pass

        scraper.detail_complete.connect(on_detail_complete)
        scraper.detail_error.connect(on_detail_error)
        scraper.parse_detail_pages(detail_urls)

    return _run_qt_app(factory)


# ============================================================
# 入口
# ============================================================

COMMANDS = {
    "fda_toc": cmd_fda_toc,
    "fda_pdf": cmd_fda_pdf,
    "cde_list": cmd_cde_list,
    "cde_pdf": cmd_cde_pdf,
}


def main():
    if len(sys.argv) < 2:
        _emit({"ok": False, "error": f"用法: python qt_helper.py <{'|'.join(COMMANDS)}>，参数从 stdin 读 JSON"}, 1)

    command = sys.argv[1]
    if command not in COMMANDS:
        _emit({"ok": False, "error": f"未知命令: {command}，支持: {list(COMMANDS)}"}, 1)

    # 从 stdin 读参数 JSON
    try:
        stdin_text = sys.stdin.read()
        args = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError as e:
        _emit({"ok": False, "error": f"stdin JSON 解析失败: {e}"}, 1)

    try:
        result = COMMANDS[command](args)
    except Exception as e:
        import traceback
        _emit({"ok": False, "error": f"{command} 执行异常: {e}", "traceback": traceback.format_exc()[-500:]}, 1)

    _emit(result, 0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
