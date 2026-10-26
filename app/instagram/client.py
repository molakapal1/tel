"""کلاینت اینستاگرام با نشست پایدار (بخش ۴.۳ سند — اسرار از محیط).

نکته مهم (بخش ۳.۱): instagrapi یک کتابخانه غیررسمی است و دریافت دایرکت
با آن «سرویس تضمین‌شده رسمی» محسوب نمی‌شود؛ محدودیت‌ها در README و
گزارش وضعیت مستند شده‌اند.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import ClientError, TwoFactorRequired

log = logging.getLogger("instagram.client")


class InstagramLoginError(Exception):
    pass


class InstagramClient:
    """پوشش امن و thread-safe کلاینت instagrapi با مدیریت نشست."""

    def __init__(self, username: str, password: str, session_file: Path,
                 proxy: str | None = None, two_factor_code: str | None = None):
        self.username = username
        self.password = password
        self.session_file = Path(session_file)
        self.proxy = proxy or None
        self.two_factor_code = two_factor_code or None
        self.cl: Client | None = None
        self._lock = threading.Lock()
        self.logged_in_at: int | None = None
        self.last_error: str | None = None

    # ---------- ورود ----------
    def login(self) -> bool:
        """ورود با نگهداری نشست؛ در صورت وجود نشست معتبر از آن استفاده می‌شود."""
        with self._lock:
            client = Client()
            client.delay_range = [2, 6]  # تأخیر تصادفی برای کاهش ریسک محدودسازی
            if self.proxy:
                client.set_proxy(self.proxy)
            if self.session_file.exists():
                try:
                    client.load_settings(str(self.session_file))
                except Exception as e:
                    log.warning("بارگذاری نشست ناموفق بود: %s", e)
            try:
                client.login(self.username, self.password)
            except TwoFactorRequired:
                if not self.two_factor_code:
                    self.last_error = "این اکانت دومرحله‌ای است؛ IG_2FA_CODE تنظیم نشده."
                    raise InstagramLoginError(self.last_error)
                client.login(self.username, self.password,
                             verification_code=self.two_factor_code)
            except ClientError as e:
                self.last_error = str(e)
                raise InstagramLoginError(f"ورود به اینستاگرام ناموفق: {e}")
            self.cl = client
            self.logged_in_at = int(time.time())
            self.last_error = None
            self._save_session()
            log.info("ورود موفق به اینستاگرام")
            return True

    def _save_session(self) -> None:
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            self.cl.dump_settings(str(self.session_file))
        except Exception as e:
            log.warning("ذخیره نشست ناموفق: %s", e)

    # ---------- ابزار عمومی ----------
    def with_client(self, fn):
        """اجرای امن یک عملیات با retry یک‌باره در صورت خرابی نشست."""
        for attempt in (1, 2):
            if self.cl is None:
                self.login()
            try:
                with self._lock:
                    return fn(self.cl)
            except Exception as e:
                self.last_error = str(e)
                log.warning("عملیات اینستاگرام ناموفق (تلاش %s): %s", attempt, e)
                if attempt == 1:
                    time.sleep(5)
                    try:
                        self.login()
                    except InstagramLoginError:
                        break
        raise ClientError(f"عملیات اینستاگرام پس از تلاش مجدد ناموفق: {self.last_error}")

    @property
    def is_ready(self) -> bool:
        return self.cl is not None and self.logged_in_at is not None
