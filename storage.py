import json
import os
import logging
import datetime
from config import SEEN_FILE, DATA_DIR

logger = logging.getLogger(__name__)

STATS_FILE = os.path.join(DATA_DIR, "stats.json")
NAMES_FILE = os.path.join(DATA_DIR, "professor_names.json")
STATUS_MSG_FILE = os.path.join(DATA_DIR, "status_message.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ── Seen announcements ────────────────────────────────────────────────────────

def load_seen() -> dict:
    _ensure_data_dir()
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to load seen.json: %s", e)
        return {}


def save_seen(seen: dict):
    _ensure_data_dir()
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Failed to save seen.json: %s", e)


def get_new_announcements(professor_url: str, announcements: list, seen: dict) -> list:
    seen_ids = set(seen.get(professor_url, []))
    return [a for a in announcements if a["id"] not in seen_ids]


def get_known_count(professor_url: str, seen: dict) -> int:
    """Return how many announcement IDs we've previously seen for this URL."""
    return len(seen.get(professor_url, []))


def mark_seen(professor_url: str, announcements: list, seen: dict):
    existing = set(seen.get(professor_url, []))
    for a in announcements:
        existing.add(a["id"])
    seen[professor_url] = list(existing)


# ── Stats ─────────────────────────────────────────────────────────────────────

def load_stats() -> dict:
    _ensure_data_dir()
    if not os.path.exists(STATS_FILE):
        return {"daily_counts": {}, "last_check_time": None}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to load stats.json: %s", e)
        return {"daily_counts": {}, "last_check_time": None}


def save_stats(stats: dict):
    _ensure_data_dir()
    # Prune entries older than 7 days
    cutoff = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    stats["daily_counts"] = {
        k: v for k, v in stats.get("daily_counts", {}).items() if k >= cutoff
    }
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Failed to save stats.json: %s", e)


def increment_daily_count(stats: dict, n: int):
    today = datetime.date.today().isoformat()
    stats["daily_counts"][today] = stats["daily_counts"].get(today, 0) + n


# ── Professor name cache ──────────────────────────────────────────────────────

def load_professor_names() -> dict:
    """Return cached {url: professor_name} mapping."""
    _ensure_data_dir()
    if not os.path.exists(NAMES_FILE):
        return {}
    try:
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to load professor_names.json: %s", e)
        return {}


def save_professor_names(names: dict):
    _ensure_data_dir()
    try:
        with open(NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Failed to save professor_names.json: %s", e)


# ── Status message ID ─────────────────────────────────────────────────────────

def load_status_message_id() -> int | None:
    """Return the saved Telegram message_id of the last status message, or None."""
    _ensure_data_dir()
    if not os.path.exists(STATUS_MSG_FILE):
        return None
    try:
        with open(STATUS_MSG_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("message_id")
    except (json.JSONDecodeError, IOError):
        return None


def save_status_message_id(message_id: int):
    _ensure_data_dir()
    try:
        with open(STATUS_MSG_FILE, "w", encoding="utf-8") as f:
            json.dump({"message_id": message_id}, f)
    except IOError as e:
        logger.error("Failed to save status_message.json: %s", e)
