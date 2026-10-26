"""سرویس گروه‌های کاربری و سیاست‌ها (بخش ۷ سند).

گروه‌ها: بازه زمانی ثبت‌نام (نسل‌ها)، فیلتر وضعیت، یا انتخاب دستی.
سیاست‌ها با پیش‌نمایش تعداد مشمول و اجرای فوری یا زمان‌بندی‌شده اعمال
می‌شوند و تاریخچه آن‌ها نگه داشته می‌شود.
"""
from __future__ import annotations

import json
import time

from ..database.repositories import GroupsRepo, PlansRepo, SubscriptionsRepo

NOW = lambda: int(time.time())  # noqa: E731


class GroupService:
    def __init__(self, groups: GroupsRepo, subs: SubscriptionsRepo, plans: PlansRepo):
        self.groups = groups
        self.subs = subs
        self.plans = plans

    # ---------- ساخت گروه ----------
    def create_time_group(self, name: str, start: int | None, end: int | None) -> tuple[bool, int | str]:
        if start is None and end is None:
            return False, "حداقل یک مرز زمانی لازم است."
        if start and end and start >= end:
            return False, "مرز شروع باید قبل از مرز پایان باشد."
        group_id = self.groups.create(name, "time_window", boundary_start=start, boundary_end=end)
        return True, group_id

    def create_filter_group(self, name: str, filter_type: str,
                            filter_value: str | None) -> tuple[bool, int | str]:
        valid = {"active_sub", "no_sub", "expired_sub", "blocked", "plan"}
        if filter_type not in valid:
            return False, "نوع فیلتر نامعتبر است."
        group_id = self.groups.create(name, "filter", filter_type=filter_type, filter_value=filter_value)
        return True, group_id

    def create_manual_group(self, name: str, user_ids: list[int]) -> tuple[bool, int | str]:
        group_id = self.groups.create(name, "manual")
        self.groups.add_members(group_id, user_ids)
        return True, group_id

    # ---------- پیش‌نمایش و اجرای سیاست (بخش ۷.۵ تا ۷.۷) ----------
    POLICY_LABELS = {
        "gift_subscription": "هدیه اشتراک",
        "extend_active": "تمدید اشتراک فعال",
        "no_change": "بدون تغییر (فقط ثبت)",
    }

    def propose_policy(self, group_id: int, action: str, params: dict,
                       scheduled_at: int | None, created_by: int) -> tuple[bool, str | int]:
        if action not in self.POLICY_LABELS:
            return False, "سیاست نامعتبر است."
        if action in ("gift_subscription", "extend_active") and "plan_id" not in params:
            return False, "برای این سیاست انتخاب پلن لازم است."
        if scheduled_at and scheduled_at <= NOW():
            return False, "زمان اجرا باید در آینده باشد."
        policy_id = self.groups.create_policy(group_id, action, params, scheduled_at, created_by)
        count = len(self.groups.member_ids(group_id))
        self.groups.set_preview(policy_id, count)  # پیش‌نمایش تعداد مشمول (۷.۵)
        return True, policy_id

    def apply_policy(self, policy_id: int, applied_by: int) -> dict:
        """اجرای سیاست با ثبت نتیجه؛ برای زمان‌بندی‌شده‌ها در_startup هم صدا زده می‌شود."""
        policy = self.groups.policy(policy_id)
        if not policy or policy["status"] not in ("previewed", "pending"):
            return {"ok": False, "error": "سیاست قابل اجرا نیست."}
        params = json.loads(policy["params"])
        members = self.groups.member_ids(policy["group_id"])
        group = self.groups.get(policy["group_id"])
        result = {"total": len(members), "affected": 0, "action": policy["action"]}
        try:
            if policy["action"] == "gift_subscription":
                plan_id = int(params["plan_id"])
                version = self.plans.current_version(plan_id)
                cfg = json.loads(version["config"])
                days = int(params.get("days") or 0)
                duration = (days * 86400) if days else (
                    cfg["duration_value"] * {"minute": 60, "hour": 3600, "day": 86400,
                                             "week": 604800, "month": 2592000}[cfg["duration_unit"]]
                )
                for uid in members:
                    self.subs.create(uid, plan_id, version["id"], duration,
                                     "campaign" if params.get("campaign") else "gift",
                                     f"policy:{policy_id}")
                    result["affected"] += 1
            elif policy["action"] == "extend_active":
                seconds = int(params.get("seconds", 0))
                for uid in members:
                    active = self.subs.active_of(uid)
                    if active:
                        self.subs._insert_extension(active["id"], NOW(), seconds)
                        result["affected"] += 1
            # no_change: فقط شمارش
            self.groups.mark_applied(policy_id, applied_by, result)
            result["ok"] = True
            result["group"] = group["name"] if group else "-"
            return result
        except Exception as e:  # خطای اجرای سیاست ثبت می‌شود (بخش ۷.۷)
            self.groups.mark_failed(policy_id, str(e))
            return {"ok": False, "error": str(e)}

    def run_due_policies(self) -> list[dict]:
        """اجرای سیاست‌های زمان‌بندی‌شده سررسیدشده (بخش ۷.۶)."""
        results = []
        for p in self.groups.due_policies():
            results.append({"policy_id": p["id"], **self.apply_policy(p["id"], 0)})
        return results

    # ---------- جست‌وجوی کاربران قدیمی/جدید (بخش ۷.۱) ----------
    def split_by_boundary(self, boundary: int) -> dict:
        old = self.groups._users_in_window(None, boundary)
        new = self.groups._users_in_window(boundary, None)
        return {"old": len(old), "new": len(new), "old_ids": old, "new_ids": new}
