import json
import os
import logging
from config import SEEN_FILE, DATA_DIR

logger = logging.getLogger(__name__)


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_seen() -> dict:
    """Load previously seen announcements from JSON file.

    Returns a dict: { professor_url: [list of announcement IDs] }
    """
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
    """Persist seen announcements to JSON file."""
    _ensure_data_dir()
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Failed to save seen.json: %s", e)


def get_new_announcements(professor_url: str, announcements: list, seen: dict) -> list:
    """Return only announcements not previously seen for this professor."""
    seen_ids = set(seen.get(professor_url, []))
    new = [a for a in announcements if a["id"] not in seen_ids]
    return new


def mark_seen(professor_url: str, announcements: list, seen: dict):
    """Add announcement IDs to the seen set for this professor."""
    seen_ids = seen.get(professor_url, [])
    existing = set(seen_ids)
    for a in announcements:
        existing.add(a["id"])
    seen[professor_url] = list(existing)
