import asyncio
import glob
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# نمایش درست متن فارسی در cmd
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ====================== تنظیمات (این بخش را پر کن) ======================
TOKEN = "PUT_YOUR_TOKEN_HERE"            # توکن ربات تلگرام
BOT_USERNAME = "your_bot_username"       # یوزرنیم ربات تلگرام بدون @
IG_USERNAME = "your_instagram_username"  # اکانت اینستاگرام مخصوص ربات
IG_PASSWORD = "your_instagram_password"  # رمز همان اکانت

# پروکسی محلی v2ray. اگر VPN حالت TUN دارد و روشن است: PROXY = ""
PROXY = "http://127.0.0.1:3067"
# ========================================================================

CODE_MINUTES = 20          # اعتبار کد
MAX_PER_HOUR = 15          # حداکثر دانلود هر کاربر در ساعت
POLL_MIN, POLL_MAX = 30, 60  # فاصله چک‌کردن دایرکت (ثانیه، تصادفی)
MAX_SIZE = 49 * 1024 * 1024  # حد مجاز تلگرام برای ربات‌ها
DB_FILE = "bot.db"
SESSION_FILE = "ig_session.json"

# لینک پست/ریلز (با یا بدون یوزرنیم در مسیر)
LINK_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([\w-]+)",
    re.IGNORECASE,
)

# پروکسی را برای همه ابزارها (yt-dlp، instaloader و ...) فعال می‌کند
if PROXY:
    for _k in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        os.environ[_k] = PROXY
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    os.environ["no_proxy"] = "localhost,127.0.0.1"

cl = None
TG_LOOP = None
ig_lock = threading.Lock()
db_lock = threading.Lock()
first_scan_done = False
recent = defaultdict(deque)


# ============================ دیتابیس ============================
def query(sql, args=(), fetch=False):
    with db_lock:
        con = sqlite3.connect(DB_FILE)
        try:
            cur = con.execute(sql, args)
            rows = cur.fetchall() if fetch else None
            con.commit()
            return rows
        finally:
            con.close()


def init_db():
    query(
        "CREATE TABLE IF NOT EXISTS users ("
        "telegram_id INTEGER PRIMARY KEY, "
        "ig_username TEXT UNIQUE, "
        "method INTEGER DEFAULT 1)"
    )
    query(
        "CREATE TABLE IF NOT EXISTS codes ("
        "code TEXT PRIMARY KEY, ig_username TEXT, "
        "expires_at INTEGER, used INTEGER DEFAULT 0)"
    )
    query(
        "CREATE TABLE IF NOT EXISTS seen ("
        "thread_id TEXT PRIMARY KEY, last_msg_id TEXT)"
    )


def get_or_create_code(username):
    now = int(time.time())
    query("DELETE FROM codes WHERE expires_at < ?", (now,))
    row = query(
        "SELECT code FROM codes WHERE ig_username=? AND used=0 AND expires_at>?",
        (username, now),
        True,
    )
    if row:
        return row[0][0]
    while True:
        code = str(secrets.randbelow(900000) + 100000)
        exists = query("SELECT 1 FROM codes WHERE code=?", (code,), True)
        if not exists:
            break
    query(
        "INSERT INTO codes (code, ig_username, expires_at) VALUES (?, ?, ?)",
        (code, username, now + CODE_MINUTES * 60),
    )
    return code


# ============================ اینستاگرام ============================
def ig_login():
    client = Client()
    client.delay_range = [2, 6]  # تأخیر تصادفی بین درخواست‌ها
    if PROXY:
        client.set_proxy(PROXY)
    if os.path.exists(SESSION_FILE):
        client.load_settings(SESSION_FILE)
        if PROXY:
            client.set_proxy(PROXY)
    try:
        client.login(IG_USERNAME, IG_PASSWORD)
    except TwoFactorRequired:
        code = input("Enter Instagram 2FA code: ").strip()
        client.login(IG_USERNAME, IG_PASSWORD, verification_code=code)
    client.dump_settings(SESSION_FILE)
    return client


def send_dm(thread, text):
    with ig_lock:
        cl.direct_answer(thread.id, text)


def dump_message(m):
    """کل محتوای پیام را به متن تبدیل می‌کند (برای پیدا کردن لینک)."""
    try:
        data = m.model_dump(mode="json")
    except Exception:
        try:
            data = m.dict()
        except Exception:
            data = str(m)
    try:
        return json.dumps(data, default=str, ensure_ascii=False)
    except Exception:
        return str(data)


