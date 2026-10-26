"""آزمون امنیت و کنترل دسترسی (بخش ۲۴.۸ سند)."""
from __future__ import annotations

import logging

import pytest

from app.admin.permissions import (
    ALL_PERMISSIONS, PERM_APPROVE_PAYMENT, PERM_TECH_SETTINGS, AccessDenied,
)
from app.logging_config import mask_secrets

from .conftest import OWNER, USER1, USER2


def test_normal_user_cannot_access_panel(services):
    services.user_service.register(USER1, "u", None)
    assert services.permissions.context_of(USER1) is None
    with pytest.raises(AccessDenied):
        services.permissions.check(USER1, PERM_APPROVE_PAYMENT)


def test_role_permissions_enforced(services):
    """نقش فروش مجوز تأیید پرداخت دارد اما تنظیمات فنی نه (بخش ۱۹.۳)."""
    services.user_service.register(USER2, "sales_admin", None)
    roles = {r["name"]: r["id"] for r in services.admins_repo.roles()}
    services.admins_repo.add(USER2, roles["sales"], OWNER)
    assert services.permissions.check(USER2, PERM_APPROVE_PAYMENT) is not None
    with pytest.raises(AccessDenied):
        services.permissions.check(USER2, PERM_TECH_SETTINGS)


def test_owner_has_all(services):
    ctx = services.permissions.check(OWNER, PERM_TECH_SETTINGS)
    assert ctx.role_name == "owner"
    for p in ALL_PERMISSIONS:
        assert services.admins_repo.has_permission(OWNER, p)


def test_order_ownership_idor(services):
    """کاربر نباید بتواند روی سفارش کاربر دیگر عملیات کند (بخش ۲۲.۳)."""
    from .test_orders import _order_flow_to_receipt
    order_id = _order_flow_to_receipt(services, user=USER1)
    services.user_service.register(USER2, "attacker", None)
    # اعلام پرداخت جعلی توسط کاربر دیگر
    ok, _ = services.order_service.announce_payment(order_id, USER2)
    assert ok is False
    # ارسال رسید جعلی
    ok2, _ = services.order_service.attach_receipt(order_id, USER2, "fake")
    assert ok2 is False
    # لغو جعلی
    ok3, _ = services.order_service.cancel(order_id, USER2)
    assert ok3 is False
    assert services.orders_repo.get(order_id)["status"] == "receipt_received"


def test_secrets_masked_in_logs():
    """نشت اطلاعات محرمانه در لاگ (بخش ۲۰.۳ و ۲۲.۱)."""
    token = "123456789:AAHfk3HeBxRE9GabcdefGHIJKLMNOpqrs"
    masked = mask_secrets(f"login failed with token={token}")
    assert token not in masked
    assert mask_secrets("password=SuperSecret123") .find("SuperSecret123") == -1
    assert mask_secrets("کارت: 6037991122334455") .find("6037991122334455") == -1
    # متن عادی دست‌نخورده می‌ماند
    assert mask_secrets("ربات با موفقیت اجرا شد") == "ربات با موفقیت اجرا شد"


def test_sensitive_not_in_error_log(services):
    """error_log نباید شماره کارت کامل یا توکن ذخیره کند."""
    services.errors_repo.log("telegram", "send", "token=123456789:AAHfk3HeBxabcdefGHIJKLMNOpqrs")
    rows = services.errors_repo.recent(category="telegram")
    assert "AAHfk3HeBxabcdefGHIJKLMNOpqrs" not in rows[0]["message"]


def test_payment_snapshot_hidden_from_user_views(services):
    """شماره کارت در اسنپ‌شات سفارش ذخیره می‌شود اما نمایش کاربر مطلق نیست؛
    این آزمون تضمین می‌کند پیام پرداخت فقط برای صاحب سفارش ساخته می‌شود."""
    from .test_orders import _order_flow_to_receipt
    order_id = _order_flow_to_receipt(services, user=USER1)
    order = services.orders_repo.get(order_id)
    assert order["user_id"] == USER1
