from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from judicex_memory_os.daily_assistant import (
    OPTIONS, classify_document, document_insights, run_action, scan_directories,
)
from judicex_memory_os.store import LegalMemoryStore


class DailyAssistantTests(unittest.TestCase):
    def test_document_classification(self):
        self.assertEqual(classify_document("دادنامه.pdf", ""), "court_decision")
        self.assertEqual(classify_document("scan.pdf", "ابلاغیه وقت رسیدگی"), "court_notice")
        self.assertEqual(classify_document("متن.txt", "دادخواست مطالبه وجه"), "pleading")

    def test_scan_is_incremental_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "docs"
            root.mkdir()
            (root / "دادنامه.txt").write_text("رأی دادگاه بدوی", encoding="utf-8")
            db = Path(tmp) / "judicex.db"
            with LegalMemoryStore(db):
                pass
            first = scan_directories(db, [root])
            second = scan_directories(db, [root])
            self.assertEqual(first["scanned"], 1)
            self.assertEqual(second["scanned"], 0)
            self.assertEqual(first["changed"][0]["category"], "court_decision")

    def test_at_least_twenty_options_are_registered(self):
        self.assertGreaterEqual(len(OPTIONS), 20)
        self.assertEqual(len({item["id"] for item in OPTIONS}), len(OPTIONS))

    def test_document_insights_extract_basic_legal_markers(self):
        result = document_insights({
            "path": "decision.txt",
            "category": "court_decision",
            "extractor": "text",
            "extracted_text": "شماره پرونده: ۱۴۰۳/۱۲۳۴۵ ماده ۱۰ قانون مدنی مبلغ ۵۰۰۰۰۰ ریال مهلت تجدیدنظرخواهی",
        })
        self.assertTrue(result["case_numbers"])
        self.assertTrue(result["legal_articles"])
        self.assertTrue(result["amounts"])
        self.assertTrue(result["deadline_mentions"])

    def test_action_help_and_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "judicex.db"
            with LegalMemoryStore(db):
                pass
            self.assertGreaterEqual(len(run_action(db, "help")["options"]), 20)
            self.assertEqual(run_action(db, "stats")["total"], 0)


if __name__ == "__main__":
    unittest.main()
