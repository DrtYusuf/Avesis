from __future__ import annotations

import json
import os
import logging
import datetime
import config
from config import SEEN_FILE, TRACKED_FILE, DATA_DIR

logger = logging.getLogger(__name__)

STATS_FILE = os.path.join(DATA_DIR, "stats.json")
NAMES_FILE = os.path.join(DATA_DIR, "professor_names.json")
STATUS_MSG_FILE = os.path.join(DATA_DIR, "status_message.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ── Tracked professors ────────────────────────────────────────────────────────
# The tracked list is managed at runtime by /seç. On first run it is seeded from
# the PROFESSORS env var; from then on tracked.json is the single source of truth
# (an existing but empty file means "intentionally following nobody").

def load_tracked() -> list[str]:
    """Return the tracked profile URLs, seeding from config.PROFESSORS on first run."""
    _ensure_data_dir()
    if not os.path.exists(TRACKED_FILE):
        seeded = _dedupe(config.PROFESSORS)
        if seeded:
            save_tracked(seeded)
        return seeded
    try:
        with open(TRACKED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to load tracked.json: %s", e)
        return _dedupe(config.PROFESSORS)

    urls = data.get("professors", []) if isinstance(data, dict) else data
    return _dedupe(u for u in urls if isinstance(u, str))


def save_tracked(urls: list[str]):
    _ensure_data_dir()
    try:
        with open(TRACKED_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"professors": _dedupe(urls), "updated_at": datetime.datetime.now().isoformat()},
                f, ensure_ascii=False, indent=2,
            )
    except IOError as e:
        logger.error("Failed to save tracked.json: %s", e)


def add_tracked(url: str) -> bool:
    """Start following a profile. Returns False if it was already tracked."""
    urls = load_tracked()
    if _normalize_url(url) in {_normalize_url(u) for u in urls}:
        return False
    urls.append(url)
    save_tracked(urls)
    return True


def remove_tracked(url: str) -> bool:
    """Stop following a profile. Returns False if it wasn't tracked."""
    urls = load_tracked()
    target = _normalize_url(url)
    kept = [u for u in urls if _normalize_url(u) != target]
    if len(kept) == len(urls):
        return False
    save_tracked(kept)
    return True


def is_tracked(url: str) -> bool:
    target = _normalize_url(url)
    return any(_normalize_url(u) == target for u in load_tracked())


def _normalize_url(url: str) -> str:
    """Compare URLs ignoring trailing slashes and case."""
    return url.strip().rstrip("/").lower()


def _dedupe(urls) -> list[str]:
    """Drop duplicates and blanks while preserving order."""
    result, seen_urls = [], set()
    for url in urls:
        clean = url.strip().rstrip("/")
        if not clean:
            continue
        key = clean.lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        result.append(clean)
    return result


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

def load_status_message_id():
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
