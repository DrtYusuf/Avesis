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

# ── Redis backend (Vercel / serverless) ──────────────────────────────────────
_redis = None
_redis_checked = False


def _get_redis():
    global _redis, _redis_checked
    if not _redis_checked:
        _redis_checked = True
        url = os.getenv("UPSTASH_REDIS_REST_URL")
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        if url and token:
            try:
                from upstash_redis import Redis
                _redis = Redis(url=url, token=token)
            except ImportError:
                logger.warning("upstash-redis kurulu degil, dosya depolama kullaniliyor")
            except Exception as e:
                logger.error("Redis baglantisi kurulamadi: %s", e)
    return _redis


# ── Dual-mode helpers ────────────────────────────────────────────────────────

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_json(redis_key: str, file_path: str, default_factory=dict):
    r = _get_redis()
    if r is not None:
        try:
            data = r.get(redis_key)
            if data is None:
                return default_factory()
            return json.loads(data) if isinstance(data, str) else data
        except Exception as e:
            logger.error("Redis okuma hatasi (%s): %s", redis_key, e)
            return default_factory()
    _ensure_data_dir()
    if not os.path.exists(file_path):
        return default_factory()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Dosya okuma hatasi (%s): %s", file_path, e)
        return default_factory()


def _save_json(redis_key: str, file_path: str, data):
    r = _get_redis()
    if r is not None:
        try:
            r.set(redis_key, json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error("Redis yazma hatasi (%s): %s", redis_key, e)
        return
    _ensure_data_dir()
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Dosya yazma hatasi (%s): %s", file_path, e)


# ── Tracked professors ────────────────────────────────────────────────────────

def load_tracked() -> list[str]:
    data = _load_json("tracked", TRACKED_FILE)
    if not data:
        seeded = _dedupe(config.PROFESSORS)
        if seeded:
            save_tracked(seeded)
        return seeded
    urls = data.get("professors", []) if isinstance(data, dict) else data
    return _dedupe(u for u in urls if isinstance(u, str))


def save_tracked(urls: list[str]):
    _save_json("tracked", TRACKED_FILE, {
        "professors": _dedupe(urls),
        "updated_at": datetime.datetime.now().isoformat(),
    })


def add_tracked(url: str) -> bool:
    urls = load_tracked()
    if _normalize_url(url) in {_normalize_url(u) for u in urls}:
        return False
    urls.append(url)
    save_tracked(urls)
    return True


def remove_tracked(url: str) -> bool:
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
    return url.strip().rstrip("/").lower()


def _dedupe(urls) -> list[str]:
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
    return _load_json("seen", SEEN_FILE)


def save_seen(seen: dict):
    _save_json("seen", SEEN_FILE, seen)


def get_new_announcements(professor_url: str, announcements: list, seen: dict) -> list:
    seen_ids = set(seen.get(professor_url, []))
    return [a for a in announcements if a["id"] not in seen_ids]


def get_known_count(professor_url: str, seen: dict) -> int:
    return len(seen.get(professor_url, []))


def mark_seen(professor_url: str, announcements: list, seen: dict):
    existing = set(seen.get(professor_url, []))
    for a in announcements:
        existing.add(a["id"])
    seen[professor_url] = list(existing)


# ── Stats ─────────────────────────────────────────────────────────────────────

def load_stats() -> dict:
    data = _load_json("stats", STATS_FILE)
    data.setdefault("daily_counts", {})
    data.setdefault("last_check_time", None)
    return data


def save_stats(stats: dict):
    cutoff = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    stats["daily_counts"] = {
        k: v for k, v in stats.get("daily_counts", {}).items() if k >= cutoff
    }
    _save_json("stats", STATS_FILE, stats)


def increment_daily_count(stats: dict, n: int):
    today = datetime.date.today().isoformat()
    stats["daily_counts"][today] = stats["daily_counts"].get(today, 0) + n


# ── Professor name cache ──────────────────────────────────────────────────────

def load_professor_names() -> dict:
    return _load_json("professor_names", NAMES_FILE)


def save_professor_names(names: dict):
    _save_json("professor_names", NAMES_FILE, names)


# ── Status message ID ─────────────────────────────────────────────────────────

def load_status_message_id():
    data = _load_json("status_message", STATUS_MSG_FILE)
    return data.get("message_id") if data else None


def save_status_message_id(message_id: int):
    _save_json("status_message", STATUS_MSG_FILE, {"message_id": message_id})


# ── Search query (serverless webhook mode) ───────────────────────────────────

def store_search_query(chat_id, query: str):
    r = _get_redis()
    if r is not None:
        try:
            r.set(f"search:{chat_id}", query, ex=3600)
        except Exception as e:
            logger.error("Arama sorgusu kaydedilemedi: %s", e)


def load_search_query(chat_id) -> str:
    r = _get_redis()
    if r is not None:
        try:
            return r.get(f"search:{chat_id}") or ""
        except Exception:
            return ""
    return ""
