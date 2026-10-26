"""آزمون یکپارچگی — استخراج پست از پیام دایرکت و جریان ثبت (بخش ۳.۱ و مرحله ۷ سند)."""
from __future__ import annotations

from types import SimpleNamespace

from app.instagram.inbox import extract_post

from ..conftest import USER1, make_paid_sub


# ---------- پیام‌های جعلی اینستاگرام ----------
def _msg(**kw):
    return SimpleNamespace(**kw)


def test_extract_from_shared_post():
    m = _msg(media_share=SimpleNamespace(code="CxAB123"), clip=None, text="")
    result = extract_post(m)
    assert result is not None
    url, shortcode, kind = result
    assert shortcode == "CxAB123"
    assert url == "https://www.instagram.com/p/CxAB123/"
    assert kind == "post"


def test_extract_from_shared_reel():
    m = _msg(media_share=None, clip=SimpleNamespace(code="Rxyz99"), text="")
    url, shortcode, kind = extract_post(m)
    assert kind == "reel"
    assert "reel" in url


def test_extract_from_text_link():
    m = _msg(media_share=None, clip=None,
             text="ببین این رو https://www.instagram.com/reel/DAf9xZz1/ عالیه")
    url, shortcode, kind = extract_post(m)
    assert shortcode == "DAf9xZz1"
    assert kind == "reel"


def test_extract_from_deep_payload():
    """لینک داخل ساختار xma/link (روش ۳ استخراج)."""
    m = _msg(media_share=None, clip=None, text="",
             xma_share=SimpleNamespace(link=SimpleNamespace(
                 url="https://www.instagram.com/p/DDdd112/")))
    url, shortcode, kind = extract_post(m)
    assert shortcode == "DDdd112"


def test_extract_nothing():
    m = _msg(media_share=None, clip=None, text="سلام")
    assert extract_post(m) is None


# ---------- جریان یکپارچه: پیام دایرکت → صف → تکمیل ----------
async def test_inbox_message_to_delivery(engine, services, fake_sender, notifier):
    """کاربر متصل، پست می‌فرستد؛ درخواست ثبت و کامل می‌شود (مرحله ۷ سند)."""
    make_paid_sub(services, USER1)
    # اتصال اینستاگرام
    code = services.links_repo.create_code("zoe_ig")
    ok, _ = services.links_repo.link(code, USER1)
    assert ok

    # پیام دایرکت شبیه‌سازی‌شده با پست اشتراکی
    message = _msg(media_share=SimpleNamespace(code="INTEG1"), clip=None, text="")
    from app.instagram.inbox import LINK_RE  # noqa: F401 — مطمئنیم ماژول لود است
    result = extract_post(message)
    assert result is not None
    url, shortcode, kind = result

    # ثبت مستقیم در موتور (شبیه کاری که inbox در حلقه تلگرام می‌کند)
    ok2, rid = await engine.submit(USER1, url, shortcode, kind)
    assert ok2
    req = engine._pick_next()
    assert req is not None
    await engine._process(req)
    row = services.downloads_repo.get(rid)
    assert row["status"] == "completed"
    assert len(fake_sender.sent) == 1
    assert fake_sender.sent[0][0] == USER1


async def test_unlinked_user_gets_code(services):
    """کاربر وصل‌نشده فقط کد اتصال می‌گیرد (بخش ۵.۲)."""
    code = services.links_repo.create_code("newbie_ig")
    assert len(code) == 6
    assert services.links_repo.find_by_ig("newbie_ig") is None  # هنوز متصل نیست


async def test_blocked_user_request_rejected(engine, services, notifier):
    make_paid_sub(services, USER1)
    services.users_repo.set_blocked(USER1, True, "test")
    ok, msg = await engine.submit(USER1, "https://instagram.com/reel/BLOCK1/", "BLOCK1")
    assert ok is False
    assert "مسدود" in msg
