from __future__ import annotations

import datetime
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

# ── Bot instance management ───────────────────────────────────────────────────
_bot: Bot | None = None
_last_message_time: datetime.datetime | None = None


def set_bot(bot: Bot):
    """Store the Application's bot instance to reuse its connection pool."""
    global _bot
    _bot = bot


def _get_bot() -> Bot:
    return _bot or Bot(token=TELEGRAM_BOT_TOKEN)


def get_last_message_time() -> datetime.datetime | None:
    return _last_message_time


def _record_send():
    global _last_message_time
    _last_message_time = datetime.datetime.now()


# ── Markdown escaping ─────────────────────────────────────────────────────────

def escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Send functions ────────────────────────────────────────────────────────────

async def send_professor_announcements(
    professor_name: str, announcements: list, profile_url: str
):
    """Send all new announcements for a professor as a single message with inline button."""
    bot = _get_bot()
    docs_url = profile_url.rstrip("/") + "/dokumanlar"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 Duyuruyu Oku", url=docs_url)
    ]])

    if len(announcements) == 1:
        a = announcements[0]
        title = a.get("title", "Başlık yok")
        date = a.get("date", "")
        content = a.get("content", "")
        short = content[:200] + ("..." if len(content) > 200 else "")

        lines = [
            "📢 *Yeni Duyuru*",
            "",
            f"👨‍🏫 *Hoca:* {escape_md(professor_name)}",
            f"📌 *Başlık:* {escape_md(title)}",
        ]
        if date:
            lines.append(f"📅 *Tarih:* {escape_md(date)}")
        if short:
            lines += ["", f"📝 {escape_md(short)}"]
        text = "\n".join(lines)
    else:
        lines = [
            f"📢 *{len(announcements)} Yeni Duyuru*",
            f"👨‍🏫 *{escape_md(professor_name)}*",
            "",
        ]
        for i, a in enumerate(announcements, 1):
            title = escape_md(a.get("title", "Başlık yok"))
            date = a.get("date", "")
            date_str = f" \\({escape_md(date)}\\)" if date else ""
            lines.append(f"{i}\\. {title}{date_str}")
        text = "\n".join(lines)

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )
        _record_send()
        logger.info("Duyuru gönderildi: %s (%d adet)", professor_name, len(announcements))
    except TelegramError as e:
        logger.error("Duyuru mesajı gönderilemedi: %s", e)


async def send_daily_summary(count: int):
    """Send daily summary message."""
    bot = _get_bot()
    if count > 0:
        text = f"📊 *Günlük Özet*\n\nBugün toplam *{count}* yeni duyuru bulundu\\."
    else:
        text = "📊 *Günlük Özet*\n\nBugün yeni duyuru bulunamadı\\."
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        _record_send()
    except TelegramError as e:
        logger.error("Günlük özet gönderilemedi: %s", e)


async def send_uptime_ping(last_check: str):
    """Send uptime confirmation after 24h silence."""
    bot = _get_bot()
    safe = escape_md(last_check)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"✅ *Bot aktif*\n\nSon kontrol: {safe}\nYeni duyuru bulunamadı\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        _record_send()
    except TelegramError as e:
        logger.error("Uptime ping gönderilemedi: %s", e)


async def send_error_alert(message: str):
    """Send an error/info notification. Message is auto-escaped for MarkdownV2."""
    bot = _get_bot()
    safe = escape_md(message)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"⚠️ *AVESİS Tracker*\n\n{safe}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        _record_send()
    except TelegramError as e:
        logger.error("Hata bildirimi gönderilemedi: %s", e)


async def send_startup_message():
    """Notify that the bot has started successfully."""
    bot = _get_bot()
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="✅ *AVESİS Tracker başlatıldı\\.*\nGünlük duyuru kontrolü aktif\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        _record_send()
    except TelegramError as e:
        logger.error("Başlangıç mesajı gönderilemedi: %s", e)


async def send_text(chat_id, text: str, parse_mode=None):
    """Send a plain or formatted message to a specific chat."""
    bot = _get_bot()
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except TelegramError as e:
        logger.error("Mesaj gönderilemedi (%s): %s", chat_id, e)
