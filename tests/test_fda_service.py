#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for FdaSearchService — openFDA direct search and download."""

import unittest
import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service.fda_service import FdaSearchService


# Sample openFDA API response (2 results, each with submissions containing docs)
SAMPLE_API_RESPONSE = {
    "meta": {"results": {"total": 2}},
    "results": [
        {
            "application_number": "NDA 215985",
            "sponsor_name": "Merck Sharp & Dohme",
            "openfda": {
                "brand_name": ["Keytruda"],
                "generic_name": ["pembrolizumab"],
                "manufacturer_name": ["Merck Sharp & Dohme Corp"],
                "application_number": ["NDA215985"],
            },
            "submissions": [
                {
                    "submission_type": "ORIG-1",
                    "submission_status": "AP",
                    "submission_status_date": "20200615",
                    "submission_class_code": "N",
                    "review_priority": "Priority",
                    "application_docs": [
                        {
                            "type": "Medical Review(s)",
                            "url": "https://example.com/medical_review.pdf",
                        },
                        {
                            "type": "Statistical Review(s)",
                            "url": "https://example.com/stats_review.pdf",
                        },
                        {
                            "type": "Label",
                            "url": "https://example.com/label.pdf",
                        },
                    ],
                }
            ],
        },
        {
            "application_number": "NDA 761052",
            "sponsor_name": "Merck Sharp & Dohme",
            "openfda": {
                "brand_name": ["Keytruda"],
                "generic_name": ["pembrolizumab"],
                "manufacturer_name": ["Merck Sharp & Dohme Corp"],
                "application_number": ["NDA761052"],
            },
            "submissions": [
                {
                    "submission_type": "SUPPL-1",
                    "submission_status": "AP",
                    "submission_status_date": "20210322",
                    "submission_class_code": "S",
                    "review_priority": "Standard",
                    "application_docs": [
                        {
                            "type": "Summary Review",
                            "url": "https://example.com/summary.pdf",
                        },
                    ],
                }
            ],
        },
    ],
}


class TestFlattenResults(unittest.TestCase):
    """Test _flatten_results() — API response → flat row list."""

    def test_flatten_produces_one_row_per_review_doc(self):
        """Only review-type docs become rows; 'Label' is excluded."""
        svc = FdaSearchService()
        rows = svc._flatten_results(SAMPLE_API_RESPONSE["results"])
        # Medical Review, Statistical Review, Summary Review = 3 rows
        self.assertEqual(len(rows), 3)

    def test_flatten_row_has_required_fields(self):
        svc = FdaSearchService()
        rows = svc._flatten_results(SAMPLE_API_RESPONSE["results"])
        row = rows[0]
        self.assertIn("brand_name", row)
        self.assertIn("generic_name", row)
        self.assertIn("application_number", row)
        self.assertIn("manufacturer_name", row)
        self.assertIn("submission_type", row)
        self.assertIn("submission_status_date", row)
        self.assertIn("doc_type", row)
        self.assertIn("doc_url", row)

    def test_flatten_row_values(self):
        svc = FdaSearchService()
        rows = svc._flatten_results(SAMPLE_API_RESPONSE["results"])
        first = rows[0]
        self.assertEqual(first["brand_name"], "Keytruda")
        self.assertEqual(first["generic_name"], "pembrolizumab")
        self.assertEqual(first["application_number"], "NDA 215985")
        self.assertEqual(first["submission_type"], "ORIG-1")
        self.assertEqual(first["submission_status_date"], "20200615")
        self.assertEqual(first["doc_type"], "Medical Review(s)")

    def test_flatten_skips_non_review_docs(self):
        """Label and Letter docs should not appear in results."""
        svc = FdaSearchService()
        rows = svc._flatten_results(SAMPLE_API_RESPONSE["results"])
        doc_types = [r["doc_type"] for r in rows]
        self.assertNotIn("Label", doc_types)
        self.assertNotIn("Letter", doc_types)


class TestBuildSearchParams(unittest.TestCase):
    """Test _build_search_params() — UI params → openFDA query string."""

    def test_drug_name_only(self):
        svc = FdaSearchService()
        params = svc._build_search_params({"drug_name": "pembrolizumab"})
        self.assertIn("search", params)
        self.assertIn("openfda.generic_name", params["search"])

    def test_drug_name_with_date_range(self):
        svc = FdaSearchService()
        params = svc._build_search_params({
            "drug_name": "pembrolizumab",
            "date_from": "2020-01-01",
            "date_to": "2021-12-31",
        })
        self.assertIn("submissions.submission_status_date", params["search"])
        self.assertIn("[20200101+TO+20211231]", params["search"])

    def test_date_from_only(self):
        svc = FdaSearchService()
        params = svc._build_search_params({
            "drug_name": "pembrolizumab",
            "date_from": "2020-01-01",
        })
        self.assertIn("[20200101+TO+*]", params["search"])

    def test_date_to_only(self):
        svc = FdaSearchService()
        params = svc._build_search_params({
            "drug_name": "pembrolizumab",
            "date_to": "2021-12-31",
        })
        self.assertIn("[*+TO+20211231]", params["search"])

    def test_manufacturer_filter(self):
        svc = FdaSearchService()
        params = svc._build_search_params({
            "drug_name": "pembrolizumab",
            "manufacturer": "Merck",
        })
        self.assertIn("openfda.manufacturer_name", params["search"])


class TestMakeFilename(unittest.TestCase):
    """Test _make_download_filename()."""

    def test_standard_naming(self):
        from service.fda_service import _make_download_filename
        name = _make_download_filename(
            brand_name="Keytruda",
            submission_type="ORIG-1",
            date="20200615",
            doc_type="Medical Review(s)",
        )
        self.assertEqual(name, "Keytruda_ORIG-1_20200615_医学审评.pdf")

    def test_fallback_to_generic_name(self):
        from service.fda_service import _make_download_filename
        name = _make_download_filename(
            brand_name="",
            submission_type="ORIG-1",
            date="20200615",
            doc_type="Statistical Review(s)",
        )
        # When no brand_name, doc_type Chinese name is used as fallback prefix
        self.assertTrue(name.startswith("统计审评"))


if __name__ == "__main__":
    unittest.main()
