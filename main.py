import asyncio
import datetime
import logging
import sys
from zoneinfo import ZoneInfo

import config
from bot import send_announcement, send_startup_message, send_no_announcement_message, send_error_alert
from storage import load_seen, save_seen, get_new_announcements, mark_seen
from tracker import scrape_professor

try:
    TZ = ZoneInfo(config.TIMEZONE)
except Exception:
    TZ = ZoneInfo("Europe/Istanbul")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("avesis-tracker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def check_professors(silent: bool = False, notify: bool = True):
    """Scrape all professors and notify on new announcements.

    silent=True: mark everything as seen without sending notifications (first run).
    notify=False: scrape and update seen.json but do not send Telegram messages (keepalive).
    """
    if silent:
        logger.info("İlk çalışma: mevcut duyurular kaydediliyor (bildirim gönderilmeyecek)...")
    elif not notify:
        logger.info("Canlı tutma kontrolü yapılıyor (bildirim gönderilmeyecek)...")
    else:
        logger.info("Duyuru kontrolü başlatılıyor...")

    seen = load_seen()
    any_new = False
    any_error = False

    for url in config.PROFESSORS:
        logger.info("Kontrol ediliyor: %s", url)
        result = scrape_professor(url)

        if result["error"] and not result["announcements"]:
            logger.warning("Hata (%s): %s", url, result["error"])
            if notify and not silent and result["error"] != "Duyurular bölümü bulunamadı.":
                any_error = True
                await send_error_alert(
                    f"{result['professor_name']} ({url})\n{result['error']}"
                )
            continue

        new = get_new_announcements(url, result["announcements"], seen)
        if not new:
            if not silent and notify:
                logger.info("Yeni duyuru yok: %s", result["professor_name"])
            continue

        if silent or not notify:
            logger.info("%d yeni içerik var (bildirim bekliyor): %s", len(new), result["professor_name"])
        else:
            any_new = True
            logger.info("%d yeni duyuru bulundu: %s", len(new), result["professor_name"])
            for announcement in new:
                await send_announcement(result["professor_name"], announcement, url)
                await asyncio.sleep(0.5)

        if notify or silent:
            mark_seen(url, new, seen)

    if notify or silent:
        save_seen(seen)
    if notify and not silent and not any_new and not any_error:
        logger.info("Tüm profiller kontrol edildi, yeni duyuru bulunamadı.")
        check_time = datetime.datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
        await send_no_announcement_message(check_time)


def _parse_times(times: list[str]) -> list[tuple[int, int]]:
    result = []
    for t in times:
        try:
            h, m = t.strip().split(":")
            result.append((int(h), int(m)))
        except Exception:
            logger.warning("Geçersiz saat formatı: %s", t)
    return result


def _now() -> datetime.datetime:
    return datetime.datetime.now(TZ)


def _next_run(schedules: list[tuple[int, int]]) -> datetime.datetime:
    """Return the nearest upcoming datetime from a list of (hour, minute) pairs."""
    now = _now()
    candidates = []
    for h, m in schedules:
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t <= now:
            t += datetime.timedelta(days=1)
        candidates.append(t)
    return min(candidates)


async def main():
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Yapılandırma hatası: %s", err)
        sys.exit(1)

    schedules = _parse_times(config.CHECK_TIMES)
    if not schedules:
        schedules = [(9, 0)]

    logger.info("AVESİS Tracker başlatılıyor...")
    logger.info("Takip edilen profil sayısı: %d", len(config.PROFESSORS))
    logger.info("Kontrol saatleri: %s", ", ".join(config.CHECK_TIMES))

    try:
        await send_startup_message()
    except Exception as e:
        logger.warning("Başlangıç mesajı gönderilemedi: %s", e)

    # First run: silently mark existing announcements as seen
    await check_professors(silent=True)

    last_notify: datetime.datetime | None = None
    last_keepalive: datetime.datetime | None = None

    KEEPALIVE_INTERVAL = 20 * 60   # 20 dakika
    NOTIFY_INTERVAL   = 2 * 60 * 60  # 2 saat

    logger.info("Keepalive: her 20 dakika | Bildirim: her 2 saat")

    while True:
        await asyncio.sleep(30)
        now = _now()

        # 20 dakikada bir sessiz kontrol (box'u canlı tutar)
        if last_keepalive is None or (now - last_keepalive).total_seconds() >= KEEPALIVE_INTERVAL:
            last_keepalive = now
            await check_professors(notify=False)

        # Her 2 saatte bir bildirimli kontrol
        if last_notify is None or (now - last_notify).total_seconds() >= NOTIFY_INTERVAL:
            last_notify = now
            await check_professors(notify=True)


if __name__ == "__main__":
    asyncio.run(main())