def extract_post(m):
    """پست یا ریلز داخل پیام دایرکت را پیدا می‌کند. خروجی: (url, shortcode)"""
    # ۱) پست یا ریلزی که با دکمه Share فرستاده شده
    for field, kind in (("media_share", "p"), ("clip", "reel")):
        obj = getattr(m, field, None)
        code = getattr(obj, "code", None) if obj is not None else None
        if code:
            return f"https://www.instagram.com/{kind}/{code}/", code

    # ۲) لینک داخل متن
    if getattr(m, "text", None):
        mt = LINK_RE.search(m.text)
        if mt:
            return mt.group(0), mt.group(1)

    # ۳) جستجو در کل محتوای پیام (xma، link و ...)
    mt = LINK_RE.search(dump_message(m))
    if mt:
        return mt.group(0), mt.group(1)
    return None


def handle_dm(thread, m, username):
    row = query(
        "SELECT telegram_id, method FROM users WHERE ig_username=?",
        (username,),
        True,
    )

    # کاربر هنوز وصل نیست: کد بده
    if not row:
        code = get_or_create_code(username)
        send_dm(
            thread,
            f"کد شما: {code}\n"
            f"تا {CODE_MINUTES} دقیقه فرصت دارید این کد را برای ربات تلگرام "
            f"@{BOT_USERNAME} بفرستید.",
        )
        return

    # کاربر وصل است: دنبال پست یا لینک بگرد
    tg_id, method = row[0]
    post = extract_post(m)
    if not post:
        print("No post found in message. Dump:", dump_message(m)[:800])
        if getattr(m, "text", None):
            send_dm(
                thread,
                "حساب شما وصل است ✅\n"
                "پست یا ریلز را برای من بفرست (Share) یا لینکش را بفرست "
                "تا در تلگرام برایت دانلود کنم.",
            )
        return

    url, shortcode = post
    print(f"Post found for @{username}: {url}")
    if TG_LOOP is not None:
        asyncio.run_coroutine_threadsafe(
            deliver(tg_id, url, shortcode, method), TG_LOOP
        )


def check_inbox():
    global first_scan_done
    items = []
    with ig_lock:
        for t in cl.direct_threads(amount=10, thread_message_limit=10):
            items.append((t, False))
        try:
            req = getattr(cl, "direct_requests", None) or cl.direct_pending_inbox
            for t in req(amount=10):
                items.append((t, True))
        except Exception as e:
            print("Pending inbox error:", e)

    me = str(cl.user_id)
    for t, pending in items:
        try:
            if not t.messages or len(t.users) != 1:
                continue

            row = query(
                "SELECT last_msg_id FROM seen WHERE thread_id=?",
                (str(t.id),),
                True,
            )
            last_seen = row[0][0] if row else None

            new = []
            for m in t.messages[:10]:
                if str(m.id) == last_seen:
                    break
                if str(m.user_id) != me:
                    new.append(m)

            if new and first_scan_done:
                username = t.users[0].username.lower()
                if pending:
                    try:
                        with ig_lock:
                            cl.direct_request_approve(t.id)
                    except Exception as e:
                        print("Approve error:", e)
                for m in reversed(new):  # قدیمی‌ترین اول
                    try:
                        print(f"New DM from @{username}, type={m.item_type}")
                        handle_dm(t, m, username)
                    except Exception as e:
                        print("DM handling error:", e)

            query(
                "INSERT OR REPLACE INTO seen (thread_id, last_msg_id) VALUES (?, ?)",
                (str(t.id), str(t.messages[0].id)),
            )
        except Exception as e:
            print("Thread error:", e)
    first_scan_done = True


def ig_loop():
    while True:
        try:
            check_inbox()
        except Exception as e:
            print("Instagram error:", e)
            time.sleep(300)
        time.sleep(random.randint(POLL_MIN, POLL_MAX))


# ============================ روش‌های دانلود ============================
def run_cmd(args, timeout=180):
    try:
        subprocess.run(args, capture_output=True, timeout=timeout)
    except Exception:
        pass


def method_ytdlp(url, shortcode, folder):
    args = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "-f", "bv*[vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/b",
        "--merge-output-format", "mp4",
        "-o", os.path.join(folder, "%(id)s.%(ext)s"),
    ]
    if PROXY:
        args += ["--proxy", PROXY]
    args.append(url)
    run_cmd(args)


def method_instaloader(url, shortcode, folder):
    run_cmd([
        sys.executable, "-m", "instaloader",
        "--dirname-pattern=" + folder,
        "--no-metadata-json", "--no-captions", "--no-compress-json",
        "--", "-" + shortcode,
    ])


