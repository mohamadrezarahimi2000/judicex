from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .store import LegalMemoryStore

ALLOWED = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
DECISION_WORDS = ("دادنامه", "رأی", "رای", "قرار", "حکم", "محکوم", "تجدیدنظر", "بدوی")
NOTICE_WORDS = ("ابلاغیه", "ابلاغ", "ثنا", "اخطاریه", "وقت رسیدگی", "جلسه رسیدگی")


def _normalize(value: str) -> str:
    return value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")


def _extract_text(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace"), "text"
    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs), "docx"
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
        text = "\n".join(f"[صفحه {i + 1}]\n{v}" for i, v in enumerate(pages) if v)
        if text.strip():
            return text, "pdf-text"
        if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
            return "", "pdf-scanned-needs-ocr"
        chunks = []
        with tempfile.TemporaryDirectory(prefix="judicex-ocr-") as tmp:
            prefix = str(Path(tmp) / "page")
            subprocess.run(["pdftoppm", "-r", "220", "-jpeg", str(path), prefix],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for image in sorted(Path(tmp).glob("page-*.jpg"))[:30]:
                result = subprocess.run(["tesseract", str(image), "stdout", "-l", "fas+eng"],
                                        check=True, capture_output=True, text=True)
                chunks.append(result.stdout.strip())
        return "\n".join(chunks), "pdf-ocr"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
        if not shutil.which("tesseract"):
            return "", "image-needs-ocr"
        result = subprocess.run(["tesseract", str(path), "stdout", "-l", "fas+eng"],
                                check=True, capture_output=True, text=True)
        return result.stdout, "image-ocr"
    return "", "unsupported"


def classify_document(filename: str, text: str) -> str:
    value = _normalize(filename + "\n" + text[:12000]).lower()
    if any(word in value for word in DECISION_WORDS):
        return "court_decision"
    if any(word in value for word in NOTICE_WORDS):
        return "court_notice"
    if "دادخواست" in value or "لایحه" in value:
        return "pleading"
    return "document"


def scan_directories(db_path: str | Path, directories: list[str | Path]) -> dict[str, Any]:
    db = sqlite3.connect(str(db_path))
    db.execute("""
        CREATE TABLE IF NOT EXISTS daily_scan_files (
            path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
            mtime REAL NOT NULL, category TEXT NOT NULL, extracted_text TEXT NOT NULL,
            extractor TEXT NOT NULL, scanned_at TEXT NOT NULL
        )
    """)
    db.commit()
    scanned, changed, errors = [], [], []
    for root_value in directories:
        root = Path(root_value).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            errors.append({"path": str(root), "error": "پوشه در دسترس نیست"})
            continue
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ALLOWED:
                continue
            try:
                stat = path.stat()
                if stat.st_size > 50 * 1024 * 1024:
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                old = db.execute("SELECT sha256 FROM daily_scan_files WHERE path=?", (str(path),)).fetchone()
                if old and old[0] == digest:
                    continue
                text, extractor = _extract_text(path)
                category = classify_document(path.name, text)
                db.execute("""
                    INSERT INTO daily_scan_files(path,sha256,size,mtime,category,extracted_text,extractor,scanned_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,size=excluded.size,
                    mtime=excluded.mtime,category=excluded.category,extracted_text=excluded.extracted_text,
                    extractor=excluded.extractor,scanned_at=excluded.scanned_at
                """, (str(path), digest, stat.st_size, stat.st_mtime, category, text,
                      extractor, datetime.now().astimezone().isoformat(timespec="seconds")))
                item = {"path": str(path), "category": category, "extractor": extractor,
                        "characters": len(text), "sha256": digest}
                scanned.append(item)
                changed.append(item)
            except Exception as exc:
                errors.append({"path": str(path), "error": str(exc)})
    db.commit()
    db.close()
    return {"scanned": len(scanned), "changed": changed, "errors": errors}


def daily_report(db_path: str | Path, horizon_days: int = 7) -> dict[str, Any]:
    today = date.today()
    with LegalMemoryStore(db_path) as store:
        tasks = store.list_matter_tasks(top_k=500)
    upcoming = []
    for task in tasks:
        due = str(task.get("due_date") or "")
        if task.get("status") == "done" or not due:
            continue
        try:
            due_date = date.fromisoformat(due[:10])
        except ValueError:
            continue
        days = (due_date - today).days
        if days <= horizon_days:
            upcoming.append({**task, "days_remaining": days,
                             "alert": "گذشته" if days < 0 else ("امروز" if days == 0 else f"{days} روز دیگر")})
    upcoming.sort(key=lambda item: (item["due_date"], item.get("priority") != "urgent"))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT path,category,extractor,scanned_at FROM daily_scan_files ORDER BY scanned_at DESC LIMIT 50").fetchall()
    conn.close()
    docs = [dict(row) for row in rows]
    return {"date": today.isoformat(), "upcoming_tasks": upcoming, "recent_documents": docs,
            "counts": {"upcoming": len(upcoming), "recent_documents": len(docs)}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Judicex daily document scan and deadline report")
    parser.add_argument("--db", required=True)
    parser.add_argument("--scan", action="append", default=[], help="Directory to scan; may be repeated")
    parser.add_argument("--horizon", type=int, default=7)
    args = parser.parse_args()
    result: dict[str, Any] = {}
    if args.scan:
        result["scan"] = scan_directories(args.db, args.scan)
    result["report"] = daily_report(args.db, max(0, args.horizon))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
