"""سرویس اشتراک‌ها، آزمایش و اتصال کدها (بخش ۱۰، ۱۳.۹ و ۱۴ سند)."""
from __future__ import annotations

import json
import time

from ..database.repositories import (
    CampaignsRepo, PlansRepo, PromoCodesRepo, SubscriptionsRepo, TrialRepo,
)
from .plans import PlanService
from .settings import SettingsService

NOW = lambda: int(time.time())  # noqa: E731


class SubscriptionService:
    def __init__(self, subs: SubscriptionsRepo, plans: PlansRepo, plan_service: PlanService,
                 trials: TrialRepo, campaigns: CampaignsRepo, codes: PromoCodesRepo,
                 settings: SettingsService):
        self.subs = subs
        self.plans = plans
        self.plan_service = plan_service
        self.trials = trials
        self.campaigns = campaigns
        self.codes = codes
        self.settings = settings

    # ---------- فعال‌سازی با کد ----------
    def redeem_code(self, code: str, user_id: int) -> tuple[bool, str]:
        ok, msg, _ = self.codes.redeem(code.strip().upper(), user_id)
        return ok, msg

    # ---------- آزمایش (بخش ۱۰) ----------
    def grant_trial(self, user_id: int, plan_id: int, source: str = "admin") -> tuple[bool, str]:
        """اعطای پلن آزمایشی با کنترل سوءاستفاده (بخش ۱۰.۴)."""
        plan = self.plans.get(plan_id)
        if not plan:
            return False, "پلن پیدا نشد."
        version = self.plans.current_version(plan_id)
        cfg = self.plan_service.config_of_version(version)
        if not cfg.is_trial:
            return False, "این پلن آزمایشی نیست."

        # شرط کمپین (بخش ۱۰.۵): اگر کمپین فعال برای پلن هست از سقف آن پیروی کن
        campaign = self.campaigns.active_trial_for(plan_id)
        if source == "campaign":
            if not campaign:
                return False, "کمپین آزمایشی فعالی برای این پلن وجود ندارد."

        # جلوگیری از دریافت مجدد
        scope = self.settings.get("trial.limit_scope", "per_plan")
        if cfg.trial_once_per_user:
            if scope == "global" and self.trials.granted_count(user_id) > 0:
                return False, "شما قبلاً دوره آزمایشی دریافت کرده‌اید."
            if self.trials.granted_count(user_id, plan_id) > 0:
                return False, "شما قبلاً این دوره آزمایشی را دریافت کرده‌اید."

        self.trials.grant(user_id, plan_id, source)
        sub_id = self.subs.create(user_id, plan_id, version["id"], cfg.duration_seconds,
                                  "trial", f"{source}:plan{plan_id}")
        if campaign and source == "campaign":
            self.campaigns.increment_use(campaign["id"])
        return True, f"دوره آزمایشی «{plan['title']}» فعال شد."

    # ---------- هدیه/تمدید مدیریتی (بخش ۶.۲) ----------
    def gift_days(self, user_id: int, plan_id: int, days: int, by_admin: int) -> int:
        return self.subs.create(user_id, plan_id,
                                self.plans.current_version(plan_id)["id"],
                                days * 86400, "gift", f"admin:{by_admin}")

    # ---------- پاک‌سازی دوره‌ای ----------
    def sweep(self) -> int:
        return self.subs.sweep_expired()

    def days_left(self, user_id: int) -> int | None:
        sub = self.subs.active_of(user_id)
        if not sub:
            return None
        return max(0, (sub["expires_at"] - NOW()) // 86400)
