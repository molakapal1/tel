"""اعتبارسنجی واقعی راه‌اندازی (مرحله ۷ سند) — اجرای برنامه با توکن ساختگی.

هدف: اطمینان از سیم‌کشی کامل (config → db → services → engine → inbox →
dispatcher) پیش از رسیدن به polling تلگرام. خطای 401 توکن ساختگی، نشانه
رسیدن سالم به آخرین مرحله است.
"""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:AAFakeTokenForWiringValidationOnly"
os.environ["INSTAGRAM_USERNAME"] = "fake_ig_user"
os.environ["INSTAGRAM_PASSWORD"] = "fake_ig_pass"
os.environ["ADMIN_IDS"] = "111"
os.environ["IG_POLL_MIN"] = "30"
os.environ["IG_POLL_MAX"] = "60"

tmp = Path(tempfile.mkdtemp())
os.environ["STORAGE_DIR"] = str(tmp / "storage")
os.environ["DATABASE_PATH"] = "storage/bot.db"

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.logging_config import setup_logging
from app.database import Database
from app.services import build_services, build_engine
from app.telegram.delivery import TelegramSender
from app.instagram.client import InstagramClient
from app.main import build_dispatcher

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


async def main():
    cfg = get_settings()
    cfg.ensure_dirs()
    setup_logging(cfg.logs_dir, "INFO")
    log = logging.getLogger("wiring")
    errors = cfg.validate_runtime()
    log.info("خطاهای تنظیمات (انتظاری، چون ساختگی است): %s", errors)

    db = Database(cfg.db_file)
    services = build_services(db, cfg.admin_ids)
    log.info("✅ پایگاه داده + سرویس‌ها")

    bot = Bot(token=cfg.telegram_bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sender = TelegramSender(bot, use_local_api=False)

    ig = InstagramClient(cfg.instagram_username, cfg.instagram_password, cfg.session_file)
    from app.instagram.content import InstagramContentDownloader
    downloader = InstagramContentDownloader(ig, proxy=None)

    async def notify(uid, text):
        pass

    engine = build_engine(services, downloader, sender, notify, cfg.temp_dir)
    log.info("✅ موتور دانلود")

    from app.instagram.inbox import InstagramInbox
    inbox = InstagramInbox(ig, services.links_repo, engine,
                           loop_holder=asyncio.get_running_loop())
    services.inbox_health = inbox.health
    log.info("✅ پایشگر دایرکت")

    dp = build_dispatcher(services)
    log.info("✅ دیسپچر: %s روتر", len(dp.sub_routers))

    await engine.start()
    log.info("✅ موتور راه‌اندازی شد (زمان‌بند + پاک‌ساز)")

    # بررسی اتصال تلگرام — با توکن ساختگی باید 401 بگیریم (نشانه سلامت مسیر)
    try:
        me = await bot.get_me()
        log.info("✅ تلگرام: @%s", me.username)
        telegram_ok = True
    except Exception as e:
        log.warning("تلگرام با توکن ساختگی: %s (طبیعی است)", type(e).__name__)
        telegram_ok = False

    await engine.stop()
    db.close()
    log.info("=== WIRING VALIDATION %s ===", "PASSED (جز اتصال واقعی)" if not telegram_ok else "PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
