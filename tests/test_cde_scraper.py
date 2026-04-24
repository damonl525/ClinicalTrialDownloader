#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CdeListScraper — list page scraping and detail page parsing."""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


if __name__ == "__main__":
    unittest.main()