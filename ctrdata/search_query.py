#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search URL generation and counting — search_query submodule.

Handles: generate_queries(), count_trials(), parse_query_url().
"""

import logging
from typing import Any, Callable, Dict, List

from core.exceptions import CtrdataError

from core.exceptions import DatabaseError, QueryError
from ctrdata import process as _proc
from ctrdata.template_loader import render as _render

logger = logging.getLogger(__name__)


def generate_queries(
    bridge,
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
) -> Dict[str, str]:
    """
    调用 ctrGenerateQueries() 生成各注册中心的搜索 URL

    Returns:
        {"CTGOV2": "https://...", "EUCTR": "https://...", ...}
    """
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")

    for val, lbl in [
        (condition, "疾病/状况"), (intervention, "干预措施"),
        (search_phrase, "搜索短语"),
    ]:
        if val:
            _proc._validate_r_input(val, lbl)

    params = []
    if condition:
        params.append(f'condition = "{_proc._r_escape(condition)}"')
    if intervention:
        params.append(f'intervention = "{_proc._r_escape(intervention)}"')
    if search_phrase:
        params.append(f'searchPhrase = "{_proc._r_escape(search_phrase)}"')
    if phase:
        params.append(f'phase = "{_proc._r_escape(phase)}"')
    if recruitment:
        params.append(f'recruitment = "{_proc._r_escape(recruitment)}"')
    if start_after:
        params.append(f'startAfter = "{_proc._r_escape(start_after)}"')
    if start_before:
        params.append(f'startBefore = "{_proc._r_escape(start_before)}"')
    if completed_after:
        params.append(f'completedAfter = "{_proc._r_escape(completed_after)}"')
    if completed_before:
        params.append(f'completedBefore = "{_proc._r_escape(completed_before)}"')
    if population:
        params.append(f'population = "{_proc._r_escape(population)}"')
    if countries:
        country_list = [c.strip() for c in countries.split(",") if c.strip()]
        country_r = ", ".join(f'"{_proc._r_escape(c)}"' for c in country_list)
        params.append(f"countries = c({country_r})")
    if only_med_interv_trials:
        params.append("onlyMedIntervTrials = TRUE")
    if only_with_results:
        params.append("onlyWithResults = TRUE")

    if not params:
        # Allow empty search — ctrGenerateQueries() uses defaults
        params.append('condition = ""')

    params_str = ",\n    ".join(params)

    r_code = _render("generate_queries", params=params_str)

    proc = _proc.run_r(bridge, r_code)
    output = proc.stdout.strip()

    result = {}
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("QUERYURL\t"):
            parts = line.split("\t", 2)
            if len(parts) == 3:
                result[parts[1]] = parts[2]

    if not result:
        raise QueryError("ctrGenerateQueries() 未返回有效 URL，请检查搜索条件")

    return result


def count_trials(bridge, urls: Dict[str, str], callback: Callable = None) -> Dict[str, int]:
    """调用 ctrLoadQueryIntoDb(only.count=TRUE) 预览各注册中心结果数量"""
    if not bridge.db_path:
        raise DatabaseError("请先连接数据库")

    db = _proc._r_escape(bridge.db_path)
    col = _proc._r_escape(bridge.collection)

    count_lines = []
    for reg, url in urls.items():
        safe_url = _proc._r_escape(url)
        safe_reg = _proc._r_escape(reg)
        count_lines.append(f'''
        {{
            n <- tryCatch({{
                suppressWarnings(suppressMessages({{
                    ctrdata::ctrLoadQueryIntoDb(
                        queryterm = "{safe_url}", con = con,
                        only.count = TRUE, verbose = FALSE
                    )
                }}))
            }}, error = function(e) {{
                cat(sprintf("COUNT\\t{safe_reg}\\t0\\n"))
                list(n = 0L)
            }})
            cat(sprintf("COUNT\\t{safe_reg}\\t%d\\n", n$n))
        }}
        ''')

    r_code = _render("count_trials", db=db, col=col, count_blocks="\n".join(count_lines))

    if callback:
        proc = _proc.run_r_streaming(bridge, r_code, callback=callback, timeout=120)
        output = proc.stdout.strip()
    else:
        proc = _proc.run_r(bridge, r_code, timeout=120)
        output = proc.stdout.strip()

    counts = {}
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("COUNT\t"):
            parts = line.split("\t")
            if len(parts) == 3:
                try:
                    counts[parts[1]] = int(parts[2])
                except ValueError:
                    counts[parts[1]] = 0

    return counts


def parse_query_url(bridge, url: str) -> dict:
    """使用 ctrGetQueryUrl 解析搜索 URL"""
    _proc._validate_r_input(url, "URL")
    safe_url = _proc._r_escape(url)

    r_code = _render("parse_query_url", safe_url=safe_url)

    result = _proc.run_r_json(bridge, r_code)
    if isinstance(result, dict) and result.get("ok") is False:
        raise QueryError(f"查询解析失败: {result.get('error', '')}")

    return result


# ============================================================
# Active substance synonyms
# ============================================================

def find_synonyms(bridge, substance: str) -> list:
    """调用 ctrFindActiveSubstanceSynonyms() 查找活性成分同义词"""
    _proc._validate_r_input(substance, "活性成分")
    safe_sub = _proc._r_escape(substance)

    r_code = _render("find_synonyms", safe_sub=safe_sub)

    try:
        result = _proc.run_r_json(bridge, r_code, timeout=30)
        if isinstance(result, list):
            return result
        return []
    except Exception as e:
        logger.warning(f"同义词查找失败: {e}")
        return []


# ============================================================
# Open in browser
# ============================================================

def open_in_browser(bridge, url: str = "", registers: List[str] = None) -> None:
    """调用 ctrOpenSearchPagesInBrowser() 在浏览器中打开搜索结果"""
    if url:
        safe_url = _proc._r_escape(url)
        url_or_register = f'url = "{safe_url}"'
    elif registers:
        reg_list = ", ".join(f'"{_proc._r_escape(r)}"' for r in registers)
        url_or_register = f'register = c({reg_list})'
    else:
        raise CtrdataError("请提供 url 或 registers 参数")
    r_code = _render("open_browser", url_or_register=url_or_register)

    _proc.run_r(bridge, r_code, timeout=30)
