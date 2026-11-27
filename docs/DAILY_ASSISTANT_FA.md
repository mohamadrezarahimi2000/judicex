# دستیار روزانه Judicex — نسخه توسعه‌یافته

این ماژول امکانات اسکن افزایشی، دسته‌بندی مقدماتی، استخراج نشانگرهای حقوقی، گزارش موعدها و خروجی‌گیری را فراهم می‌کند.

## ۲۶ گزینه عملیاتی

| گزینه | کارکرد |
|---|---|
| scan | اسکن پوشه‌های گوشی |
| report | گزارش روزانه |
| all | گزارش جامع |
| stats | آمار اسناد بر اساس نوع |
| decisions | فهرست آرای قضایی |
| notices | فهرست ابلاغیه‌ها |
| pleadings | فهرست لوایح و دادخواست‌ها |
| search | جست‌وجوی متن اسناد |
| case_numbers | استخراج الگوهای شماره پرونده |
| dates | استخراج تاریخ‌ها |
| articles | استخراج ارجاع مواد قانونی |
| amounts | استخراج مبالغ |
| deadlines | شناسایی عبارت‌های مرتبط با مهلت |
| parties | استخراج خطوط حاوی طرفین |
| insights | تحلیل ساختاری یک‌جا |
| duplicates | شناسایی فایل‌های تکراری |
| today | کارهای سررسید امروز |
| overdue | کارهای عقب‌افتاده |
| upcoming | موعدهای آینده |
| images | فهرست تصاویر |
| pdfs | فهرست PDFها |
| ocr | فهرست اسناد OCRشده |
| export_json | خروجی JSON |
| export_csv | خروجی CSV |
| health | بررسی سلامت ابزارها |
| help | فهرست امکانات |

## اجرا در Termux

ابتدا پوشه‌های موردنظر را اسکن کن:

```bash
cd ~/judicex
.venv/bin/python -m judicex_memory_os.daily_assistant --db ~/judicex-data/rahimi.db --scan ~/storage/shared/Download --scan ~/storage/shared/Documents
```

نمایش همه گزینه‌ها:

```bash
.venv/bin/python -m judicex_memory_os.daily_assistant --db ~/judicex-data/rahimi.db --list-options
```

گزارش جامع:

```bash
.venv/bin/python -m judicex_memory_os.daily_assistant --db ~/judicex-data/rahimi.db --action all
```

جست‌وجوی عبارت:

```bash
.venv/bin/python -m judicex_memory_os.daily_assistant --db ~/judicex-data/rahimi.db --action search --query "تجدیدنظرخواهی"
```

استخراج مواد قانونی:

```bash
.venv/bin/python -m judicex_memory_os.daily_assistant --db ~/judicex-data/rahimi.db --action articles
```

خروجی CSV:

```bash
.venv/bin/python -m judicex_memory_os.daily_assistant --db ~/judicex-data/rahimi.db --action export_csv --output ~/judicex-data/documents.csv
```

## محدودیت‌ها و ملاحظات حقوقی

- این گزینه‌ها ابزارهای کمکی و استخراج الگو هستند؛ تشخیص رأی/ابلاغیه و استخراج شماره‌ها ممکن است خطا داشته باشد.
- عبارت مهلت، به‌تنهایی مهلت قانونی قطعی نیست. تاریخ ابلاغ، نوع تصمیم، مقررات خاص و تعطیلات باید بررسی شوند.
- این نسخه هنوز تحلیل حقوقی مولد و خودکار با مدل زبانی را به ماژول اسکن متصل نکرده است.
- فایل‌ها فقط خوانده می‌شوند و در پرونده‌ای وارد یا حذف نمی‌شوند.
- اجرای خودکار روزانه به تنظیم زمان‌بند Android/Termux نیاز دارد.
- قبل از اتکا به خروجی، متن اصلی سند و صفحه مربوط کنترل شود.
