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
from storage import _load_json, _save_json

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

PAGE_SIZE_ES = 50  # AVESİS proxy'si büyük size değerlerini kırpabilir


def _fetch_faculty(faculty_name: str) -> list[dict]:
    """Tek bir fakültenin araştırmacılarını sayfalayarak çeker."""
    query = {
        "bool": {
            "must": [
                {"term": {"type_primary.keyword": RESEARCHER_TYPE}},
                {"term": {"facultyname_primary.keyword": faculty_name}},
            ]
        }
    }
    source_fields = [
        "profilepagealias",
        "fullnamewithtitle_primary",
        "title_primary",
        "title_order",
        "departmentname_primary",
        "facultyname_primary",
        "name",
        "surname",
    ]

    all_hits = []
    offset = 0
    while offset < MAX_RESULTS:
        body = {
            "from": offset,
            "size": PAGE_SIZE_ES,
            "query": query,
            "_source": source_fields,
        }
        response = requests.post(
            SEARCH_ENDPOINT,
            headers={**HEADERS, "Content-Type": "application/json"},
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=REQUEST_TIMEOUT * 2,
        )
        response.raise_for_status()
        data = response.json().get("hits", {})
        hits = data.get("hits", [])
        all_hits.extend(hits)

        total = data.get("total", 0)
        if isinstance(total, dict):
            total = total.get("value", 0)

        offset += PAGE_SIZE_ES
        if offset >= total or not hits:
            break

    return all_hits


def _fetch_from_avesis() -> list[dict]:
    """Query the AVESİS search proxy for every researcher in the target faculties.

    Proxy, size parametresini sınırlayabileceğinden sonuçları sayfalayarak çeker.
    """
    all_hits = []
    for faculty_name in config.FACULTY_NAMES:
        hits = _fetch_faculty(faculty_name)
        all_hits.extend(hits)
        logger.info("AVESİS: %s → %d kayıt", faculty_name, len(hits))

    seen_aliases = set()
    professors = []
    for hit in all_hits:
        source = hit.get("_source", {})
        alias = _first(source.get("profilepagealias"))
        if not alias or alias in seen_aliases:
            continue
        seen_aliases.add(alias)
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
            "faculty": _first(source.get("facultyname_primary"), UNKNOWN_DEPARTMENT),
            "title_order": source.get("title_order") or 99,
        })

    professors.sort(key=lambda p: (p["faculty"], p["department"], p["title_order"], fold(p["name"])))
    faculty_label = ", ".join(config.FACULTY_NAMES)
    logger.info("AVESİS dizini alındı: %d kişi (%s)", len(professors), faculty_label)
    return professors


# ── Cache ─────────────────────────────────────────────────────────────────────

def _cache_key() -> str:
    """Hangi fakülteler için önbellek oluşturulduğunu tanımlayan anahtar."""
    return ",".join(sorted(config.FACULTY_NAMES))


def _read_cache() -> dict | None:
    cache = _load_json("faculty_cache", FACULTY_CACHE_FILE)
    if not cache or cache.get("faculty") != _cache_key() or not cache.get("professors"):
        return None
    return cache


def _write_cache(professors: list[dict]):
    _save_json("faculty_cache", FACULTY_CACHE_FILE, {
        "faculty": _cache_key(),
        "fetched_at": datetime.datetime.now().isoformat(),
        "professors": professors,
    })


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
        faculty_label = ", ".join(config.FACULTY_NAMES)
        logger.warning("AVESİS dizini boş döndü (%s)", faculty_label)
    except (requests.RequestException, ValueError) as e:
        logger.warning("AVESİS dizini alınamadı: %s", e)

    if cache:
        logger.info("Eski önbellek kullanılıyor (%d kişi)", len(cache["professors"]))
        return cache["professors"]

    raise DirectoryError(
        "Personel listesi alınamadı. "
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