def method_instagrapi(url, shortcode, folder):
    with ig_lock:
        pk = cl.media_pk_from_url(url)
        info = cl.media_info(pk)
        path = Path(folder)
        if info.media_type == 2:
            cl.video_download(pk, path)
        elif info.media_type == 1:
            cl.photo_download(pk, path)
        elif info.media_type == 8:
            cl.album_download(pk, path)


METHODS = {
    1: ("yt-dlp", method_ytdlp),
    2: ("instaloader", method_instaloader),
    3: ("instagrapi (با اکانت ربات)", method_instagrapi),
}


def find_media(folder):
    files = []
    for ext in ("mp4", "jpg", "jpeg", "png", "webp"):
        files += glob.glob(os.path.join(folder, "*." + ext))
    return sorted(files)


def download(url, shortcode, preferred):
    order = [preferred] + [k for k in METHODS if k != preferred]
    for key in order:
        folder = tempfile.mkdtemp()
        try:
            METHODS[key][1](url, shortcode, folder)
        except Exception as e:
            print(f"Method {key} failed:", e)
        files = find_media(folder)
        if files:
            return folder, files
        shutil.rmtree(folder, ignore_errors=True)
    return None, []


# ============================ ارسال به تلگرام ============================
def video_info(path):
    width = height = duration = None
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration",
                "-of", "csv=p=0", path,
            ],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        parts = out.split(",")
        try:
            width = int(parts[0])
            height = int(parts[1])
        except Exception:
            pass
        try:
            duration = int(float(parts[2]))
        except Exception:
            pass
    except Exception:
        pass
    return width, height, duration


def compress(path):
    out = path[:-4] + "_small.mp4"
    run_cmd([
        "ffmpeg", "-y", "-i", path,
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-crf", "30", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", out,
    ], timeout=600)
    if os.path.exists(out) and os.path.getsize(out) <= MAX_SIZE:
        return out
    return None


async def send_video(bot, chat_id, path):
    if os.path.getsize(path) > MAX_SIZE:
        await bot.send_message(chat_id, "ویدیو بزرگ است، در حال فشرده‌سازی...")
        small = await asyncio.to_thread(compress, path)
        if not small:
            await bot.send_message(
                chat_id,
                "ویدیو حتی بعد از فشرده‌سازی برای تلگرام زیادی بزرگ است.",
            )
            return
        path = small

    width, height, duration = await asyncio.to_thread(video_info, path)
    try:
        with open(path, "rb") as fh:
            await bot.send_video(
                chat_id=chat_id, video=fh,
                width=width, height=height, duration=duration,
                supports_streaming=True,
                read_timeout=600, write_timeout=600, connect_timeout=60,
            )
    except Exception:
        try:
            with open(path, "rb") as fh:
                await bot.send_document(
                    chat_id=chat_id, document=fh,
                    read_timeout=600, write_timeout=600, connect_timeout=60,
                )
        except Exception:
            await bot.send_message(chat_id, "ارسال ویدیو خطا داد.")


async def send_photo(bot, chat_id, path):
    try:
        with open(path, "rb") as fh:
            await bot.send_photo(
                chat_id=chat_id, photo=fh,
                read_timeout=300, write_timeout=300,
            )
    except Exception:
        await bot.send_message(chat_id, "ارسال عکس خطا داد.")


def allowed(tg_id):
    now = time.time()
    q = recent[tg_id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= MAX_PER_HOUR:
        return False
    q.append(now)
    return True


async def process_download(bot, chat_id, url, shortcode, method):
    """دانلود و ارسال به تلگرام (هم برای لینک تلگرام و هم برای دایرکت)."""
    if not allowed(chat_id):
        await bot.send_message(
            chat_id, "تعداد دانلودهای این ساعت تمام شد. کمی بعد دوباره امتحان کن."
        )
        return

    await bot.send_message(chat_id, "در حال دانلود... کمی صبر کن.")
    folder, files = await asyncio.to_thread(download, url, shortcode, method)
    if not files:
        await bot.send_message(
            chat_id,
            "دانلود نشد. ممکن است پیج خصوصی باشد یا لینک مشکل داشته باشد.",
        )
        return

    try:
        for f in files:
            if f.lower().endswith(".mp4"):
                await send_video(bot, chat_id, f)
            else:
                await send_photo(bot, chat_id, f)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


async def deliver(tg_id, url, shortcode, method):
    """وقتی پست از طریق دایرکت اینستاگرام رسید، برای تلگرام کاربر می‌فرستد."""
    try:
        bot = TG_APP.bot
        await bot.send_message(tg_id, "📩 پست از دایرکت اینستاگرام رسید.")
        await process_download(bot, tg_id, url, shortcode, method)
    except Exception as e:
        print("Deliver error:", e)


# ============================ دستورهای تلگرام ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام!\n"
        f"برای اتصال حساب: از اینستاگرام خودت به پیج @{IG_USERNAME} در دایرکت "
        "یک پیام (مثلاً سلام) بفرست. یک کد ۶ رقمی می‌گیری. "
        f"آن را ظرف {CODE_MINUTES} دقیقه همین‌جا برای من بفرست.\n\n"
        "بعد از اتصال، می‌توانی:\n"
        "• لینک پست یا ریلز را همین‌جا بفرستی، یا\n"
        "• پست را در اینستاگرام برای همان پیج Share کنی (یا لینکش را بفرستی) "
        "تا اینجا برایت بیاید.\n\n"
        "دستورها:\n"
        "/method - انتخاب روش دانلود\n"
        "/unlink - قطع اتصال اکانت اینستاگرام"
    )


