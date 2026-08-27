from __future__ import annotations

import asyncio
import datetime
import logging
import sys
from zoneinfo import ZoneInfo

from telegram import BotCommand, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

import config
import directory
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
    format_check_summary,
    get_last_message_time,
)
from selection import cmd_sec, on_callback
from storage import (
    load_seen, save_seen, get_new_announcements, mark_seen,
    get_known_count, load_tracked,
    load_stats, save_stats, increment_daily_count,
    load_professor_names, save_professor_names,
)
from tracker import scrape_professor

TZ = ZoneInfo(config.TIMEZONE)

_log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(logging.FileHandler("avesis-tracker.log", encoding="utf-8"))
except (IOError, OSError):
    pass  # Vercel gibi read-only ortamlarda dosya oluşturulamaz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)

# ── Runtime state ─────────────────────────────────────────────────────────────
_check_lock: asyncio.Lock | None = None
_error_counts: dict[str, int] = {}    # consecutive error count per URL
_error_alerted: dict[str, bool] = {}  # whether threshold alert was sent
_background_tasks: set[asyncio.Task] = set()

DAILY_SUMMARY_HOUR = int(getattr(config, "DAILY_SUMMARY_HOUR", 22))
UPTIME_PING_HOURS = 24
MAX_CONSECUTIVE_ERRORS = 3
# ─────────────────────────────────────────────────────────────────────────────


