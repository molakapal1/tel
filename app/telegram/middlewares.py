"""میدل‌ورهای تلگرام — ثبت‌نام خودکار و حالت تعمیرات (بخش ۶.۱ و ۱۸ سند)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from ..services import Services


class UserMiddleware(BaseMiddleware):
    """برای هر پیام: ثبت/به‌روزرسانی کاربر + اجرای حالت تعمیرات."""

    def __init__(self, services: Services):
        self.services = services

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None:
            # ثبت‌نام یکپارچه (بخش ۶.۱) — تاریخ ثبت‌نام اولیه حفظ می‌شود
            self.services.user_service.register(user.id, user.username, user.full_name)
            # حالت تعمیرات: فقط مدیران عبور می‌کنند (بخش ۱۸.۱ متن تعمیرات)
            if self.services.settings.is_maintenance:
                is_admin = self.services.permissions.context_of(user.id) is not None
                if not is_admin:
                    from aiogram.types import Message, CallbackQuery
                    text = self.services.settings.get("text.maintenance")
                    if isinstance(event, Message):
                        await event.reply(text)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(text, show_alert=True)
                    return None
        data["services"] = self.services
        return await handler(event, data)
