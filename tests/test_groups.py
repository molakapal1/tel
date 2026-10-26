"""آزمون گروه‌های کاربری و سیاست‌ها (بخش ۲۴.۲ سند)."""
from __future__ import annotations

import time

from .conftest import OWNER, USER1, USER2, make_paid_sub


def _register_many(services, ids):
    for i, uid in enumerate(ids):
        services.user_service.register(uid, f"user{i}", None)
        if i:  # فاصله زمانی برای تفکیک مرز
            time.sleep(0.01)
    return services.users_repo.get(ids[-1])["registered_at"]


def test_boundary_split_old_new(services):
    """تاریخ مرزی T: قدیمی‌ها قبل، جدیدها بعد از T (بخش ۷.۱)."""
    _register_many(services, [USER1, USER2])
    now = int(time.time())
    # ثبت‌نام با زمان‌های صریح و قابل تفکیک
    services.db.execute("UPDATE users SET registered_at=? WHERE telegram_id=?", (now - 200, USER1))
    services.db.execute("UPDATE users SET registered_at=? WHERE telegram_id=?", (now - 50, USER2))
    result = services.group_service.split_by_boundary(now - 100)
    assert USER1 in result["old_ids"]
    assert USER2 in result["new_ids"]


def test_time_window_group_members(services):
    _register_many(services, [USER1, USER2])
    now = int(time.time())
    services.db.execute("UPDATE users SET registered_at=? WHERE telegram_id=?", (now - 200, USER1))
    services.db.execute("UPDATE users SET registered_at=? WHERE telegram_id=?", (now - 50, USER2))
    ok, _ = services.group_service.create_time_group("کاربران اول", None, now - 100)
    assert ok
    g = services.groups_repo.list()[0]
    members = services.groups_repo.member_ids(g["id"])
    assert USER1 in members and USER2 not in members


def test_filter_group_active_sub(services):
    _register_many(services, [USER1, USER2])
    make_paid_sub(services, USER1)
    ok, _ = services.group_service.create_filter_group("مشترکان فعال", "active_sub", None)
    g = services.groups_repo.list()[0]
    members = services.groups_repo.member_ids(g["id"])
    assert USER1 in members and USER2 not in members


def test_policy_preview_and_apply_gift(services):
    """پیش‌نمایش تعداد مشمول + اجرای سیاست هدیه (بخش ۷.۵ و ۷.۷)."""
    _register_many(services, [USER1, USER2])
    plan = services.plans_repo.get_by_name("basic_month")
    ok, _ = services.group_service.create_filter_group("همه", "active_sub", None)
    # گروه بدون مشترک → کاربر مستقیم اضافه می‌کنیم (گروه دستی ساده‌تر است)
    ok2, gid = services.group_service.create_manual_group("منتخبان", [USER1, USER2])
    assert ok2
    ok3, policy_id = services.group_service.propose_policy(
        gid, "gift_subscription", {"plan_id": plan["id"]}, None, OWNER)
    assert ok3
    policy = services.groups_repo.policy(policy_id)
    assert policy["preview_count"] == 2  # پیش‌نمایش تعداد مشمول
    assert policy["status"] == "previewed"
    result = services.group_service.apply_policy(policy_id, OWNER)
    assert result["ok"] and result["affected"] == 2
    # هر دو کاربر اشتراک هدیه دارند
    assert services.subs_repo.active_of(USER1) is not None
    assert services.subs_repo.active_of(USER2) is not None
    # تاریخچه سیاست ثبت شده است (بخش ۷.۷)
    history = services.groups_repo.policy_history()
    assert any(h["id"] == policy_id and h["status"] == "applied" for h in history)


def test_scheduled_policy_runs_when_due(services):
    """اجرای زمان‌بندی‌شده پس از سررسید (بخش ۷.۶) — حتی اگر ربات در زمان
    مقرر خاموش بوده باشد، پس از راه‌اندازی سیاست اجرا می‌شود."""
    _register_many(services, [USER1])
    plan = services.plans_repo.get_by_name("basic_month")
    _, gid = services.group_service.create_manual_group("تست زمان‌بندی", [USER1])
    future = int(time.time()) + 3600
    ok, policy_id = services.group_service.propose_policy(
        gid, "gift_subscription", {"plan_id": plan["id"]}, future, OWNER)
    assert ok
    # شبیه‌سازی: زمان مقرر گذشته و ربات تازه روشن شده است
    services.db.execute("UPDATE group_policies SET scheduled_at=? WHERE id=?",
                        (int(time.time()) - 5, policy_id))
    results = services.group_service.run_due_policies()
    assert any(r.get("ok") and r.get("policy_id") == policy_id for r in results)
    assert services.subs_repo.active_of(USER1) is not None


def test_future_schedule_rejected(services):
    _register_many(services, [USER1])
    _, gid = services.group_service.create_manual_group("گ", [USER1])
    ok, msg = services.group_service.propose_policy(
        gid, "no_change", {}, int(time.time()) - 100, OWNER)
    assert ok is False  # زمان گذشته پذیرفته نمی‌شود
