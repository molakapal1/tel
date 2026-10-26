"""سرویس سفارش و پرداخت دستی (بخش ۱۳ سند)."""
from __future__ import annotations

from ..database.repositories import OrdersRepo, PaymentMethodsRepo, PlansRepo
from .plans import PlanService
from .settings import SettingsService


class OrderService:
    def __init__(self, orders: OrdersRepo, payments: PaymentMethodsRepo, plans: PlansRepo,
                 plan_service: PlanService, settings: SettingsService):
        self.orders = orders
        self.payments = payments
        self.plans = plans
        self.plan_service = plan_service
        self.settings = settings

    # ---------- ایجاد سفارش (۱۳.۱) ----------
    def create_order(self, user_id: int, plan_id: int, discount_percent: int = 0
                     ) -> tuple[bool, str]:
        if self.settings.sales_mode != "paid":
            return False, "در حالت فعلی سرویس، خرید پلن فعال نیست."
        plan = self.plans.get(plan_id)
        if not plan or plan["is_archived"]:
            return False, "پلن موجود نیست."
        method = self.payments.get_active()
        if not method:
            return False, "روش پرداخت فعالی تنظیم نشده است. با پشتیبانی تماس بگیر."
        # پلن باید در فهرست فروش باشد
        saleable = {p["id"]: p for p in self.plan_service.saleable_plans()}
        if plan_id not in saleable:
            return False, "این پلن در حال حاضر قابل خرید نیست."
        plan_row = saleable[plan_id]
        amount = self.plan_service.effective_price(plan_row, discount_percent)
        order_id = self.orders.create(
            user_id, plan_row, amount, plan_row["config"].duration_seconds, method
        )
        return True, order_id

    def payment_text(self, order) -> str:
        """متن پیام پرداخت با قالب قابل تنظیم از پنل (۱۳.۴)."""
        import json
        snap = json.loads(order["payment_snapshot"])
        info = snap["card_number"] or ""
        if snap.get("holder_name"):
            info += f"\nبه نام: {snap['holder_name']}"
        if snap.get("bank_name"):
            info += f"\nبانک: {snap['bank_name']}"
        if snap.get("instructions"):
            info += f"\n{snap['instructions']}"
        plan = self.plans.get(order["plan_id"])
        import time
        days = max(1, order["duration_seconds"] // 86400)
        return self.settings.get("text.payment").format(
            order_id=order["id"], plan_title=plan["title"] if plan else "-",
            amount=order["amount"], duration=f"{days} روز", payment_info=info,
        )

    # ---------- چرخه وضعیت (۱۳.۶) ----------
    def announce_payment(self, order_id: str, user_id: int) -> tuple[bool, str]:
        order = self.orders.get(order_id)
        if not order or order["user_id"] != user_id:
            return False, "سفارش پیدا نشد."
        if self.orders.announce_payment(order_id):
            return True, "اعلام پرداخت ثبت شد ✅ لطفاً رسید را بفرست تا بررسی شود."
        return False, "امکان اعلام پرداخت برای این سفارش نیست."

    def attach_receipt(self, order_id: str, user_id: int, file_id: str) -> tuple[bool, str]:
        order = self.orders.get(order_id)
        if not order or order["user_id"] != user_id:
            return False, "سفارش پیدا نشد."
        if self.orders.attach_receipt(order_id, file_id):
            return True, "رسید دریافت شد 🧾 در انتظار بررسی مدیر است."
        return False, "این سفارش در وضعیت قابل قبولی برای دریافت رسید نیست."

    def cancel(self, order_id: str, user_id: int) -> tuple[bool, str]:
        order = self.orders.get(order_id)
        if not order or order["user_id"] != user_id:
            return False, "سفارش پیدا نشد."
        if self.orders.cancel_by_user(order_id, user_id):
            return True, "سفارش لغو شد."
        return False, "لغو این سفارش ممکن نیست."

    # ---------- عملیات مدیر (۱۳.۷ و ۱۳.۸) ----------
    def approve(self, order_id: str, by: int) -> tuple[bool, str]:
        ok, sub_id = self.orders.confirm(order_id, by)
        if ok:
            return True, f"پرداخت تأیید شد ✅ اشتراک فعال/تمدید شد (#{sub_id})."
        order = self.orders.get(order_id)
        if order and order["status"] == "confirmed":
            return False, "این سفارش قبلاً تأیید شده است (جلوگیری از تأیید تکراری)."
        return False, "این سفارش در وضعیت قابل تأیید نیست."

    def reject(self, order_id: str, by: int, reason: str) -> tuple[bool, str]:
        if self.orders.reject(order_id, by, reason):
            return True, "سفارش رد شد و دلیل آن ثبت گردید."
        return False, "رد این سفارش ممکن نیست (وضعیت نهایی شده)."

    def sweep(self) -> int:
        return self.orders.sweep_expired()
