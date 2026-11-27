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




def _documents(db_path: str | Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM daily_scan_files ORDER BY scanned_at DESC").fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _matches(documents: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    needle = _normalize(pattern).casefold()
    return [d for d in documents if needle in _normalize(d.get("path", "") + "\\n" + d.get("extracted_text", "")).casefold()]


def _extract_values(text: str, pattern: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in re.finditer(pattern, _normalize(text), re.I)))


def document_insights(document: dict[str, Any]) -> dict[str, Any]:
    text = document.get("extracted_text", "")
    return {
        "path": document.get("path"),
        "category": document.get("category"),
        "case_numbers": _extract_values(text, r"(?:پرونده\\s*(?:کلاسه)?|شماره\\s*پرونده)\\s*[:：]?\\s*[0-9۰-۹/.-]{5,}"),
        "dates": _extract_values(text, r"(?<!\\d)(?:1[34][0-9]{2}|20[0-9]{2})[/.-](?:0?[1-9]|1[0-2])[/.-](?:0?[1-9]|[12][0-9]|3[01])(?!\\d)|(?<!\\d)(?:0?[1-9]|[12][0-9]|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:1[34][0-9]{2}|20[0-9]{2})(?!\\d)"),
        "amounts": _extract_values(text, r"[0-9۰-۹][0-9۰-۹,.٬]*\\s*(?:ریال|تومان)"),
        "legal_articles": _extract_values(text, r"ماده\\s*[0-9۰-۹]+(?:\\s*(?:و|تا)\\s*[0-9۰-۹]+)?"),
        "deadline_mentions": [line.strip() for line in text.splitlines() if re.search(r"مهلت|ظرف\\s+\\d+\\s+روز|روز\\s+از\\s+تاریخ|تجدیدنظرخواهی|واخواهی|فرجام", line)],
        "parties": [line.strip() for line in text.splitlines() if re.search(r"خواهان|خوانده|شاکی|متهم|محکوم\\s*له|محکوم\\s*علیه", line)],
        "extractor": document.get("extractor"),
    }


def run_action(db_path: str | Path, action: str, query: str = "", output: str = "") -> dict[str, Any]:
    docs = _documents(db_path)
    if action == "scan":
        raise ValueError("برای اسکن از گزینه --scan استفاده کنید.")
    if action == "report":
        return daily_report(db_path)
    if action == "all":
        return {"report": daily_report(db_path), "stats": run_action(db_path, "stats")}
    if action == "stats":
        counts: dict[str, int] = {}
        for d in docs:
            counts[d.get("category", "unknown")] = counts.get(d.get("category", "unknown"), 0) + 1
        return {"total": len(docs), "by_category": counts, "ocr_count": sum("ocr" in d.get("extractor", "") for d in docs)}
    if action in {"decisions", "notices", "pleadings", "images", "pdfs", "ocr"}:
        category_map = {"decisions": "court_decision", "notices": "court_notice", "pleadings": "pleading"}
        if action in category_map:
            found = [d for d in docs if d.get("category") == category_map[action]]
        elif action == "images":
            found = [d for d in docs if Path(d.get("path", "")).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}]
        elif action == "pdfs":
            found = [d for d in docs if Path(d.get("path", "")).suffix.lower() == ".pdf"]
        else:
            found = [d for d in docs if "ocr" in d.get("extractor", "")]
        return {"count": len(found), "documents": [{k: d.get(k) for k in ("path", "category", "extractor", "scanned_at")} for d in found]}
    if action in {"search", "case_numbers", "dates", "articles", "amounts", "deadlines", "parties", "insights"}:
        found = _matches(docs, query) if action == "search" and query else docs
        insights = [document_insights(d) for d in found]
        if action == "search":
            return {"query": query, "count": len(found), "documents": [d["path"] for d in found]}
        if action == "insights":
            return {"count": len(insights), "items": insights}
        key_map = {"case_numbers": "case_numbers", "dates": "dates", "articles": "legal_articles",
                   "amounts": "amounts", "deadlines": "deadline_mentions", "parties": "parties"}
        key = key_map[action]
        return {"count": sum(len(i[key]) for i in insights),
                "items": [{"path": i["path"], "values": i[key]} for i in insights if i[key]]}
    if action == "duplicates":
        groups: dict[str, list[str]] = {}
        for d in docs:
            groups.setdefault(d.get("sha256", ""), []).append(d.get("path", ""))
        return {"groups": [v for k, v in groups.items() if k and len(v) > 1]}
    if action in {"today", "overdue", "upcoming"}:
        tasks = daily_report(db_path, 3650)["upcoming_tasks"]
        if action == "today":
            tasks = [t for t in tasks if t["days_remaining"] == 0]
        elif action == "overdue":
            tasks = [t for t in tasks if t["days_remaining"] < 0]
        else:
            tasks = [t for t in tasks if t["days_remaining"] > 0]
        return {"count": len(tasks), "tasks": tasks}
    if action == "export_json":
        data = {"documents": docs, "report": daily_report(db_path, 3650)}
        target = Path(output or "judicex-daily-export.json")
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"exported": str(target), "documents": len(docs)}
    if action == "export_csv":
        import csv
        target = Path(output or "judicex-documents.csv")
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["path", "category", "extractor", "size", "scanned_at", "sha256"])
            writer.writeheader()
            writer.writerows({k: d.get(k, "") for k in writer.fieldnames} for d in docs)
        return {"exported": str(target), "documents": len(docs)}
    if action == "health":
        return {"database_exists": Path(db_path).exists(), "document_index": len(docs),
                "tesseract": shutil.which("tesseract") or "", "pdftoppm": shutil.which("pdftoppm") or ""}
    if action == "help":
        return {"options": OPTIONS}
    raise ValueError(f"گزینه ناشناخته: {action}")


