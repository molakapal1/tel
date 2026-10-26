"""سرویس کاربران و دسترسی (بخش ۵ و ۶ سند)."""
from __future__ import annotations

from ..database.repositories import LinksRepo, SubscriptionsRepo, UsersRepo
from .settings import SettingsService


class AccessResult:
    """نتیجه بررسی شرایط استفاده از سرویس (گام ۳ و ۴ جریان اصلی)."""

    def __init__(self, allowed: bool, reason: str = "", limits: dict | None = None,
                 subscription=None):
        self.allowed = allowed
        self.reason = reason
        self.limits = limits or {}
        self.subscription = subscription

    def __bool__(self):
        return self.allowed


class UserService:
    def __init__(self, users: UsersRepo, links: LinksRepo, subs: SubscriptionsRepo,
                 settings: SettingsService):
        self.users = users
        self.links = links
        self.subs = subs
        self.settings = settings

    def register(self, telegram_id: int, username: str | None, name: str | None) -> bool:
        """ثبت‌نام هنگام Start؛ True یعنی ثبت‌نام جدید (بخش ۶.۱)."""
        return self.users.register(telegram_id, username, name)

    def check_access(self, telegram_id: int) -> AccessResult:
        """بررسی وضعیت کاربر برای استفاده از سرویس.

        ترتیب: مسدودی → حالت تعمیر → حالت تجاری → اشتراک فعال.
        خروجی شامل محدودیت‌های مؤثر دانلود نیز هست.
        """
        user = self.users.get(telegram_id)
        if not user:
            return AccessResult(False, "ابتدا /start را بفرست.")
        if user["status"] == "blocked":
            return AccessResult(False, "حساب شما مسدود شده است. با پشتیبانی تماس بگیر.")

        if self.settings.sales_mode == "free":
            return AccessResult(True, limits=self.settings.free_mode_config)

        sub = self.subs.active_of(telegram_id)
        if not sub:
            return AccessResult(False, "برای استفاده از سرویس اشتراک فعال لازم است. /plans را ببین.")
        return AccessResult(True, limits={}, subscription=sub)

    def status_summary(self, telegram_id: int) -> dict:
        """خلاصه وضعیت برای نمایش به کاربر."""
        sub = self.subs.active_of(telegram_id)
        link = self.links.get_active(telegram_id)
        return {
            "user": self.users.get(telegram_id),
            "subscription": sub,
            "link": link,
            "sales_mode": self.settings.sales_mode,
        }
