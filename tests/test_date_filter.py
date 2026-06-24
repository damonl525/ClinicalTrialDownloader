#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-4: _filter_by_date 纯函数测试（宽松近似 vs 严格排除）。

日期过滤是纯 pandas 逻辑（不依赖 R/Qt），可直接单测。
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_df():
    """4 行混合数据：CTGOV2 有日期 / EUCTR 无日期 / EUCTR 有日期 / EUCTR 无日期。"""
    return pd.DataFrame({
        "_id": [
            "NCT04523532",          # CTGOV2，有 startDate
            "2004-000356-17-3RD",   # EUCTR，无 startDate（_id 年份=2004）
            "2015-023156-12-DE",    # EUCTR，有 startDate
            "2021-005148-21-GB",    # EUCTR，无 startDate（_id 年份=2021）
        ],
        ".startDate": ["2020-03-15", "", "2015-06-01", ""],
    })


def test_lenient_mode_uses_id_year_fallback(sample_df):
    """宽松模式（默认）：无 startDate 用 _id 年份中点近似。范围 [2018,2022]。

    - NCT04523532: startDate 2020-03-15，在范围 → 保留
    - 2004-...: NaT → fallback 2004-07-01，不在 [2018,2022] → 排除
    - 2015-...: startDate 2015-06-01，不在范围 → 排除
    - 2021-...: NaT → fallback 2021-07-01，在范围 → 保留
    期望保留 2 行。
    """
    from ctrdata.extract import _filter_by_date

    result = _filter_by_date(sample_df, "2018-01-01", "2022-12-31", strict_date=False)
    assert len(result) == 2
    assert set(result["_id"]) == {"NCT04523532", "2021-005148-21-GB"}


def test_strict_mode_excludes_missing_startdate(sample_df):
    """严格模式：无 startDate 的行被排除。范围 [2018,2022]。

    - NCT04523532: 2020-03-15，在范围 → 保留
    - 2004-...: NaT → 排除
    - 2015-...: 2015-06-01，不在范围 → 排除
    - 2021-...: NaT → 排除
    期望保留 1 行。
    """
    from ctrdata.extract import _filter_by_date

    result = _filter_by_date(sample_df, "2018-01-01", "2022-12-31", strict_date=True)
    assert len(result) == 1
    assert set(result["_id"]) == {"NCT04523532"}


def test_strict_vs_lenient_differs_only_on_missing_dates(sample_df):
    """严格比宽松少保留的，正是无 startDate 的行（2004-、2021-）。

    宽松保留 {NCT04523532, 2021-...}；严格保留 {NCT04523532}。
    差集 = {2021-005148-21-GB}，即严格额外排除的那行本有 _id 年份回退。
    """
    from ctrdata.extract import _filter_by_date

    lenient = _filter_by_date(sample_df, "2018-01-01", "2022-12-31", strict_date=False)
    strict = _filter_by_date(sample_df, "2018-01-01", "2022-12-31", strict_date=True)
    dropped = set(lenient["_id"]) - set(strict["_id"])
    assert dropped == {"2021-005148-21-GB"}


def test_no_date_range_returns_unchanged(sample_df):
    """未设日期范围 → 原样返回（不触发过滤）。"""
    from ctrdata.extract import _filter_by_date

    assert len(_filter_by_date(sample_df, "", "")) == 4
    assert len(_filter_by_date(sample_df, "", "", strict_date=True)) == 4


def test_no_startdate_column_returns_unchanged():
    """无 .startDate 列 → 原样返回。"""
    from ctrdata.extract import _filter_by_date

    df = pd.DataFrame({"_id": ["NCT04523532"], ".trialPhase": ["3"]})
    result = _filter_by_date(df, "2020-01-01", "2022-12-31")
    assert len(result) == 1
    assert ".startDate" not in result.columns


def test_only_start_boundary():
    """只设下界：startDate >= 2018-01-01。"""
    from ctrdata.extract import _filter_by_date

    df = pd.DataFrame({
        "_id": ["NCT04523532", "2004-000356-17-3RD", "2021-005148-21-GB"],
        ".startDate": ["2020-03-15", "", ""],
    })
    # 宽松：NCT(2020) + 2021(fallback) 在下界上；2004(fallback) 不在
    result = _filter_by_date(df, "2018-01-01", "", strict_date=False)
    assert set(result["_id"]) == {"NCT04523532", "2021-005148-21-GB"}
