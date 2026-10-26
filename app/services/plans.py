"""سرویس پلن‌ها و نسخه‌بندی (بخش ۸ و ۹ سند).

PlanConfig قرارداد تنظیمات هر نسخه پلن است و به‌صورت JSON در جدول
plan_versions ذخیره می‌شود؛ تمام مقادیر مستقل از یکدیگر قابل تنظیم‌اند.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from ..database.repositories import PlansRepo, SubscriptionsRepo

NOW = lambda: int(time.time())  # noqa: E731

DURATION_UNITS = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000}
UNIT_LABELS = {"minute": "دقیقه", "hour": "ساعت", "day": "روز", "week": "هفته", "month": "ماه"}


@dataclass
class PlanConfig:
    """تنظیمات کامل یک نسخه پلن (بخش ۸.۲)."""
    price: int = 0                       # تومان
    duration_value: int = 30             # مدت اعتبار
    duration_unit: str = "day"           # واحد مدت
    start_on_activation: bool = True     # شروع اعتبار از فعال‌سازی (یا خرید)
    concurrent_downloads: int = 1        # دانلود هم‌زمان
    wait_seconds: int = 60               # زمان انتظار بین دانلودها
    queue_limit: int = 5                 # حداکثر درخواست در صف
    hourly_quota: int | None = None      # سهمیه ساعتی
    daily_quota: int | None = None       # سهمیه روزانه
    total_quota: int | None = None       # سهمیه کل دوره
    max_file_mb: int = 50                # حداکثر حجم فایل (مگابایت)
    priority: int = 0                    # اولویت در صف
    features: list[str] = field(default_factory=list)  # قابلیت‌های مجاز
    discount_percent: int = 0            # تخفیف درصدی پایه پلن
    is_trial: bool = False               # پلن آزمایشی
    trial_once_per_user: bool = True     # یک‌بارمصرف برای هر کاربر
    is_sellable: bool = True             # وضعیت فروش
    sale_start: int | None = None        # بازه فروش
    sale_end: int | None = None

    # ---------- اعتبارسنجی ----------
    def validate(self) -> list[str]:
        errors = []
        if self.price < 0:
            errors.append("قیمت نمی‌تواند منفی باشد.")
        if self.duration_value <= 0:
            errors.append("مدت اعتبار باید مثبت باشد.")
        if self.duration_unit not in DURATION_UNITS:
            errors.append("واحد مدت نامعتبر است.")
        if self.concurrent_downloads < 1:
            errors.append("حداقل دانلود هم‌زمان ۱ است.")
        if self.wait_seconds < 0:
            errors.append("زمان انتظار نمی‌تواند منفی باشد. (صفر = بدون انتظار اجباری)")
        if self.queue_limit < 1:
            errors.append("حداقل ظرفیت صف ۱ است.")
        for q in (self.hourly_quota, self.daily_quota, self.total_quota):
            if q is not None and q < 1:
                errors.append("سهمیه‌ها در صورت تعیین باید حداقل ۱ باشند.")
        if self.max_file_mb < 1:
            errors.append("حداقل حجم فایل ۱ مگابایت است.")
        if not (0 <= self.discount_percent <= 100):
            errors.append("درصد تخفیف بین ۰ تا ۱۰۰ است.")
        return errors

    @property
    def duration_seconds(self) -> int:
        return self.duration_value * DURATION_UNITS[self.duration_unit]

    @property
    def duration_label(self) -> str:
        return f"{self.duration_value} {UNIT_LABELS[self.duration_unit]}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PlanConfig":
        clean = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**clean)


class PlanService:
    def __init__(self, plans: PlansRepo, subs: SubscriptionsRepo):
        self.plans = plans
        self.subs = subs

    # ---------- خواندن ----------
    def config_of_version(self, version_row) -> PlanConfig:
        return PlanConfig.from_dict(json.loads(version_row["config"]))

    def config_of_plan(self, plan_id: int) -> PlanConfig | None:
        v = self.plans.current_version(plan_id)
        return self.config_of_version(v) if v else None

    def saleable_plans(self) -> list[dict]:
        """پلن‌های قابل نمایش به کاربر، همراه با config لحظه‌ای."""
        out = []
        for row in self.plans.saleable():
            cfg = PlanConfig.from_dict(json.loads(row["config"]))
            out.append({
                "id": row["id"], "title": row["title"], "name": row["name"],
                "description": row["description"], "version_id": row["version_id"],
                "version": row["version"], "config": cfg,
            })
        return out

    # ---------- عملیات مدیر (بخش ۸.۱ و ۹) ----------
    def create_plan(self, name: str, title: str, description: str, config: PlanConfig,
                    created_by: int) -> tuple[bool, str | int]:
        errors = config.validate()
        if errors:
            return False, "\n".join(errors)
        if self.plans.get_by_name(name):
            return False, "پلنی با این نام داخلی وجود دارد."
        plan_id = self.plans.create(name, title, description, config.to_dict(), created_by)
        return True, plan_id

    def draft_new_version(self, plan_id: int, config: PlanConfig, created_by: int,
                          changelog: str) -> tuple[bool, str | int]:
        """ویرایش پلن = ساخت نسخه جدید پیش‌نویس؛ نسخه منتشرشده فعلی دست‌نخورده می‌ماند."""
        errors = config.validate()
        if errors:
            return False, "\n".join(errors)
        plan = self.plans.get(plan_id)
        if not plan:
            return False, "پلن پیدا نشد."
        version_id = self.plans.draft_new_version(plan_id, config.to_dict(), created_by, changelog)
        return True, version_id

    def change_preview(self, plan_id: int, new_config: PlanConfig) -> dict:
        """پیش‌نمایش تغییرات حساس: مقادیر قبلی/جدید و تعداد مشمولان (بخش ۹.۴)."""
        current = self.plans.current_version(plan_id)
        old_cfg = self.config_of_version(current) if current else None
        diff = {}
        if old_cfg:
            for key, new_val in new_config.to_dict().items():
                old_val = old_cfg.to_dict().get(key)
                if old_val != new_val:
                    diff[key] = {"old": old_val, "new": new_val}
        return {
            "diff": diff,
            "affected_subscribers": self.plans.affected_subscribers(plan_id),
        }

    def publish(self, version_id: int, scope: str, by: int) -> tuple[bool, str]:
        """انتشار نسخه با دامنه (بخش ۹.۲): future | current | both."""
        if scope not in ("future", "current", "both"):
            return False, "دامنه انتشار نامعتبر است."
        try:
            result = self.plans.publish_version(version_id, scope)
        except ValueError as e:
            return False, str(e)
        return True, (f"نسخه {result['version']} پلن منتشر شد "
                      f"(دامنه: { {'future': 'خریداران آینده', 'current': 'مشترکان فعلی', 'both': 'هر دو گروه'}[scope] }).")

    def effective_price(self, plan: dict, discount_percent: int = 0) -> int:
        cfg: PlanConfig = plan["config"]
        pct = max(discount_percent, cfg.discount_percent)
        return int(cfg.price * (100 - pct) / 100)

    def gift(self, user_id: int, plan_id: int, duration_seconds: int | None = None,
             note: str = "gift") -> int:
        """هدیه اشتراک (بخش ۶.۲) — با تمدید در صورت اشتراک فعال."""
        v = self.plans.current_version(plan_id)
        cfg = self.config_of_version(v)
        duration = duration_seconds or cfg.duration_seconds
        return self.subs.create(user_id, plan_id, v["id"], duration, "gift", note)
