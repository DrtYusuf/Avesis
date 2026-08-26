from __future__ import annotations

import datetime
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from storage import load_status_message_id, save_status_message_id

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


# ── Check summary formatting ──────────────────────────────────────────────────

CHECK_LIST_LIMIT = 25  # keep the message well under Telegram's 4096 char cap


def _bullet_list(names: list, limit: int = CHECK_LIST_LIMIT) -> str:
    """Render names as an escaped MarkdownV2 bullet list, truncating long lists."""
    shown = names[:limit]
    lines = [f"• {escape_md(name)}" for name in shown]
    remaining = len(names) - len(shown)
    if remaining > 0:
        lines.append(escape_md(f"…ve {remaining} hoca daha"))
    return "\n".join(lines)


def _format_summary(
    title: str, status_line: str, when: str, checked: list, failed: list
) -> str:
    """Shared layout for the check summary and the daily recap."""
    lines = [f"{title}\n\n{status_line}"]

    if when:
        lines.append(f"🕐 {escape_md(when)}")

    if checked:
        lines.append(f"\n👨‍🏫 *Kontrol edilenler \\({len(checked)}\\):*")
        lines.append(_bullet_list(checked))

    if failed:
        lines.append(f"\n⚠️ *Ulaşılamayanlar \\({len(failed)}\\):*")
        lines.append(_bullet_list(failed))

    if not checked and not failed:
        lines.append("\n_Takip edilen hoca yok — /sec ile ekleyin\\._")

    return "\n".join(lines)


def format_check_summary(
    checked: list, failed: list, when: str = "", total_new: int = 0
) -> str:
    """Build the 'check finished' message, listing which professors were checked."""
    status = (
        f"📢 *{total_new}* yeni duyuru bulundu\\."
        if total_new > 0
        else "📭 Yeni duyuru yok\\."
    )
    return _format_summary("✅ *Duyurular kontrol edildi*", status, when, checked, failed)


def format_daily_summary(
    count: int, checked: list, failed: list, when: str = ""
) -> str:
    """Build the end-of-day recap in the same layout as the check summary."""
    status = (
        f"📢 Bugün toplam *{count}* yeni duyuru bulundu\\."
        if count > 0
        else "📭 Bugün yeni duyuru bulunamadı\\."
    )
    return _format_summary("📊 *Günlük Özet*", status, when, checked, failed)


# ── Status message (edit-in-place) ────────────────────────────────────────────

async def edit_or_send_status(text: str) -> None:
    """Edit the last status message if possible; otherwise send a new one and save its ID."""
    bot = _get_bot()
    msg_id = load_status_message_id()
    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=TELEGRAM_CHAT_ID,
                message_id=msg_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            _record_send()
            return
        except TelegramError as e:
            if "message is not modified" in str(e).lower():
                _record_send()
                return  # içerik aynı, sorun yok
            pass  # mesaj silinmiş ya da çok eski — yeni gönder

    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        save_status_message_id(msg.message_id)
        _record_send()
    except TelegramError as e:
        logger.error("Durum mesajı gönderilemedi: %s", e)


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


async def send_daily_summary(
    count: int, checked: list | None = None, failed: list | None = None, when: str = ""
):
    """Send the end-of-day recap, listing the professors covered by the last check.

    A day with new announcements gets its own message; a quiet day only updates
    the existing status message so the chat doesn't fill up.
    """
    text = format_daily_summary(count, checked or [], failed or [], when)
    if count > 0:
        bot = _get_bot()
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            _record_send()
        except TelegramError as e:
            logger.error("Günlük özet gönderilemedi: %s", e)
    else:
        await edit_or_send_status(text)


async def send_uptime_ping(last_check: str, checked: list | None = None, failed: list | None = None):
    """Refresh the status message so the user can tell the bot is still alive.

    Re-renders the last check's professor list so the ping doesn't overwrite the
    summary with less information than it already showed.
    """
    await edit_or_send_status(
        format_check_summary(checked or [], failed or [], last_check)
    )


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
