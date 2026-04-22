#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
常量定义 — 基于 ctrdata R 包 1.26.0
"""

import os

# ================================================================
# Application identity
# ================================================================
APP_NAME = "临床试验数据下载器"
APP_NAME_EN = "Clinical Trial Data Downloader"
APP_VERSION = "1.2.0"

# ================================================================
# 数据库
# ================================================================
DEFAULT_DB_NAME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trials.sqlite")
DEFAULT_COLLECTION = "ctrdata"

# ================================================================
# 注册中心
# ================================================================
SUPPORTED_REGISTERS = {
    "CTGOV2": "ClinicalTrials.gov (v2 API)",
    "EUCTR": "EU 临床试验注册中心",
    "ISRCTN": "ISRCTN 注册中心",
    "CTIS": "EU CTIS",
}

# ================================================================
# 下载后过滤选项 — 映射到 ctrdata 概念函数实际输出值
# ================================================================
FILTER_PHASES = {
    "全部": "",
    "1期": "phase 1",
    "1/2期": "phase 1+2",
    "2期": "phase 2",
    "2/3期": "phase 2+3",
    "2/4期": "phase 2+4",
    "3期": "phase 3",
    "3/4期": "phase 3+4",
    "1/2/3期": "phase 1+2+3",
    "4期": "phase 4",
    "1/2/3/4期": "phase 1+2+3+4",
}

FILTER_STATUSES = {
    "全部": "",
    "进行中": "ongoing",
    "已完成": "completed",
    "提前终止": "ended early",
    "其他": "other",
}

# ================================================================
# 文档下载 — 与 ctrdata 的 documents.regexp 参数对应
# ================================================================
# ctrdata 默认文档过滤正则 (来自 ctrdata 1.26.0 源码)
DOC_PATTERN_CTRDATA_DEFAULT = (
    "prot|sample|statist|sap_|p1ar|p2ars|icf|ctalett|lay|^[0-9]+ "
)

# 预定义文档类型选项
DOC_TYPE_OPTIONS = {
    "全部文档": DOC_PATTERN_CTRDATA_DEFAULT,
    "Protocol + SAP": "prot|sap_|statist",
    "仅 Protocol": "prot",
    "仅 SAP": "sap_|statist",
    "仅知情同意书": "icf",
}

# ================================================================
# 试验概念函数 (f.*) — ctrdata 1.21.0+ 提供的跨注册中心标准化函数
# ================================================================
CONCEPT_FUNCTIONS = {
    "f.statusRecruitment": ("招募状态", True),
    "f.trialPhase": ("试验阶段", True),
    "f.trialTitle": ("试验标题", True),
    "f.startDate": ("开始日期", True),
    "f.sampleSize": ("样本量", False),
    "f.sponsorType": ("资助方类型", False),
    "f.numSites": ("中心数量", False),
    "f.hasResults": ("是否有结果", False),
    "f.isUniqueTrial": ("是否唯一试验", False),
    "f.controlType": ("对照组类型", False),
    "f.assignmentType": ("分配类型", False),
    "f.primaryEndpointDescription": ("主要终点", False),
    "f.trialObjectives": ("试验目标", False),
    "f.trialPopulation": ("目标人群", False),
}

# ctrdata 概念函数实际输出值（用于下载后过滤匹配）
CONCEPT_VALUES = {
    "trialPhase": [
        "phase 1", "phase 1+2", "phase 2", "phase 2+3",
        "phase 2+4", "phase 3", "phase 3+4", "phase 1+2+3",
        "phase 4", "phase 1+2+3+4",
    ],
    "statusRecruitment": [
        "ongoing", "completed", "ended early", "other",
    ],
}

# ================================================================
# 搜索参数 — ctrGenerateQueries() 参数选项
# ================================================================
SEARCH_PHASES = {
    "全部": "",
    "1期": "phase 1",
    "1/2期": "phase 1+2",
    "2期": "phase 2",
    "2/3期": "phase 2+3",
    "3期": "phase 3",
    "4期": "phase 4",
}

SEARCH_RECRUITMENT = {
    "全部": "",
    "进行中": "ongoing",
    "已完成": "completed",
    "其他": "other",
}

SEARCH_POPULATIONS = {
    "全部": "",
    "成人 (A)": "A",
    "儿童 (P)": "P",
    "老人 (E)": "E",
    "成人+儿童 (P+A)": "P+A",
    "全年龄段 (P+A+E)": "P+A+E",
}

# 适应症/干预措施搜索用的 CTGOV2 原始字段名
CONDITION_FIELDS = [
    "protocolSection.conditionsModule.conditions",
]

INTERVENTION_FIELDS = [
    "protocolSection.armsInterventionsModule.interventions",
]

# 概念函数 R 列名前缀（ctrdata 输出列名为 .xxx 而非 f.xxx）
CONCEPT_COL_PREFIX = "."

# ================================================================
# GUI
# ================================================================
GUI_TITLE = f"{APP_NAME} v{APP_VERSION}"
GUI_DEFAULT_SIZE = (950, 720)
GUI_MIN_SIZE = (800, 600)
LOG_MAX_LINES = 2000
TREEVIEW_DISPLAY_LIMIT = 50

# ================================================================
# 默认选中的概念函数
# ================================================================
DEFAULT_CONCEPTS = [
    "f.statusRecruitment",
    "f.trialPhase",
    "f.trialTitle",
    "f.startDate",
]

# ================================================================
# R 错误中文翻译
# ================================================================
# ================================================================
# FDA openFDA API — 审评资料匹配
# ================================================================
FDA_API_BASE = "https://api.fda.gov/drug/drugsfda.json"
FDA_API_RATE_LIMIT = 1.5  # seconds between calls (no API key, ~40/min)

FDA_REVIEW_DOC_TYPES = {
    "Medical Review(s)": "医学审评",
    "Statistical Review(s)": "统计审评",
    "Chemistry Review(s)": "化学审评",
    "Clinical Pharmacology and Biopharmaceutics Review(s)": "临床药理审评",
    "Pharmacology Review(s)": "药理毒理审评",
    "Summary Review": "综述报告",
    "Other Review(s)": "其他审评",
}

# ================================================================
# R 错误中文翻译
# ================================================================
R_ERROR_TRANSLATIONS = [
    # (pattern, translated_message)
    (r"V8 engine not found", "V8 引擎未安装。请在 R 中执行: install.packages('V8')"),
    (r"cannot open the connection", "网络连接失败，请检查网络设置"),
    (r"HTTP error 404", "请求的页面不存在，请检查搜索条件"),
    (r"HTTP error 429", "请求过于频繁，请稍后再试"),
    (r"HTTP error 5[0-9]{2}", "服务器错误，请稍后再试"),
    (r"collection.*does not exist", "指定的集合不存在，请先下载数据"),
    (r"no records found", "未找到符合条件的试验记录"),
    (r"there is no package called.*ctrdata", "ctrdata 包未安装。请在 R 中执行: install.packages('ctrdata')"),
    (r"there is no package called.*nodbi", "nodbi 包未安装。请在 R 中执行: install.packages('nodbi')"),
    (r"object.*not found", "R 对象未找到，可能是版本不兼容。请更新 ctrdata 包"),
    (r"could not find function", "R 函数未找到，可能是 ctrdata 版本过低。请更新: install.packages('ctrdata')"),
    (r"timeout", "操作超时，网络响应过慢，请稍后重试"),
    (r"Permission denied", "权限不足，无法写入目标路径"),
]

# ================================================================
# FDA Tab — search parameter dropdown options
# ================================================================
FDA_APPLICATION_TYPES = {
    "全部": "",
    "NDA (新药申请)": "NDA",
    "BLA (生物制品许可)": "BLA",
    "ANDA (简略新药申请)": "ANDA",
}

FDA_SEARCH_ROUTES = {
    "全部": "",
    "口服 (oral)": "oral",
    "注射 (intravenous)": "intravenous",
    "局部 (topical)": "topical",
    "吸入 (inhalation)": "inhalation",
    "皮下 (subcutaneous)": "subcutaneous",
    "肌肉 (intramuscular)": "intramuscular",
}

FDA_REVIEW_PRIORITIES = {
    "全部": "",
    "标准 (Standard)": "Standard",
    "优先 (Priority)": "Priority",
}

FDA_SUBMISSION_CLASSES = {
    "全部": "",
    "原创新药 (N)": "N",
    "补充申请 (S)": "S",
    "有效性补充 (SE)": "SE",
    "制造补充 (SL)": "SL",
}
