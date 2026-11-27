from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from judicex_memory_os.daily_assistant import classify_document, scan_directories
from judicex_memory_os.store import LegalMemoryStore


class DailyAssistantTests(unittest.TestCase):
    def test_document_classification(self):
        self.assertEqual(classify_document("دادنامه.pdf", ""), "court_decision")
        self.assertEqual(classify_document("scan.pdf", "ابلاغیه وقت رسیدگی"), "court_notice")
        self.assertEqual(classify_document("متن.txt", "دادخواست مطالبه وجه"), "pleading")

    def test_scan_is_incremental(self):
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


if __name__ == "__main__":
    unittest.main()
