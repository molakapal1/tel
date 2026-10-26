"""آزمون کاربران و اتصال حساب‌ها (بخش ۲۴.۱ سند)."""
from __future__ import annotations

import time

from app.database.repositories import LinksRepo

from .conftest import USER1, USER2


# ---------- ثبت‌نام ----------
def test_register_new_user(services):
    assert services.user_service.register(USER1, "ali", "علی") is True
    u = services.users_repo.get(USER1)
    assert u["username"] == "ali"
    assert u["status"] == "active"


def test_duplicate_register_preserves_date(services):
    services.user_service.register(USER1, "ali", "علی")
    first = services.users_repo.get(USER1)["registered_at"]
    time.sleep(1.05)  # عبور از ثانیه برای اطمینان
    assert services.user_service.register(USER1, "ali2", "علی جدید") is False
    second = services.users_repo.get(USER1)
    assert second["registered_at"] == first  # تاریخ ثبت‌نام اولیه حفظ می‌شود
    assert second["username"] == "ali2"      # ولی نام کاربری به‌روز می‌شود


def test_block_unblock(services):
    services.user_service.register(USER1, "ali", None)
    assert services.users_repo.set_blocked(USER1, True, "test") is True
    assert services.users_repo.is_blocked(USER1) is True
    # کاربر مسدود به سرویس دسترسی ندارد (بخش ۶)
    access = services.user_service.check_access(USER1)
    assert access.allowed is False
    assert "مسدود" in access.reason
    assert services.users_repo.set_blocked(USER1, False) is True
    assert services.users_repo.is_blocked(USER1) is False


# ---------- اتصال اینستاگرام (بخش ۵) ----------
def test_link_code_flow(services):
    services.user_service.register(USER1, "ali", None)
    code = services.links_repo.create_code("alice_ig", ttl_seconds=600)
    assert len(code) == 6 and code.isdigit()
    ok, ig = services.links_repo.link(code, USER1)
    assert ok and ig == "alice_ig"
    link = services.links_repo.get_active(USER1)
    assert link["ig_username"] == "alice_ig"
    # کد یک‌بارمصرف است
    ok2, _ = services.links_repo.link(code, USER2)
    assert ok2 is False


def test_code_regenerated_while_valid(services):
    c1 = services.links_repo.create_code("bob_ig", ttl_seconds=600)
    c2 = services.links_repo.create_code("bob_ig", ttl_seconds=600)
    assert c1 == c2  # کد معتبر قبلی برگردانده می‌شود


def test_expired_code_rejected(services):
    code = services.links_repo.create_code("carol_ig", ttl_seconds=600)
    services.db.execute("UPDATE link_codes SET expires_at=? WHERE code=?", (int(time.time()) - 1, code))
    ok, msg = services.links_repo.link(code, USER1)
    assert ok is False
    assert "منقضی" in msg


def test_ig_account_one_to_one(services):
    services.user_service.register(USER1, "a", None)
    services.user_service.register(USER2, "b", None)
    code1 = services.links_repo.create_code("dave_ig")
    ok, _ = services.links_repo.link(code1, USER1)
    assert ok
    # همان یوزرنیم نمی‌تواند به تلگرام دیگری وصل شود
    code2 = services.links_repo.create_code("dave_ig")
    ok2, msg2 = services.links_repo.link(code2, USER2)
    assert ok2 is False
    # یک تلگرام نمی‌تواند دو اینستاگرام داشته باشد
    code3 = services.links_repo.create_code("erin_ig")
    ok3, msg3 = services.links_repo.link(code3, USER1)
    assert ok3 is False


def test_unlink_preserves_subscription(services):
    from .conftest import make_paid_sub
    services.user_service.register(USER1, "a", None)
    make_paid_sub(services, USER1)
    code = services.links_repo.create_code("frank_ig")
    services.links_repo.link(code, USER1)
    ig = services.links_repo.unlink_by_admin(USER1)
    assert ig == "frank_ig"
    # اشتراک پس از قطع اتصال هم باید موجود باشد (بخش ۵.۴)
    assert services.subs_repo.active_of(USER1) is not None
    assert services.links_repo.get_active(USER1) is None
