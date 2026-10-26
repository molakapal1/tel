"""زمان‌بندهای دوره‌ای سامانه (بخش ۷.۶، ۱۱.۲، ۱۱.۶ و ۱۳.۶ سند).

- اجرای شروع زمان‌بندی‌شده فروش + یادآوری مدیران (بخش ۱۱.۶)
- منقضی‌سازی اشتراک‌ها و سفارش‌ها
- اجرای سیاست‌های گروهی زمان‌بندی‌شده (بخش ۷.۶)
- هشدار انقضای نزدیک اشتراک برای کاربران (بخش ۱۸.۴)
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot

from .database.repositories import AdminsRepo, SubscriptionsRepo
from .services import Services
from .services.settings import SALES_PAID, SALES_SCHEDULED

log = logging.getLogger("schedulers")
NOW = lambda: int(time.time())  # noqa: E731


async def _notify_admins(bot: Bot, admins: AdminsRepo, text: str) -> None:
    for a in admins.list_admins():
        try:
            await bot.send_message(a["telegram_id"], text)
        except Exception as e:
            log.warning("اعلان به مدیر %s ناموفق: %s", a["telegram_id"], e)


async def sales_scheduler(bot: Bot, services: Services, interval: int = 60) -> None:
    """بررسی شروع فروش زمان‌بندی‌شده و ارسال هشدارها (بخش ۱۱)."""
    alerted_start = False
    alerted_near = False
    while True:
        try:
            mode = services.settings.get("sales.mode")
            if mode == SALES_SCHEDULED:
                start = services.settings.get("sales.scheduled_start")
                if start:
                    start = int(start)
                    now = NOW()
                    alert_before = int(services.settings.get("sales.alert_minutes_before", 60)) * 60
                    if now >= start:
                        services.settings.set("sales.mode", SALES_PAID)
                        services.settings.set("sales.selling_stopped", False)
                        await _notify_admins(
                            bot, services.admins_repo,
                            "💰 شروع زمان‌بندی‌شده فروش با موفقیت اجرا شد.")
                        alerted_start = alerted_near = False
                    elif not alerted_near and now >= start - alert_before:
                        await _notify_admins(
                            bot, services.admins_repo,
                            f"⏰ شروع فروش نزدیک است: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(start))}")
                        alerted_near = True
            else:
                alerted_start = alerted_near = False
        except Exception:
            log.exception("خطای زمان‌بند فروش")
        await asyncio.sleep(interval)


async def expiry_sweeper(services: Services, interval: int = 900) -> None:
    """منقضی‌سازی تنبل اشتراک‌ها و سفارش‌های باز (بخش ۱۳.۶)."""
    while True:
        try:
            subs = services.subs_repo.sweep_expired()
            orders = services.orders_repo.sweep_expired()
            if subs or orders:
                log.info("انقضا: %s اشتراک، %s سفارش", subs, orders)
        except Exception:
            log.exception("خطای پاک‌ساز انقضا")
        await asyncio.sleep(interval)


async def group_policy_scheduler(services: Services, interval: int = 60) -> None:
    """اجرای سیاست‌های گروهی زمان‌بندی‌شده (بخش ۷.۶).

    اگر ربات در زمان مقرر خاموش بوده باشد، پس از راه‌اندازی مجدد سیاست‌های
    سررسیدشده اجرا می‌شوند.
    """
    while True:
        try:
            results = services.group_service.run_due_policies()
            for r in results:
                log.info("اجرای سیاست #%s: %s", r.get("policy_id"), r)
        except Exception:
            log.exception("خطای زمان‌بند سیاست گروهی")
        await asyncio.sleep(interval)


async def expiry_notifier(bot: Bot, services: Services, interval: int = 3600) -> None:
    """یادآوری انقضای نزدیک اشتراک به کاربران (بخش ۱۸.۴)."""
    sent_key = "notify.expiry_last_run"
    while True:
        try:
            days = int(services.settings.get("notify.expiry_warn_days", 3))
            rows = services.db.query(
                "SELECT s.user_id, s.expires_at, p.title FROM subscriptions s "
                "JOIN plans p ON p.id=s.plan_id WHERE s.status='active' "
                "AND s.expires_at BETWEEN ? AND ?",
                (NOW(), NOW() + days * 86400),
            )
            for r in rows:
                try:
                    await bot.send_message(
                        r["user_id"],
                        f"⏳ اشتراک «{r['title']}» شما تا "
                        f"{(r['expires_at'] - NOW()) // 86400 + 1} روز آینده منقضی می‌شود.\n"
                        "برای تمدید: /plans")
                except Exception:
                    continue
                await asyncio.sleep(0.1)
            services.settings.set(sent_key, NOW())
        except Exception:
            log.exception("خطای یادآور انقضا")
        await asyncio.sleep(interval)


def start_all(bot: Bot, services: Services) -> list[asyncio.Task]:
    """راه‌اندازی همه زمان‌بندهای پس‌زمینه."""
    return [
        asyncio.create_task(sales_scheduler(bot, services)),
        asyncio.create_task(expiry_sweeper(services)),
        asyncio.create_task(group_policy_scheduler(services)),
        asyncio.create_task(expiry_notifier(bot, services)),
    ]
