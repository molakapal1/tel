"""آزمون سفارش، پرداخت دستی و اشتراک (بخش ۲۴.۴ و ۲۴.۵ سند)."""
from __future__ import annotations

import time

from .conftest import OWNER, USER1, USER2, make_paid_sub


def _order_flow_to_receipt(services, user=USER1, plan_name="basic_month"):
    services.user_service.register(user, "u", None)
    plan = services.plans_repo.get_by_name(plan_name)
    ok, order_id = services.order_service.create_order(user, plan["id"])
    assert ok, order_id
    services.order_service.announce_payment(order_id, user)
    ok2, msg = services.order_service.attach_receipt(order_id, user, "file_id_1")
    assert ok2
    return order_id


def test_create_order_snapshot(services):
    """اسنپ‌شات روش پرداخت در لحظه ثبت سفارش (بخش ۱۳.۳)."""
    services.user_service.register(USER1, "u", None)
    plan = services.plans_repo.get_by_name("basic_month")
    _, order_id = services.order_service.create_order(USER1, plan["id"])
    order = services.orders_repo.get(order_id)
    import json
    snap = json.loads(order["payment_snapshot"])
    assert snap["card_number"]
    assert order["status"] == "awaiting_payment"
    # تغییر کارت بعداً روی سفارش قبلی اثر نمی‌گذارد
    services.payments_repo.update(snap.get("id") or 1, card_number="9999-9999")
    order2 = services.orders_repo.get(order_id)
    assert json.loads(order2["payment_snapshot"])["card_number"] == snap["card_number"]


def test_payment_message_contains_order_info(services):
    services.user_service.register(USER1, "u", None)
    plan = services.plans_repo.get_by_name("basic_month")
    _, order_id = services.order_service.create_order(USER1, plan["id"])
    order = services.orders_repo.get(order_id)
    text = services.order_service.payment_text(order)
    assert order_id in text
    assert "تومان" in text


def test_approve_activates_subscription(services):
    order_id = _order_flow_to_receipt(services)
    ok, msg = services.order_service.approve(order_id, OWNER)
    assert ok
    order = services.orders_repo.get(order_id)
    assert order["status"] == "confirmed"
    assert order["subscription_id"]
    sub = services.subs_repo.get(order["subscription_id"])
    assert sub["status"] == "active"
    assert sub["source"] == "purchase"
    assert services.subs_repo.active_of(USER1) is not None


