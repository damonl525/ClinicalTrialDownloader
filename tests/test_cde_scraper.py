#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CdeListScraper — list page scraping and detail page parsing."""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

# Ensure a QApplication exists for QObject-based tests
app = QApplication.instance() or QApplication(sys.argv)

from service.cde_scraper import CdeListScraper


class TestExtractTableRows(unittest.TestCase):
    """Test _extract_table_rows() — JS result dict → row dicts."""

    def test_extract_row_count(self):
        """Mock JS result produces correct number of rows."""
        scraper = CdeListScraper()
        mock_js_result = {
            "rows": [
                {
                    "accept_id": "JXHS2500034",
                    "drug_name": "瑞米布替尼片",
                    "drug_type": "化学药品",
                    "apply_type": "进口药",
                    "reg_class": "1类",
                    "company": "Novartis",
                    "date": "2025-03-15",
                    "detail_url": "/main/xxgk/postmarket/drugDetail?acceptId=JXHS2500034",
                },
                {
                    "accept_id": "JXHS2500035",
                    "drug_name": "另一药品",
                    "drug_type": "中药",
                    "apply_type": "新药",
                    "reg_class": "2类",
                    "company": "某公司",
                    "date": "2025-03-16",
                    "detail_url": "/main/xxgk/postmarket/drugDetail?acceptId=JXHS2500035",
                },
            ],
            "total_pages": 183,
            "current_page": 1,
        }
        rows = scraper._extract_table_rows(mock_js_result)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["accept_id"], "JXHS2500034")
        self.assertEqual(rows[1]["accept_id"], "JXHS2500035")

    def test_extract_required_fields(self):
        scraper = CdeListScraper()
        mock_js_result = {
            "rows": [{
                "accept_id": "JXHS2500034",
                "drug_name": "测试药品",
                "drug_type": "化学药品",
                "apply_type": "新药",
                "reg_class": "1类",
                "company": "某公司",
                "date": "2025-03-15",
                "detail_url": "/main/xxgk/postmarket/drugDetail?acceptId=JXHS2500034",
            }],
            "total_pages": 1,
            "current_page": 1,
        }
        rows = scraper._extract_table_rows(mock_js_result)
        row = rows[0]
        for field in ["accept_id", "drug_name", "drug_type", "apply_type",
                      "reg_class", "company", "date", "detail_url"]:
            self.assertIn(field, row, f"Missing field: {field}")

    def test_extract_handles_missing_detail_url(self):
        scraper = CdeListScraper()
        mock_js_result = {
            "rows": [{
                "accept_id": "JXHS2500034",
                "drug_name": "测试药品",
                "drug_type": "化学药品",
                "apply_type": "新药",
                "reg_class": "1类",
                "company": "某公司",
                "date": "2025-03-15",
                "detail_url": "",
            }],
            "total_pages": 1,
            "current_page": 1,
        }
        rows = scraper._extract_table_rows(mock_js_result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detail_url"], "")


class TestRowMatchesFilters(unittest.TestCase):
    """Test _row_matches_filters() — client-side date/type filtering."""

    def _make_row(self, date="2025-02-27", drug_type="化学药品",
                  apply_type="进口药", reg_class="1类"):
        return {
            "accept_id": "JXHS2500034",
            "drug_name": "测试药品",
            "drug_type": drug_type,
            "apply_type": apply_type,
            "reg_class": reg_class,
            "company": "某公司",
            "date": date,
            "detail_url": "https://example.com",
        }

    def test_no_filters_passes(self):
        scraper = CdeListScraper()
        self.assertTrue(scraper._row_matches_filters(self._make_row()))

    def test_date_from_filters_earlier(self):
        scraper = CdeListScraper()
        scraper._date_from = "2025-03-01"
        self.assertFalse(scraper._row_matches_filters(self._make_row(date="2025-02-27")))

    def test_date_from_passes_equal(self):
        scraper = CdeListScraper()
        scraper._date_from = "2025-02-27"
        self.assertTrue(scraper._row_matches_filters(self._make_row(date="2025-02-27")))

    def test_date_from_passes_later(self):
        scraper = CdeListScraper()
        scraper._date_from = "2025-02-01"
        self.assertTrue(scraper._row_matches_filters(self._make_row(date="2025-02-27")))

    def test_date_to_filters_later(self):
        scraper = CdeListScraper()
        scraper._date_to = "2025-02-01"
        self.assertFalse(scraper._row_matches_filters(self._make_row(date="2025-02-27")))

    def test_date_range_both_bounds(self):
        scraper = CdeListScraper()
        scraper._date_from = "2025-02-01"
        scraper._date_to = "2025-03-01"
        self.assertTrue(scraper._row_matches_filters(self._make_row(date="2025-02-27")))
        self.assertFalse(scraper._row_matches_filters(self._make_row(date="2025-01-15")))
        self.assertFalse(scraper._row_matches_filters(self._make_row(date="2025-03-15")))

    def test_drug_type_filter(self):
        scraper = CdeListScraper()
        scraper._drug_type = "化学药品"
        self.assertTrue(scraper._row_matches_filters(self._make_row(drug_type="化学药品")))
        self.assertFalse(scraper._row_matches_filters(self._make_row(drug_type="中药")))

    def test_apply_type_filter(self):
        scraper = CdeListScraper()
        scraper._apply_type = "进口药"
        self.assertTrue(scraper._row_matches_filters(self._make_row(apply_type="进口药")))
        self.assertFalse(scraper._row_matches_filters(self._make_row(apply_type="新药")))

    def test_reg_class_filter(self):
        scraper = CdeListScraper()
        scraper._reg_class = "1类"
        self.assertTrue(scraper._row_matches_filters(self._make_row(reg_class="1类")))
        self.assertFalse(scraper._row_matches_filters(self._make_row(reg_class="2类")))

    def test_empty_date_row_filtered_by_date_from(self):
        scraper = CdeListScraper()
        scraper._date_from = "2025-01-01"
        row = self._make_row(date="")
        # Empty string < "2025-01-01" → filtered out
        self.assertFalse(scraper._row_matches_filters(row))


class TestNormalizeDate(unittest.TestCase):
    """Test _normalize_date() — handles various date formats from API."""

    def test_standard_date(self):
        self.assertEqual(CdeListScraper._normalize_date("2025-02-27"), "2025-02-27")

    def test_date_with_time(self):
        self.assertEqual(CdeListScraper._normalize_date("2025-02-27 10:30:00"), "2025-02-27")

    def test_empty_string(self):
        self.assertEqual(CdeListScraper._normalize_date(""), "")

    def test_none_value(self):
        self.assertEqual(CdeListScraper._normalize_date(None), "")

    def test_numeric_timestamp_seconds(self):
        # 2025-02-27 00:00:00 UTC ≈ 1740614400
        result = CdeListScraper._normalize_date(1740614400)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.startswith("2025-"))

    def test_numeric_string_timestamp(self):
        result = CdeListScraper._normalize_date("1740614400")
        self.assertEqual(len(result), 10)

    def test_already_normal(self):
        self.assertEqual(CdeListScraper._normalize_date("2025-03-08"), "2025-03-08")


if __name__ == "__main__":
    unittest.main()