#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CdePdfDownloader."""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service.cde_pdf_downloader import _make_download_filename


class TestMakeFilename(unittest.TestCase):
    def test_standard_naming(self):
        name = _make_download_filename("瑞米布替尼片", "JXHS2500034", "审评报告")
        self.assertEqual(name, "瑞米布替尼片_JXHS2500034_审评报告.pdf")

    def test_empty_drug_name(self):
        name = _make_download_filename("", "JXHS2500034", "说明书")
        self.assertEqual(name, "说明书_JXHS2500034_说明书.pdf")

    def test_sanitization(self):
        name = _make_download_filename("测试/药品", "J1", "审评报告")
        self.assertNotIn('/', name)
        self.assertNotIn('\\', name)


if __name__ == "__main__":
    unittest.main()