OPTIONS = [
    {"id": "scan", "name": "اسکن پوشه‌های گوشی", "description": "شناسایی فایل‌های تازه و تغییرکرده"},
    {"id": "report", "name": "گزارش روزانه", "description": "نمایش اسناد و موعدهای نزدیک"},
    {"id": "all", "name": "گزارش جامع", "description": "ترکیب گزارش روزانه و آمار"},
    {"id": "stats", "name": "آمار اسناد", "description": "تعداد و دسته‌بندی اسناد"},
    {"id": "decisions", "name": "فهرست آرای قضایی", "description": "نمایش اسناد تشخیص‌داده‌شده به‌عنوان رأی"},
    {"id": "notices", "name": "فهرست ابلاغیه‌ها", "description": "نمایش ابلاغیه‌ها و اخطاریه‌ها"},
    {"id": "pleadings", "name": "فهرست لوایح و دادخواست‌ها", "description": "نمایش متون دفاعی و دادخواست‌ها"},
    {"id": "search", "name": "جست‌وجوی متن اسناد", "description": "جست‌وجوی واژه در اسناد استخراج‌شده"},
    {"id": "case_numbers", "name": "استخراج شماره پرونده", "description": "شناسایی الگوهای شماره پرونده"},
    {"id": "dates", "name": "استخراج تاریخ‌ها", "description": "یافتن تاریخ‌های درج‌شده در سند"},
    {"id": "articles", "name": "استخراج مواد قانونی", "description": "یافتن ارجاع‌های ماده قانونی"},
    {"id": "amounts", "name": "استخراج مبالغ", "description": "یافتن مبالغ ریالی و تومانی"},
    {"id": "deadlines", "name": "شناسایی عبارت‌های مهلت", "description": "یافتن اشاره‌های متنی به مواعد"},
    {"id": "parties", "name": "استخراج طرفین پرونده", "description": "یافتن خطوط حاوی مشخصات طرفین"},
    {"id": "insights", "name": "تحلیل ساختاری اسناد", "description": "تجمیع شماره‌ها، تاریخ‌ها، طرفین و مواد"},
    {"id": "duplicates", "name": "شناسایی فایل‌های تکراری", "description": "مقایسه هش SHA-256"},
    {"id": "today", "name": "کارهای سررسید امروز", "description": "نمایش وظایف ثبت‌شده برای امروز"},
    {"id": "overdue", "name": "کارهای عقب‌افتاده", "description": "نمایش وظایف با موعد گذشته"},
    {"id": "upcoming", "name": "موعدهای آینده", "description": "نمایش موعدهای آتی"},
    {"id": "images", "name": "فهرست تصاویر", "description": "نمایش تصاویر اسکن‌شده"},
    {"id": "pdfs", "name": "فهرست PDFها", "description": "نمایش اسناد PDF"},
    {"id": "ocr", "name": "فهرست اسناد OCRشده", "description": "نمایش اسناد پردازش‌شده با OCR"},
    {"id": "export_json", "name": "خروجی JSON", "description": "ذخیره گزارش و فهرست اسناد"},
    {"id": "export_csv", "name": "خروجی CSV", "description": "خروجی جدولی اسناد"},
    {"id": "health", "name": "بررسی سلامت", "description": "بررسی پایگاه داده و ابزارهای OCR"},
    {"id": "help", "name": "راهنمای امکانات", "description": "نمایش فهرست گزینه‌ها"},
]

def main() -> None:
    parser = argparse.ArgumentParser(description="Judicex daily assistant")
    parser.add_argument("--db", required=True)
    parser.add_argument("--scan", action="append", default=[], help="Directory to scan; may be repeated")
    parser.add_argument("--action", choices=[item["id"] for item in OPTIONS], default="all")
    parser.add_argument("--query", default="", help="Search term for --action search")
    parser.add_argument("--output", default="", help="Export file path")
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument("--list-options", action="store_true")
    args = parser.parse_args()
    if args.list_options:
        print(json.dumps(OPTIONS, ensure_ascii=False, indent=2))
        return
    result: dict[str, Any] = {}
    if args.scan:
        result["scan"] = scan_directories(args.db, args.scan)
    if args.action == "scan" and not args.scan:
        parser.error("برای action=scan حداقل یک --scan لازم است.")
    if args.action not in {"scan", "all", "report"}:
        result["result"] = run_action(args.db, args.action, args.query, args.output)
    elif args.action == "report":
        result["report"] = daily_report(args.db, max(0, args.horizon))
    elif args.action == "all":
        result["report"] = daily_report(args.db, max(0, args.horizon))
        result["stats"] = run_action(args.db, "stats")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
