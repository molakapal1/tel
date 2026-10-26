"""نقش‌ها، مجوزها و کنترل دسترسی سمت سرور (بخش ۱۹ سند).

بخش ۱۹.۴: هر عملیات باید سمت سرور مجوز مربوط را بررسی کند؛ مخفی‌کردن
دکمه یا دستور به‌تنهایی کنترل دسترسی محسوب نمی‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------- مجوزهای مستقل (بخش ۱۹.۳) ----------
PERM_VIEW_USERS = "view_users"
PERM_EDIT_USERS = "edit_users"
PERM_BLOCK_USERS = "block_users"
PERM_CHANGE_PLAN = "change_plan"
PERM_CHANGE_PRICE = "change_price"
PERM_CREATE_PROMO = "create_promo"
PERM_VIEW_ORDERS = "view_orders"
PERM_APPROVE_PAYMENT = "approve_payment"
PERM_REJECT_PAYMENT = "reject_payment"
PERM_CANCEL_SUBSCRIPTION = "cancel_subscription"
PERM_COMMERCIAL_SETTINGS = "commercial_settings"
PERM_BROADCAST = "broadcast"
PERM_REPORTS = "reports"
PERM_MANAGE_ADMINS = "manage_admins"
PERM_TECH_SETTINGS = "tech_settings"

ALL_PERMISSIONS: list[str] = [
    PERM_VIEW_USERS, PERM_EDIT_USERS, PERM_BLOCK_USERS, PERM_CHANGE_PLAN,
    PERM_CHANGE_PRICE, PERM_CREATE_PROMO, PERM_VIEW_ORDERS, PERM_APPROVE_PAYMENT,
    PERM_REJECT_PAYMENT, PERM_CANCEL_SUBSCRIPTION, PERM_COMMERCIAL_SETTINGS,
    PERM_BROADCAST, PERM_REPORTS, PERM_MANAGE_ADMINS, PERM_TECH_SETTINGS,
]

PERM_LABELS: dict[str, str] = {
    PERM_VIEW_USERS: "مشاهده کاربران",
    PERM_EDIT_USERS: "ویرایش کاربران",
    PERM_BLOCK_USERS: "مسدودسازی کاربر",
    PERM_CHANGE_PLAN: "تغییر پلن",
    PERM_CHANGE_PRICE: "تغییر قیمت",
    PERM_CREATE_PROMO: "ساخت کد اشتراک",
    PERM_VIEW_ORDERS: "مشاهده سفارش‌ها",
    PERM_APPROVE_PAYMENT: "تأیید پرداخت",
    PERM_REJECT_PAYMENT: "رد پرداخت",
    PERM_CANCEL_SUBSCRIPTION: "لغو اشتراک",
    PERM_COMMERCIAL_SETTINGS: "تنظیمات تجاری",
    PERM_BROADCAST: "پیام همگانی",
    PERM_REPORTS: "گزارش‌ها",
    PERM_MANAGE_ADMINS: "مدیریت مدیران",
    PERM_TECH_SETTINGS: "تنظیمات فنی",
}

# ---------- نقش‌های سیستتی (بخش ۱۹.۱) ----------
# (نام، مجوزها، is_system)
SYSTEM_ROLES: list[tuple[str, list[str], int]] = [
    ("owner", ["*"], 1),
    ("tech", [PERM_VIEW_USERS, PERM_VIEW_ORDERS, PERM_REPORTS, PERM_TECH_SETTINGS], 1),
    ("support", [PERM_VIEW_USERS, PERM_VIEW_ORDERS, PERM_REPORTS], 1),
    ("subs_manager", [
        PERM_VIEW_USERS, PERM_EDIT_USERS, PERM_VIEW_ORDERS, PERM_CHANGE_PLAN,
        PERM_CREATE_PROMO, PERM_CANCEL_SUBSCRIPTION, PERM_REPORTS,
    ], 1),
    ("sales", [
        PERM_VIEW_USERS, PERM_VIEW_ORDERS, PERM_APPROVE_PAYMENT, PERM_REJECT_PAYMENT,
        PERM_CHANGE_PRICE, PERM_COMMERCIAL_SETTINGS, PERM_REPORTS, PERM_BROADCAST,
    ], 1),
]

ROLE_LABELS: dict[str, str] = {
    "owner": "مدیر اصلی",
    "tech": "مدیر فنی",
    "support": "مدیر پشتیبانی",
    "subs_manager": "مدیر اشتراک‌ها",
    "sales": "مدیر فروش",
}


@dataclass
class AdminContext:
    """زمینه مدیر پس از احراز دسترسی."""
    telegram_id: int
    role_name: str
    permissions: list[str]

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


class AccessDenied(Exception):
    """دسترسی رد شده — برای آزمون‌های امنیتی قابل assert است."""


class PermissionService:
    """بررسی مجوز سمت سرور برای هر عملیات (بخش ۱۶.۳ و ۲۲.۴)."""

    def __init__(self, admins_repo):
        self.repo = admins_repo

    def context_of(self, telegram_id: int) -> AdminContext | None:
        row = self.repo.get_admin(telegram_id)
        if not row:
            return None
        import json
        return AdminContext(
            telegram_id=telegram_id,
            role_name=row["role_name"],
            permissions=json.loads(row["permissions"]),
        )

    def check(self, telegram_id: int, permission: str) -> AdminContext:
        ctx = self.context_of(telegram_id)
        if ctx is None:
            raise AccessDenied("شما مدیر مجاز نیستید.")
        if not ctx.has(permission):
            raise AccessDenied(f"نقش «{ROLE_LABELS.get(ctx.role_name, ctx.role_name)}» "
                               f"مجوز «{PERM_LABELS.get(permission, permission)}» را ندارد.")
        return ctx
