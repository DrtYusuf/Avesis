from __future__ import annotations

import asyncio
import datetime
import logging
import sys
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from bot import (
    set_bot,
    escape_md,
    edit_or_send_status,
    send_professor_announcements,
    send_error_alert,
    send_startup_message,
    send_daily_summary,
    send_uptime_ping,
    send_text,
    get_last_message_time,
)
from storage import (
    load_seen, save_seen, get_new_announcements, mark_seen,
    get_known_count,
    load_stats, save_stats, increment_daily_count,
    load_professor_names, save_professor_names,
)
from tracker import scrape_professor

TZ = ZoneInfo(config.TIMEZONE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("avesis-tracker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Runtime state ─────────────────────────────────────────────────────────────
_check_lock: asyncio.Lock | None = None
_error_counts: dict[str, int] = {}    # consecutive error count per URL
_error_alerted: dict[str, bool] = {}  # whether threshold alert was sent

DAILY_SUMMARY_HOUR = int(getattr(config, "DAILY_SUMMARY_HOUR", 22))
UPTIME_PING_HOURS = 24
MAX_CONSECUTIVE_ERRORS = 3
# ─────────────────────────────────────────────────────────────────────────────


def _now() -> datetime.datetime:
    return datetime.datetime.now(TZ)


async def check_professors(silent: bool = False, reply_chat_id=None) -> int:
    """Check all professors for new announcements.

    Returns total new announcements found.
    silent=True: mark everything seen without notifications (first run).
    """
    lock = _check_lock
    if lock is None:
        return 0

    if lock.locked():
        if reply_chat_id:
            await send_text(reply_chat_id, "⏳ Kontrol zaten devam ediyor, lütfen bekleyin.")
        return 0

    async with lock:
        if silent:
            logger.info("İlk çalışma: mevcut duyurular kaydediliyor...")
        else:
            logger.info("Duyuru kontrolü başlatılıyor...")

        seen = load_seen()
        stats = load_stats()
        names = load_professor_names()
        total_new = 0

        for url in config.PROFESSORS:
            logger.info("Kontrol ediliyor: %s", url)
            result = scrape_professor(url)
            professor_name = result["professor_name"] or url.rstrip("/").split("/")[-1]

            # Cache professor name
            if result["professor_name"]:
                names[url] = result["professor_name"]

            # ── Error handling ───────────────────────────────────────────
            if result["error"] and not result["announcements"]:
                _error_counts[url] = _error_counts.get(url, 0) + 1
                consecutive = _error_counts[url]
                logger.warning("Hata #%d (%s): %s", consecutive, url, result["error"])

                if not silent and result["error"] != "Duyurular bölümü bulunamadı.":
                    if consecutive == MAX_CONSECUTIVE_ERRORS:
                        _error_alerted[url] = True
                        await send_error_alert(
                            f"{professor_name}\n"
                            f"Art arda {consecutive}. hata: {result['error']}\n"
                            f"Sonraki hatalar sessizce geçilecek."
                        )
                    elif consecutive < MAX_CONSECUTIVE_ERRORS:
                        await send_error_alert(f"{professor_name}\n{result['error']}")
                    # consecutive > MAX: already alerted, stay silent
                continue

            # ── Recovery ─────────────────────────────────────────────────
            if _error_counts.get(url, 0) > 0:
                was_alerted = _error_alerted.get(url, False)
                _error_counts[url] = 0
                _error_alerted[url] = False
                if was_alerted and not silent:
                    await send_error_alert(
                        f"✅ {professor_name} — bağlantı yeniden sağlandı."
                    )

            # ── Scrape failure protection ─────────────────────────────────
            # If we've previously seen announcements but now get 0 with no error,
            # treat it as a suspicious scrape failure — don't touch seen.
            if not result["announcements"] and get_known_count(url, seen) > 0:
                logger.warning(
                    "Şüpheli: %s için daha önce duyuru vardı ama şimdi 0 sonuç döndü, "
                    "seen güncellenmeyecek.", url
                )
                continue

            new = get_new_announcements(url, result["announcements"], seen)
            if not new:
                if not silent:
                    logger.info("Yeni duyuru yok: %s", professor_name)
                continue

            if silent:
                logger.info("%d mevcut duyuru kaydedildi (sessiz): %s", len(new), professor_name)
            else:
                total_new += len(new)
                logger.info("%d yeni duyuru bulundu: %s", len(new), professor_name)
                await send_professor_announcements(professor_name, new, url)
                await asyncio.sleep(0.5)

            mark_seen(url, new, seen)

        save_seen(seen)
        save_professor_names(names)

        if not silent:
            if total_new > 0:
                increment_daily_count(stats, total_new)
            now_str = _now().strftime("%d.%m.%Y %H:%M")
            stats["last_check_time"] = _now().isoformat()
            save_stats(stats)

            if total_new == 0 and not reply_chat_id:
                await edit_or_send_status(
                    f"✅ *Bot aktif*\n\nSon kontrol: {escape_md(now_str)}\nYeni duyuru bulunamadı\\."
                )

            if reply_chat_id:
                if total_new > 0:
                    await send_text(reply_chat_id, f"✅ Kontrol tamamlandı. {total_new} yeni duyuru bulundu.")
                else:
                    await send_text(reply_chat_id, "✅ Kontrol tamamlandı. Yeni duyuru bulunamadı.")

        return total_new


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_kontrol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kontrol — manually trigger a check."""
    chat_id = update.effective_chat.id
    await send_text(chat_id, "🔍 Kontrol başlatılıyor...")
    await check_professors(reply_chat_id=chat_id)


async def cmd_durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/durum — show bot status and stats."""
    chat_id = update.effective_chat.id
    stats = load_stats()
    names = load_professor_names()

    # Last check time
    last_raw = stats.get("last_check_time")
    if last_raw:
        try:
            last_dt = datetime.datetime.fromisoformat(last_raw)
            last_str = last_dt.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            last_str = "Bilinmiyor"
    else:
        last_str = "Henüz kontrol yapılmadı"

    # Stats
    today = datetime.date.today()
    today_total = stats.get("daily_counts", {}).get(today.isoformat(), 0)
    weekly_total = sum(
        v for k, v in stats.get("daily_counts", {}).items()
        if k >= (today - datetime.timedelta(days=7)).isoformat()
    )

    # Professor list with error status
    prof_lines = []
    for url in config.PROFESSORS:
        name = names.get(url, url.rstrip("/").split("/")[-1])
        errors = _error_counts.get(url, 0)
        if errors >= MAX_CONSECUTIVE_ERRORS:
            status = escape_md(f"🔴 ({errors} hata, sessiz)")
        elif errors > 0:
            status = escape_md(f"⚠️ ({errors} hata)")
        else:
            status = "✅"
        prof_lines.append(f"  • {escape_md(name)} {status}")

    text = (
        f"📊 *AVESİS Tracker Durumu*\n\n"
        f"🕐 *Son kontrol:* {escape_md(last_str)}\n"
        f"📈 *Bugün:* {today_total} yeni duyuru\n"
        f"📅 *Bu hafta:* {weekly_total} yeni duyuru\n\n"
        f"👨‍🏫 *Takip edilen \\({len(config.PROFESSORS)} profil\\):*\n"
        + "\n".join(prof_lines)
    )
    await send_text(chat_id, text, parse_mode="MarkdownV2")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _parse_times(times: list[str]) -> list[tuple[int, int]]:
    result = []
    for t in times:
        try:
            h, m = t.strip().split(":")
            result.append((int(h), int(m)))
        except Exception:
            logger.warning("Geçersiz saat formatı: %s", t)
    return result


def _next_run(schedules: list[tuple[int, int]]) -> datetime.datetime:
    now = _now()
    candidates = []
    for h, m in schedules:
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now:
            t += datetime.timedelta(days=1)
        candidates.append(t)
    return min(candidates)


async def _scheduler_loop():
    """Background task: scheduled checks + daily summary + uptime ping."""
    schedules = _parse_times(config.CHECK_TIMES) or [(9, 0)]
    last_run: datetime.datetime | None = None
    last_daily_date: datetime.date | None = None
    logged_next: datetime.datetime | None = None

    while True:
        nxt = _next_run(schedules)
        if nxt != logged_next:
            logger.info("Bir sonraki kontrol: %s", nxt.strftime("%Y-%m-%d %H:%M"))
            logged_next = nxt

        await asyncio.sleep(30)
        now = _now()

        # ── Scheduled check ──────────────────────────────────────────────
        for h, m in schedules:
            scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if (
                now.hour == h
                and now.minute == m
                and (last_run is None or last_run < scheduled)
            ):
                last_run = scheduled
                await check_professors()
                break

        # ── Daily summary ────────────────────────────────────────────────
        if (
            now.hour == DAILY_SUMMARY_HOUR
            and now.minute == 0
            and last_daily_date != now.date()
        ):
            last_daily_date = now.date()
            await asyncio.sleep(2)  # let any concurrent check settle first
            day_stats = load_stats()
            today_count = day_stats.get("daily_counts", {}).get(now.date().isoformat(), 0)
            await send_daily_summary(today_count)

        # ── Uptime ping ──────────────────────────────────────────────────
        last_msg = get_last_message_time()
        if last_msg is not None:
            silence_h = (datetime.datetime.now() - last_msg).total_seconds() / 3600
            if silence_h >= UPTIME_PING_HOURS:
                ping_stats = load_stats()
                last_raw = ping_stats.get("last_check_time")
                if last_raw:
                    try:
                        last_dt = datetime.datetime.fromisoformat(last_raw)
                        last_check_str = last_dt.strftime("%d.%m.%Y %H:%M")
                    except ValueError:
                        last_check_str = "bilinmiyor"
                else:
                    last_check_str = "bilinmiyor"
                await send_uptime_ping(last_check_str)


# ── Startup ───────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    """Called by PTB after the Application is initialized, before polling starts."""
    global _check_lock
    _check_lock = asyncio.Lock()
    set_bot(application.bot)
    await send_startup_message()
    await check_professors(silent=True)
    asyncio.create_task(_scheduler_loop())
    logger.info("Scheduler başlatıldı.")


def main():
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Yapılandırma hatası: %s", err)
        sys.exit(1)

    logger.info("AVESİS Tracker başlatılıyor...")
    logger.info("Takip edilen profil sayısı: %d", len(config.PROFESSORS))
    logger.info("Kontrol saatleri: %s", ", ".join(config.CHECK_TIMES))

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("kontrol", cmd_kontrol))
    application.add_handler(CommandHandler("durum", cmd_durum))

    # run_polling() manages its own event loop — do NOT use asyncio.run()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