def _spawn(coro) -> asyncio.Task:
    """Start a background task and keep a strong reference to it.

    asyncio only holds a weak reference, so an untracked task can be garbage
    collected mid-flight. Tracking them also lets post_stop cancel them before
    the event loop closes, instead of leaving "Task was destroyed but it is
    pending" warnings on shutdown.
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _now() -> datetime.datetime:
    return datetime.datetime.now(TZ)


def _last_check_str(stats: dict, fallback: str = "bilinmiyor") -> str:
    """Format stats["last_check_time"] for display."""
    raw = stats.get("last_check_time")
    if not raw:
        return fallback
    try:
        return datetime.datetime.fromisoformat(raw).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return fallback


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
        tracked = load_tracked()

        if not tracked:
            logger.info("Takip edilen hoca yok, kontrol atlanıyor.")
            if not silent:
                stats["last_check_time"] = _now().isoformat()
                save_stats(stats)
            if reply_chat_id:
                now_str = _now().strftime("%d.%m.%Y %H:%M")
                summary = format_check_summary([], [], now_str, 0)
                await send_text(reply_chat_id, summary, parse_mode="MarkdownV2")
            return 0

        total_new = 0
        checked_names: list[str] = []   # bu turda ulaşılan hocalar
        failed_names: list[str] = []    # bu turda ulaşılamayan hocalar

        for url in tracked:
            # A URL with no entry in seen.json has never been checked — either the
            # very first run or a profile just added through /seç. Its existing
            # announcements are baselined silently instead of being announced.
            is_new_profile = url not in seen

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
                failed_names.append(professor_name)
                continue

            checked_names.append(professor_name)

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

            if is_new_profile:
                mark_seen(url, result["announcements"], seen)
                logger.info(
                    "Yeni profil baz alındı: %s (%d mevcut duyuru sessizce kaydedildi)",
                    professor_name, len(result["announcements"]),
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
            # Günlük özet ve uptime ping aynı listeyi yeniden çizebilsin diye sakla.
            stats["last_checked"] = checked_names
            stats["last_failed"] = failed_names
            save_stats(stats)

            summary = format_check_summary(checked_names, failed_names, now_str, total_new)

            if total_new == 0 and not reply_chat_id:
                await edit_or_send_status(summary)

            if reply_chat_id:
                await send_text(reply_chat_id, summary, parse_mode="MarkdownV2")

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

    last_str = _last_check_str(stats, "Henüz kontrol yapılmadı")

    # Stats
    today = datetime.date.today()
    today_total = stats.get("daily_counts", {}).get(today.isoformat(), 0)
    weekly_total = sum(
        v for k, v in stats.get("daily_counts", {}).items()
        if k >= (today - datetime.timedelta(days=7)).isoformat()
    )

    # Professor list with error status
    tracked = load_tracked()
    prof_lines = []
    for url in tracked:
        name = names.get(url, url.rstrip("/").split("/")[-1])
        errors = _error_counts.get(url, 0)
        if errors >= MAX_CONSECUTIVE_ERRORS:
            status = escape_md(f"🔴 ({errors} hata, sessiz)")
        elif errors > 0:
            status = escape_md(f"⚠️ ({errors} hata)")
        else:
            status = "✅"
        prof_lines.append(f"  • {escape_md(name)} {status}")

    if not prof_lines:
        prof_lines = ["  _Takip edilen hoca yok — /sec ile ekleyin\\._"]

    text = (
        f"📊 *AVESİS Tracker Durumu*\n\n"
        f"🕐 *Son kontrol:* {escape_md(last_str)}\n"
        f"📈 *Bugün:* {today_total} yeni duyuru\n"
        f"📅 *Bu hafta:* {weekly_total} yeni duyuru\n\n"
        f"👨‍🏫 *Takip edilen \\({len(tracked)} profil\\):*\n"
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
            await send_daily_summary(
                today_count,
                day_stats.get("last_checked", []),
                day_stats.get("last_failed", []),
                _last_check_str(day_stats),
            )

        # ── Uptime ping ──────────────────────────────────────────────────
        last_msg = get_last_message_time()
        if last_msg is not None:
            silence_h = (datetime.datetime.now() - last_msg).total_seconds() / 3600
            if silence_h >= UPTIME_PING_HOURS:
                ping_stats = load_stats()
                await send_uptime_ping(
                    _last_check_str(ping_stats),
                    ping_stats.get("last_checked", []),
                    ping_stats.get("last_failed", []),
                )


# ── Startup ───────────────────────────────────────────────────────────────────

async def _warm_faculty_cache():
    """Prefetch the faculty roster so the first /seç responds instantly."""
    try:
        people = await asyncio.to_thread(directory.load_faculty)
        logger.info("Fakülte kadrosu hazır: %d kişi (%s)", len(people), config.FACULTY_NAME)
    except Exception as e:  # dizin olmadan da bot çalışmaya devam etmeli
        logger.warning("Fakülte kadrosu önceden yüklenemedi: %s", e)


async def post_init(application: Application):
    """Called by PTB after the Application is initialized, before polling starts."""
    global _check_lock
    _check_lock = asyncio.Lock()
    set_bot(application.bot)
    try:
        await application.bot.set_my_commands([
            BotCommand("kontrol", "Duyuruları şimdi kontrol et"),
            BotCommand("durum", "Bot durumu ve takip listesi"),
            BotCommand("sec", "Takip edilen hocaları seç"),
        ])
    except Exception as e:
        logger.warning("Komut menüsü ayarlanamadı: %s", e)
    await send_startup_message()
    await check_professors(silent=True)
    _spawn(_warm_faculty_cache())
    _spawn(_scheduler_loop())
    logger.info("Scheduler başlatıldı.")


async def post_stop(application: Application):
    """Cancel background tasks while the event loop is still alive."""
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Arka plan görevleri durduruldu (%d).", len(tasks))


def main():
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Yapılandırma hatası: %s", err)
        sys.exit(1)

    logger.info("AVESİS Tracker başlatılıyor...")
    logger.info("Takip edilen profil sayısı: %d", len(load_tracked()))
    logger.info("Kontrol saatleri: %s", ", ".join(config.CHECK_TIMES))

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    application.add_handler(CommandHandler("kontrol", cmd_kontrol))
    application.add_handler(CommandHandler("durum", cmd_durum))
    application.add_handler(CommandHandler(["sec", "secim"], cmd_sec))
    # Telegram yalnızca ASCII komutları bot_command olarak işaretler, bu yüzden
    # "/seç" CommandHandler'a düşmez — metin olarak yakalıyoruz.
    application.add_handler(
        MessageHandler(filters.Regex(r"(?i)^/se[çc](?:im)?(?:@\w+)?(?:\s|$)"), cmd_sec)
    )
    application.add_handler(CallbackQueryHandler(on_callback, pattern=r"^s:"))

    # run_polling() manages its own event loop — do NOT use asyncio.run()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
