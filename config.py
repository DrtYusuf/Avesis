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

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SEEN_FILE = os.path.join(DATA_DIR, "seen.json")

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
    if not PROFESSORS:
        errors.append("PROFESSORS is not set or empty")
    return errors
