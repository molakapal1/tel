"""آزمون پلن‌ها و نسخه‌بندی (بخش ۲۴.۳ سند)."""
from __future__ import annotations

from app.services.plans import PlanConfig

from .conftest import OWNER, USER1, make_paid_sub


def _new_plan(services, name="gold", price=100000, **kw):
    cfg = PlanConfig(price=price, duration_value=30, duration_unit="day",
                     concurrent_downloads=2, wait_seconds=10, queue_limit=15, **kw)
    ok, res = services.plan_service.create_plan(name, name, "", cfg, OWNER)
    assert ok, res
    plan = services.plans_repo.get_by_name(name)
    version = services.plans_repo.current_version(plan["id"])
    services.plans_repo.publish_version(version["id"], "future")
    return plan


def test_create_and_publish(services):
    plan = _new_plan(services)
    v = services.plans_repo.current_version(plan["id"])
    assert v["status"] == "published"
    assert plan["current_version_id"] == v["id"]
    assert any(p["id"] == plan["id"] for p in services.plan_service.saleable_plans())


def test_invalid_config_rejected(services):
    bad = PlanConfig(price=-5, duration_value=0, duration_unit="day")
    ok, errors = services.plan_service.create_plan("bad", "بد", "", bad, OWNER)
    assert ok is False
    assert errors  # حداقل یک پیام خطای اعتبارسنجی


def test_price_change_keeps_old_orders(services):
    """تغییر قیمت نباید مبلغ سفارش‌های قبلی را تغییر دهد (بخش ۹.۳ و ۱۲.۴)."""
    plan = _new_plan(services, price=100000)
    # کاربر سفارش می‌دهد
    services.user_service.register(USER1, "u", None)
    ok, order_id = services.order_service.create_order(USER1, plan["id"])
    assert ok
    order = services.orders_repo.get(order_id)
    assert order["amount"] == 100000
    # نسخه جدید با قیمت بالاتر
    v = services.plans_repo.current_version(plan["id"])
    cfg = services.plan_service.config_of_version(v)
    cfg.price = 200000
    ok2, draft_id = services.plan_service.draft_new_version(plan["id"], cfg, OWNER, "گران‌تر")
    assert ok2
    services.plan_service.publish(draft_id, "future", OWNER)
    # سفارش قبلی همچنان با قیمت قدیمی است
    order_after = services.orders_repo.get(order_id)
    assert order_after["amount"] == 100000
    # سفارش جدید با قیمت جدید
    ok3, order_id2 = services.order_service.create_order(USER1, plan["id"])
    assert services.orders_repo.get(order_id2)["amount"] == 200000


def test_publish_scope_future_keeps_current_subs_on_old_version(services):
    plan = _new_plan(services)
    old_v = services.plans_repo.current_version(plan["id"])
    services.user_service.register(USER1, "u", None)
    sub_id = make_paid_sub(services, USER1, "gold")
    sub = services.subs_repo.get(sub_id)
    assert sub["plan_version_id"] == old_v["id"]
    # نسخه جدید فقط برای خریداران آینده
    cfg = services.plan_service.config_of_version(old_v)
    cfg.wait_seconds = 99
    _, draft_id = services.plan_service.draft_new_version(plan["id"], cfg, OWNER, "تغییر انتظار")
    services.plan_service.publish(draft_id, "future", OWNER)
    sub_after = services.subs_repo.get(sub_id)
    assert sub_after["plan_version_id"] == old_v["id"]  # مشترک فعلی روی نسخه قدیم ماند


def test_publish_scope_both_migrates_current_subs(services):
    plan = _new_plan(services)
    old_v = services.plans_repo.current_version(plan["id"])
    services.user_service.register(USER1, "u", None)
    sub_id = make_paid_sub(services, USER1, "gold")
    cfg = services.plan_service.config_of_version(old_v)
    cfg.wait_seconds = 5
    _, draft_id = services.plan_service.draft_new_version(plan["id"], cfg, OWNER, "بهبود")
    services.plan_service.publish(draft_id, "both", OWNER)
    assert services.subs_repo.get(sub_id)["plan_version_id"] != old_v["id"]


def test_archive_plan_stops_sale_but_keeps_history(services):
    plan = _new_plan(services)
    services.user_service.register(USER1, "u", None)
    make_paid_sub(services, USER1, "gold")
    assert services.plans_repo.archive_plan(plan["id"]) is True
    assert all(p["id"] != plan["id"] for p in services.plan_service.saleable_plans())
    assert services.subs_repo.active_of(USER1) is not None  # اشتراک فعال ماند
    assert services.plans_repo.affected_subscribers(plan["id"]) == 1


def test_version_history_trackable(services):
    """نسخه‌ها قابل بازبینی هستند (استاندارد ۱۸ بخش ۲۸)."""
    plan = _new_plan(services)
    v1 = services.plans_repo.current_version(plan["id"])
    cfg = services.plan_service.config_of_version(v1)
    cfg.price = 150000
    _, draft_id = services.plan_service.draft_new_version(plan["id"], cfg, OWNER, "v2")
    services.plan_service.publish(draft_id, "future", OWNER)
    versions = services.db.query(
        "SELECT * FROM plan_versions WHERE plan_id=? ORDER BY version", (plan["id"],))
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["status"] == "published" or versions[1]["status"] == "published"
