"""صفحه‌کلیدهای کاربر (فارسی و راست‌چین — بخش ۱۶.۱ سند)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.types import KeyboardButton

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 وضعیت من"), KeyboardButton(text="💎 پلن‌ها و خرید")],
        [KeyboardButton(text="🔗 اتصال اینستاگرام"), KeyboardButton(text="🧾 سفارش‌های من")],
        [KeyboardButton(text="🆘 راهنما")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def plans_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        rows.append([InlineKeyboardButton(
            text=f"{p['title']} — {p['config'].price:,} تومان",
            callback_data=f"buy:{p['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ پرداخت کردم", callback_data=f"paydone:{order_id}"),
        InlineKeyboardButton(text="❌ لغو سفارش", callback_data=f"paycancel:{order_id}"),
    ]])


def trial_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 دریافت دوره آزمایشی", callback_data=f"trial:{plan_id}"),
    ]])
