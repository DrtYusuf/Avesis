"""AVESİS akademik personel dizini.

/seç komutunun "hoca ekle" listesini besler. AVESİS'in araştırmacı arama ekranı
arka planda bir Elasticsearch proxy'sine (/proxy/search/_search) sorgu atar;
burada aynı uçtan yalnızca config.FACULTY_NAME fakültesindeki araştırmacıları
çekiyoruz. Böylece listeye eklenebilecek hocalar o fakülteyle sınırlı kalıyor.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import unicodedata

import requests

import config
from config import HEADERS, REQUEST_TIMEOUT, DATA_DIR

logger = logging.getLogger(__name__)

FACULTY_CACHE_FILE = os.path.join(DATA_DIR, "faculty_cache.json")

SEARCH_ENDPOINT = config.AVESIS_BASE_URL + "/proxy/search/_search"
RESEARCHER_TYPE = "Araştırmacılar"
MAX_RESULTS = 1000
UNKNOWN_DEPARTMENT = "Diğer"


class DirectoryError(Exception):
    """Fakülte listesi ne ağdan ne de önbellekten alınabildiğinde fırlatılır."""


# ── Turkish-aware text folding ────────────────────────────────────────────────

_TR_LOWER = str.maketrans({
    "I": "ı", "İ": "i", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç",
})


def fold(text: str) -> str:
    """Lowercase Turkish-correctly and strip accents, for forgiving name search."""
    lowered = (text or "").translate(_TR_LOWER).lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# ── Profile helpers ───────────────────────────────────────────────────────────

def profile_url(alias: str) -> str:
    return f"{config.AVESIS_BASE_URL}/{alias.strip('/')}"


def _first(value, default: str = "") -> str:
    """AVESİS returns some fields as lists; take the first meaningful entry."""
    if isinstance(value, list):
        for item in value:
            if item and str(item).strip() not in ("-", ""):
                return str(item).strip()
        return default
    if value and str(value).strip() not in ("-", ""):
        return str(value).strip()
    return default


# ── Remote fetch ──────────────────────────────────────────────────────────────

def _fetch_from_avesis() -> list[dict]:
    """Query the AVESİS search proxy for every researcher in the target faculty."""
    body = {
        "size": MAX_RESULTS,
        "query": {
            "bool": {
                "must": [
                    {"term": {"type_primary.keyword": RESEARCHER_TYPE}},
                    {"term": {"facultyname_primary.keyword": config.FACULTY_NAME}},
                ]
            }
        },
        "_source": [
            "profilepagealias",
            "fullnamewithtitle_primary",
            "title_primary",
            "title_order",
            "departmentname_primary",
            "name",
            "surname",
        ],
    }

    response = requests.post(
        SEARCH_ENDPOINT,
        headers={**HEADERS, "Content-Type": "application/json"},
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout=REQUEST_TIMEOUT * 2,
    )
    response.raise_for_status()
    hits = response.json().get("hits", {}).get("hits", [])

    professors = []
    for hit in hits:
        source = hit.get("_source", {})
        alias = _first(source.get("profilepagealias"))
        if not alias:
            continue  # herkese açık profili yok
        full_name = " ".join(
            p for p in (_first(source.get("name")), _first(source.get("surname"))) if p
        )
        professors.append({
            "alias": alias,
            "url": profile_url(alias),
            "name": full_name or alias,
            "title": _first(source.get("title_primary")),
            "display": _first(source.get("fullnamewithtitle_primary"), full_name or alias),
            "department": _first(source.get("departmentname_primary"), UNKNOWN_DEPARTMENT),
            "title_order": source.get("title_order") or 99,
        })

    professors.sort(key=lambda p: (p["department"], p["title_order"], fold(p["name"])))
    logger.info("AVESİS dizini alındı: %d kişi (%s)", len(professors), config.FACULTY_NAME)
    return professors


# ── Cache ─────────────────────────────────────────────────────────────────────

def _read_cache() -> dict | None:
    if not os.path.exists(FACULTY_CACHE_FILE):
        return None
    try:
        with open(FACULTY_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to load faculty_cache.json: %s", e)
        return None

    # Fakülte adı değiştiyse eski önbellek geçersizdir.
    if cache.get("faculty") != config.FACULTY_NAME or not cache.get("professors"):
        return None
    return cache


def _write_cache(professors: list[dict]):
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(FACULTY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "faculty": config.FACULTY_NAME,
                    "fetched_at": datetime.datetime.now().isoformat(),
                    "professors": professors,
                },
                f, ensure_ascii=False, indent=2,
            )
    except IOError as e:
        logger.error("Failed to save faculty_cache.json: %s", e)


def _is_fresh(cache: dict) -> bool:
    try:
        fetched = datetime.datetime.fromisoformat(cache["fetched_at"])
    except (KeyError, ValueError):
        return False
    age_h = (datetime.datetime.now() - fetched).total_seconds() / 3600
    return age_h < config.FACULTY_CACHE_TTL_HOURS


def load_faculty(force_refresh: bool = False) -> list[dict]:
    """Return the faculty roster, refreshing the on-disk cache when it goes stale.

    Falls back to a stale cache if AVESİS is unreachable; raises DirectoryError
    only when there is nothing usable at all.
    """
    cache = _read_cache()
    if cache and not force_refresh and _is_fresh(cache):
        return cache["professors"]

    try:
        professors = _fetch_from_avesis()
        if professors:
            _write_cache(professors)
            return professors
        logger.warning("AVESİS dizini boş döndü (%s)", config.FACULTY_NAME)
    except (requests.RequestException, ValueError) as e:
        logger.warning("AVESİS dizini alınamadı: %s", e)

    if cache:
        logger.info("Eski önbellek kullanılıyor (%d kişi)", len(cache["professors"]))
        return cache["professors"]

    raise DirectoryError(
        f"{config.FACULTY_NAME} personel listesi alınamadı. "
        "AVESİS'e ulaşılamıyor olabilir, birazdan tekrar deneyin."
    )


def cache_age_text() -> str:
    """Timestamp of the cached roster, for the /seç footer."""
    cache = _read_cache()
    if not cache:
        return "bilinmiyor"
    try:
        fetched = datetime.datetime.fromisoformat(cache["fetched_at"])
    except (KeyError, ValueError):
        return "bilinmiyor"
    return fetched.strftime("%d.%m.%Y %H:%M")


# ── Queries over the roster ───────────────────────────────────────────────────

def departments(professors: list[dict]) -> list[tuple[str, int]]:
    """Return (department, member count) pairs, largest first."""
    counts: dict[str, int] = {}
    for p in professors:
        counts[p["department"]] = counts.get(p["department"], 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], fold(kv[0])))


def in_department(professors: list[dict], department: str) -> list[dict]:
    return [p for p in professors if p["department"] == department]


def search(professors: list[dict], query: str) -> list[dict]:
    """Match a query against name, title, department and profile alias."""
    needle = fold(query).strip()
    if not needle:
        return []
    matches = []
    for p in professors:
        haystack = fold(p["display"] + " " + p["department"] + " " + p["alias"])
        if needle in haystack:
            matches.append(p)
    return matches


def find_by_alias(professors: list[dict], alias: str) -> dict | None:
    for p in professors:
        if p["alias"].lower() == alias.lower():
            return p
    return None


def find_by_url(professors: list[dict], url: str) -> dict | None:
    target = url.strip().rstrip("/").lower()
    for p in professors:
        if p["url"].lower() == target:
            return p
    return None
