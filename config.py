import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_TIME = os.getenv("CHECK_TIME", "09:00")  # legacy single-time support
_check_times_raw = os.getenv("CHECK_TIMES", CHECK_TIME)
CHECK_TIMES = [t.strip() for t in _check_times_raw.split(",") if t.strip()]

_professors_raw = os.getenv("PROFESSORS", "")
PROFESSORS = [url.strip() for url in _professors_raw.split(",") if url.strip()]

TIMEZONE = os.getenv("TIMEZONE", "Europe/Istanbul")

# ── AVESİS akademik personel dizini ───────────────────────────────────────────
# /seç komutunun hoca ekleme listesini bu kurumdan ve bu fakülteden çeker.
AVESIS_BASE_URL = os.getenv("AVESIS_BASE_URL", "https://avesis.yildiz.edu.tr").rstrip("/")
FACULTY_NAME = os.getenv("FACULTY_NAME", "Elektrik-Elektronik Fakültesi")
FACULTY_CACHE_TTL_HOURS = int(os.getenv("FACULTY_CACHE_TTL_HOURS", "24"))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SEEN_FILE = os.path.join(DATA_DIR, "seen.json")
# /seç ile yönetilen dinamik takip listesi. Yoksa PROFESSORS'tan tohumlanır.
TRACKED_FILE = os.path.join(DATA_DIR, "tracked.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 15


def validate():
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is not set")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID is not set")
    # Takip listesi /seç ile yönetiliyorsa PROFESSORS boş olabilir.
    if not PROFESSORS and not os.path.exists(TRACKED_FILE):
        errors.append("PROFESSORS is not set or empty")
    return errors
