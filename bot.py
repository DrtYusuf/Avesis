from __future__ import annotations

import logging
from telegram import Bot
from telegram.error import TelegramError
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def get_bot() -> Bot:
    """Create a fresh Bot instance each time (safe across asyncio.run() calls)."""
    return Bot(token=TELEGRAM_BOT_TOKEN)


def _escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def _format_message(professor_name: str, announcement: dict, profile_url: str) -> str:
    title = announcement.get("title", "Başlık yok")
    date = announcement.get("date", "")
    content = announcement.get("content", "")
    short_content = content[:200] + ("..." if len(content) > 200 else "")

    lines = [
        f"📢 *Yeni Duyuru*",
        f"",
        f"👨‍🏫 *Hoca:* {_escape_md(professor_name)}",
        f"📌 *Başlık:* {_escape_md(title)}",
    ]
    if date:
        lines.append(f"📅 *Tarih:* {_escape_md(date)}")
    if short_content:
        lines.append(f"")
        lines.append(f"📝 {_escape_md(short_content)}")
    lines.append(f"")
    lines.append(f"🔗 [Profile Git]({profile_url})")

    return "\n".join(lines)


async def send_announcement(professor_name: str, announcement: dict, profile_url: str):
    """Send a single announcement notification to Telegram."""
    bot = get_bot()
    message = _format_message(professor_name, announcement, profile_url)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=False,
        )
        logger.info("Telegram mesajı gönderildi: %s", announcement.get("title", ""))
    except TelegramError as e:
        logger.error("Telegram mesajı gönderilemedi: %s", e)


async def send_error_alert(message: str):
    """Send an error notification to Telegram."""
    bot = get_bot()
    safe = _escape_md(message)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"⚠️ *AVESİS Tracker Hatası*\n\n{safe}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except TelegramError as e:
        logger.error("Hata bildirimi gönderilemedi: %s", e)


async def send_startup_message():
    """Notify that the bot has started successfully."""
    bot = get_bot()
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="✅ *AVESİS Tracker başlatıldı\\.*\nGünlük duyuru kontrolü aktif\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except TelegramError as e:
        logger.error("Başlangıç mesajı gönderilemedi: %s", e)