async def unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query("DELETE FROM users WHERE telegram_id=?", (update.effective_user.id,))
    await update.message.reply_text("اتصال حساب قطع شد.")


async def method_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user.id
    row = query("SELECT method FROM users WHERE telegram_id=?", (tg,), True)
    if not row:
        await update.message.reply_text("اول باید حسابت را وصل کنی. /start")
        return
    args = context.args
    if args and args[0] in ("1", "2", "3"):
        query("UPDATE users SET method=? WHERE telegram_id=?", (int(args[0]), tg))
        await update.message.reply_text(
            f"روش پیش‌فرض شد: {METHODS[int(args[0])][0]}"
        )
        return
    lines = ["روش‌های دانلود (برای تغییر مثلاً بنویس /method 2):"]
    for k, (name, _) in METHODS.items():
        mark = " ✅" if k == row[0][0] else ""
        lines.append(f"{k}. {name}{mark}")
    await update.message.reply_text("\n".join(lines))


async def handle_code(update: Update, code: str):
    tg = update.effective_user.id
    now = int(time.time())

    mine = query(
        "SELECT ig_username FROM users WHERE telegram_id=?", (tg,), True
    )
    if mine:
        await update.message.reply_text(
            f"حساب تلگرامت قبلاً به @{mine[0][0]} وصل است. "
            "برای تغییر اول /unlink بزن."
        )
        return

    row = query(
        "SELECT ig_username FROM codes WHERE code=? AND used=0 AND expires_at>?",
        (code, now),
        True,
    )
    if not row:
        await update.message.reply_text("کد اشتباه است یا منقضی شده.")
        return

    ig = row[0][0]
    taken = query("SELECT 1 FROM users WHERE ig_username=?", (ig,), True)
    if taken:
        await update.message.reply_text(
            "این اکانت اینستاگرام قبلاً به تلگرام دیگری وصل شده است."
        )
        return

    query("INSERT INTO users (telegram_id, ig_username) VALUES (?, ?)", (tg, ig))
    query("UPDATE codes SET used=1 WHERE code=?", (code,))
    await update.message.reply_text(
        f"✅ حسابت به @{ig} وصل شد.\n"
        "حالا لینک پست یا ریلز را همین‌جا بفرست، یا پست را در اینستاگرام "
        "برای پیج ربات Share کن."
    )


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if re.fullmatch(r"\d{6}", text):
        await handle_code(update, text)
        return

    match = LINK_RE.search(text)
    if not match:
        await update.message.reply_text("لینک پست یا ریلز اینستاگرام را بفرست.")
        return

    tg = update.effective_user.id
    row = query("SELECT method FROM users WHERE telegram_id=?", (tg,), True)
    if not row:
        await update.message.reply_text(
            "اول باید حسابت را وصل کنی. /start را بزن."
        )
        return

    await process_download(
        context.bot, update.effective_chat.id,
        match.group(0), match.group(1), row[0][0],
    )


TG_APP = None


async def post_init(app):
    global TG_LOOP, TG_APP
    TG_APP = app
    TG_LOOP = asyncio.get_running_loop()
    threading.Thread(target=ig_loop, daemon=True).start()


def build_app():
    builder = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
    )
    if PROXY:
        builder = builder.proxy(PROXY).get_updates_proxy(PROXY)
    return builder.build()


def main():
    global cl, first_scan_done
    init_db()
    # اگر قبلاً اجرا شده، پیام‌های جدیدتر از آخرین اجرا هم پردازش می‌شوند
    first_scan_done = bool(query("SELECT 1 FROM seen LIMIT 1", fetch=True))
    print("Logging in to Instagram...")
    cl = ig_login()
    print("Instagram login OK")

    app = build_app()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unlink", unlink))
    app.add_handler(CommandHandler("method", method_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Bot is running...")
    app.run_polling(bootstrap_retries=-1)


main()