def test_double_approve_prevented(services):
    """جلوگیری از تأیید تکراری — استاندارد اجباری ۵ بخش ۲۸ (بخش ۱۳.۸)."""
    order_id = _order_flow_to_receipt(services)
    ok1, _ = services.order_service.approve(order_id, OWNER)
    ok2, msg2 = services.order_service.approve(order_id, OWNER)
    assert ok1 is True
    assert ok2 is False
    assert "قبلاً" in msg2
    # فقط یک اشتراک ساخته شده است
    count = services.db.scalar(
        "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (USER1,))
    assert count == 1


def test_reject_with_reason(services):
    order_id = _order_flow_to_receipt(services)
    ok, _ = services.order_service.reject(order_id, OWNER, "رسید ناقص")
    assert ok
    order = services.orders_repo.get(order_id)
    assert order["status"] == "rejected"
    assert order["rejection_reason"] == "رسید ناقص"
    # اشتراکی ساخته نشده
    assert services.subs_repo.active_of(USER1) is None


def test_user_cancel_open_order(services):
    services.user_service.register(USER1, "u", None)
    plan = services.plans_repo.get_by_name("basic_month")
    _, order_id = services.order_service.create_order(USER1, plan["id"])
    ok, _ = services.order_service.cancel(order_id, USER1)
    assert ok
    assert services.orders_repo.get(order_id)["status"] == "canceled"
    # پس از تأیید، لغو ممکن نیست
    order_id2 = _order_flow_to_receipt(services)
    services.order_service.approve(order_id2, OWNER)
    ok2, _ = services.order_service.cancel(order_id2, USER1)
    assert ok2 is False


def test_order_expiry_sweep(services):
    services.user_service.register(USER1, "u", None)
    plan = services.plans_repo.get_by_name("basic_month")
    _, order_id = services.order_service.create_order(USER1, plan["id"])
    services.db.execute("UPDATE orders SET expires_at=? WHERE id=?",
                        (int(time.time()) - 1, order_id))
    assert services.orders_repo.sweep_expired() >= 1
    assert services.orders_repo.get(order_id)["status"] == "expired"


def test_subscription_extension_policy(services):
    """سیاست تمدید (بخش ۱۳.۹): فعال → افزودن به انتها؛ منقضی → شروع از الان."""
    order_id = _order_flow_to_receipt(services)
    services.order_service.approve(order_id, OWNER)
    sub1 = services.subs_repo.active_of(USER1)
    exp1 = sub1["expires_at"]
    # خرید دوم → تمدید همان اشتراک
    order_id2 = _order_flow_to_receipt(services)
    services.order_service.approve(order_id2, OWNER)
    sub2 = services.subs_repo.active_of(USER1)
    assert sub2["id"] == sub1["id"]
    assert sub2["expires_at"] > exp1
    ext_rows = services.db.query(
        "SELECT * FROM subscription_extensions WHERE subscription_id=?", (sub1["id"],))
    assert len(ext_rows) == 1


def test_promo_code_redeem(services):
    services.user_service.register(USER1, "u", None)
    plan = services.plans_repo.get_by_name("basic_month")
    codes = services.codes_repo.generate(plan["id"], 7 * 86400, max_uses=1, expires_at=None,
                                         created_by=OWNER, count=1)
    code = codes[0]
    ok, msg = services.sub_service.redeem_code(code, USER1)
    assert ok, msg
    sub = services.subs_repo.active_of(USER1)
    assert sub is not None
    # استفاده مجدد توسط همان کاربر ممنوع (بخش ۱۴.۳)
    ok2, msg2 = services.sub_service.redeem_code(code, USER1)
    assert ok2 is False
    # و توسط کاربر دیگر (سقف ۱)
    services.user_service.register(USER2, "v", None)
    ok3, _ = services.sub_service.redeem_code(code, USER2)
    assert ok3 is False


def test_promo_code_cancel_keeps_activated(services):
    """لغو کد استفاده‌نشده اشتراک‌های فعال‌شده را باطل نمی‌کند (بخش ۱۴.۳)."""
    services.user_service.register(USER1, "u", None)
    plan = services.plans_repo.get_by_name("basic_month")
    codes = services.codes_repo.generate(plan["id"], 86400, 2, None, batch_id="B1",
                                         created_by=OWNER, count=2)
    ok, _ = services.sub_service.redeem_code(codes[0], USER1)
    assert ok
    canceled = services.codes_repo.cancel_batch("B1")
    # codes[0] استفاده‌شده است → لغو نمی‌شود؛ codes[1] لغو می‌شود
    assert canceled == 1
    assert services.codes_repo.get(codes[0])["status"] == "active"
    assert services.codes_repo.get(codes[1])["status"] == "canceled"
    assert services.subs_repo.active_of(USER1) is not None


def test_trial_grant_once(services):
    """کنترل سوءاستفاده آزمایش (بخش ۱۰.۴)."""
    services.user_service.register(USER1, "u", None)
    plan = services.plans_repo.get_by_name("free_trial")
    ok1, _ = services.sub_service.grant_trial(USER1, plan["id"], "user")
    ok2, msg2 = services.sub_service.grant_trial(USER1, plan["id"], "user")
    assert ok1
    assert ok2 is False  # دفعه دوم رد می‌شود


def test_gift_days(services):
    services.user_service.register(USER1, "u", None)
    make_paid_sub(services, USER1)
    sub = services.subs_repo.active_of(USER1)
    before = sub["expires_at"]
    services.sub_service.gift_days(USER1, sub["plan_id"], 3, OWNER)
    after = services.subs_repo.active_of(USER1)
    assert after["expires_at"] == before + 3 * 86400


def test_subscription_expiry(services):
    services.user_service.register(USER1, "u", None)
    make_paid_sub(services, USER1)
    sub = services.subs_repo.active_of(USER1)
    services.db.execute("UPDATE subscriptions SET expires_at=? WHERE id=?",
                        (int(time.time()) - 10, sub["id"]))
    assert services.subs_repo.sweep_expired() == 1
    assert services.subs_repo.active_of(USER1) is None
