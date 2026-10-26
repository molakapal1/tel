"""پیکربندی ثبت رویداد و خطا.

بخش ۲۰.۳ سند: توکن، رمز عبور، کوکی، سشن و سایر اطلاعات محرمانه نباید در
گزارش‌ها ظاهر شوند؛ به همین دلیل یک فیلتر ماسک‌کننده روی همه هندل‌ها
نصب می‌شود.
"""
from __future__ import annotations

import logging
import logging.handlers
import re

# الگوهای محرمانه که باید پیش از ثبت ماسک شوند
_SECRET_PATTERNS = [
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),          # توکن ربات
    re.compile(r"(?i)(password|passwd|token|secret|cookie|session)"
               r"(['\"=:\s]+)([^'\"\s,;]{4,})"),
    re.compile(r"\b\d{16}\b"),                                 # شماره کارت
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
]

_MASK = "***MASKED***"


def mask_secrets(text: str) -> str:
    """متن لاگ را از اطلاعات محرمانه پاک می‌کند."""
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.search(out):
            out = pat.sub(_MASK, out)
    return out


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        masked = mask_secrets(msg)
        if masked != msg:
            record.msg = masked
            record.args = ()
        return True


def setup_logging(logs_dir, level: str = "INFO") -> None:
    """راه‌اندازی لاگ کنسول + فایل چرخشی با ماسک اطلاعات محرمانه."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt))

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(fmt))

    masking = SecretMaskingFilter()
    console.addFilter(masking)
    file_handler.addFilter(masking)

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    # کاهش نویز کتابخانه‌ها
    for noisy in ("apscheduler", "instagrapi", "asyncio", "aiogram.event"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
