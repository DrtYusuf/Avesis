import asyncio
import datetime
import logging
import sys

import config
from bot import send_announcement, send_startup_message
from storage import load_seen, save_seen, get_new_announcements, mark_seen
from tracker import scrape_professor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("avesis-tracker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def check_professors():
    """Scrape all professors and notify on new announcements."""
    logger.info("Duyuru kontrolü başlatılıyor...")
    seen = load_seen()
    any_new = False

    for url in config.PROFESSORS:
        logger.info("Kontrol ediliyor: %s", url)
        result = scrape_professor(url)

        if result["error"] and not result["announcements"]:
            logger.warning("Hata (%s): %s", url, result["error"])
            continue

        new = get_new_announcements(url, result["announcements"], seen)
        if not new:
            logger.info("Yeni duyuru yok: %s", result["professor_name"])
            continue

        any_new = True
        logger.info("%d yeni duyuru bulundu: %s", len(new), result["professor_name"])

        for announcement in new:
            await send_announcement(result["professor_name"], announcement, url)
            await asyncio.sleep(0.5)

        mark_seen(url, new, seen)

    save_seen(seen)
    if not any_new:
        logger.info("Tüm profiller kontrol edildi, yeni duyuru bulunamadı.")


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
    """Return the nearest upcoming datetime from a list of (hour, minute) pairs."""
    now = datetime.datetime.now()
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

    # Run once immediately on startup
    await check_professors()

    while True:
        nxt = _next_run(schedules)
        wait = (nxt - datetime.datetime.now()).total_seconds()
        logger.info("Bir sonraki kontrol: %s (%.0f saniye sonra)", nxt.strftime("%Y-%m-%d %H:%M"), wait)
        await asyncio.sleep(wait)
        await check_professors()


if __name__ == "__main__":
    asyncio.run(main())
