# دستیار روزانه Judicex (نسخه نخست)

این ماژول اسکن افزایشی پوشه‌های انتخاب‌شده، استخراج متن و گزارش مواعد ثبت‌شده در پرونده‌ها را فراهم می‌کند.

## اجرا در Termux

از داخل پوشه مخزن:

```bash
.venv/bin/python -m judicex_memory_os.daily_assistant --db "$HOME/judicex-data/rahimi.db" --scan "$HOME/storage/shared/Download" --scan "$HOME/storage/shared/Documents" --horizon 7
```

برای اجرای روزانه ساعت ۷:۳۰ با Termux:API و cron، پس از نصب بسته `cronie` و تنظیم مسیرهای دلخواه:

```bash
crond
(crontab -l 2>/dev/null; echo '30 7 * * * cd $HOME/judicex && .venv/bin/python -m judicex_memory_os.daily_assistant --db $HOME/judicex-data/rahimi.db --scan $HOME/storage/shared/Download --scan $HOME/storage/shared/Documents --horizon 7 >> $HOME/judicex-data/daily-report.json 2>&1') | crontab -
```

اسکنر فایل‌های تکراری را با SHA-256 نادیده می‌گیرد و تغییرات بعدی را دوباره پردازش می‌کند. PDF متنی، DOCX، متن ساده و تصاویر/PDF اسکن‌شده (در صورت نصب Tesseract و Poppler) پشتیبانی می‌شوند. فایل‌ها به پرونده‌ای الصاق نمی‌شوند و محتوای استخراج‌شده در جدول محلی `daily_scan_files` نگهداری می‌شود.

## حدود نسخه نخست

این نسخه تحلیلگر زبانی/آنلاین رأی نیست و مهلت قانونی را از متن سند محاسبه یا قطعی نمی‌کند. فقط موعدهایی را گزارش می‌کند که قبلاً در وظایف Judicex ثبت شده‌اند. تحلیل حقوقی خودکار، تطبیق سند با پرونده، رابط داشبورد و اعلان واقعی اندروید در گام بعدی توسعه می‌یابند. اجرای زمان‌بندی‌شده در Termux نیازمند فعال بودن cron و محدود نبودن اجرای پس‌زمینه Termux توسط Android است.
