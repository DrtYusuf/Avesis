import hashlib
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


def _make_id(professor_url: str, title: str, date: str) -> str:
    """Create a stable unique ID for an announcement."""
    raw = f"{professor_url}|{title}|{date}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _extract_professor_name(soup: BeautifulSoup) -> str:
    """Try several common selectors to find the professor's display name."""
    candidates = [
        soup.select_one("h1.profile-name"),
        soup.select_one("h1.kisi-adi"),
        soup.select_one("h1"),
        soup.select_one(".profile-header h2"),
        soup.select_one(".kisisel-bilgi h2"),
    ]
    for tag in candidates:
        if tag and tag.get_text(strip=True):
            return tag.get_text(strip=True)
    return "Bilinmeyen Hoca"


# ---------------------------------------------------------------------------
# YTÜ AVESİS-specific parser
# URL pattern : https://avesis.yildiz.edu.tr/{username}
# Announcements live at  : /dokumanlar  (not /duyurular)
# HTML structure:
#   <h4 class="with-underline">Duyuru <span class="badge">N</span></h4>
#   <div class="ac-item">
#     <div class="item-head">
#       <div class="row">
#         <div class="col-md-8"><i></i><span>TITLE</span></div>
#         <div class="col-md-2"><span class="badge">Duyuru</span></div>
#         <div class="col-md-2"><span>DATE</span></div>
#       </div>
#     </div>
#     <div class="item-body"><p>CONTENT</p></div>
#   </div>
# ---------------------------------------------------------------------------

def _is_ytu(url: str) -> bool:
    return "avesis.yildiz.edu.tr" in url or "avesis.ytu.edu.tr" in url


def _parse_ytu_dokumanlar(soup: BeautifulSoup, profile_url: str) -> list:
    """Parse announcements from the YTÜ /dokumanlar page."""
    announcements = []

    # Find the <h4> whose text starts with "Duyuru"
    duyuru_heading = None
    for h4 in soup.find_all("h4"):
        if re.search(r"duyuru", h4.get_text(), re.I):
            duyuru_heading = h4
            break

    if not duyuru_heading:
        logger.debug("YTÜ dokumanlar: 'Duyuru' heading not found")
        return []

    # Collect all .ac-item siblings that follow the heading until the next h4
    siblings = []
    for sibling in duyuru_heading.find_next_siblings():
        if sibling.name == "h4":
            break
        if "ac-item" in sibling.get("class", []):
            siblings.append(sibling)

    logger.debug("YTÜ dokumanlar: found %d .ac-item elements under Duyuru heading", len(siblings))

    for item in siblings:
        # Title: first <span> inside col-md-8 (after the icon)
        title_col = item.select_one(".col-md-8, .col-xs-3")
        title = ""
        if title_col:
            span = title_col.find("span")
            title = span.get_text(strip=True) if span else title_col.get_text(strip=True)

        if not title:
            continue

        # Date: last <span> in the row (col-md-2 with date)
        date_col = item.select(".col-md-2, .col-xs-5")
        date = ""
        if date_col:
            # The last col usually holds the date (not the badge)
            for col in reversed(date_col):
                text = col.get_text(strip=True)
                if re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}", text):
                    date = text
                    break

        # Content: item-body text
        body = item.select_one(".item-body")
        content = body.get_text(separator=" ", strip=True) if body else ""

        announcement_id = _make_id(profile_url, title, date)
        announcements.append({
            "id": announcement_id,
            "title": title,
            "date": date,
            "content": content[:500],
            "url": profile_url,
        })

    return announcements


# ---------------------------------------------------------------------------
# Generic parser (fallback for other universities)
# ---------------------------------------------------------------------------

def _find_announcements_section(soup: BeautifulSoup):
    """Return the container element that holds announcements, or None."""
    # Strategy 1: element with id containing "duyuru"
    for el in soup.find_all(id=re.compile(r"duyuru", re.I)):
        return el

    # Strategy 2: heading containing "Duyuru" → return its parent container
    for heading in soup.find_all(re.compile(r"h[1-6]"), string=re.compile(r"duyuru", re.I)):
        parent = heading.find_parent(["section", "div", "article"])
        if parent:
            return parent

    # Strategy 3: tab link "#duyuru…" → follow href to panel
    for a in soup.find_all("a", string=re.compile(r"duyuru", re.I)):
        href = a.get("href", "")
        if href.startswith("#"):
            target = soup.find(id=href.lstrip("#"))
            if target:
                return target

    # Strategy 4: element with class containing "duyuru"
    for el in soup.find_all(class_=re.compile(r"duyuru", re.I)):
        return el

    return None


def _parse_announcements_generic(section, professor_url: str) -> list:
    """Extract individual announcements from a generic announcements section."""
    announcements = []

    items = (
        section.select(".ac-item")
        or section.select("li")
        or section.select(".duyuru-item")
        or section.select(".card")
        or section.select("article")
        or section.select("tr")
    )

    if not items:
        text = section.get_text(separator=" ", strip=True)
        if len(text) > 20:
            announcement_id = _make_id(professor_url, text[:80], "")
            announcements.append({
                "id": announcement_id,
                "title": text[:80],
                "date": "",
                "content": text[:500],
                "url": professor_url,
            })
        return announcements

    for item in items:
        date_tag = (
            item.find("time")
            or item.find(class_=re.compile(r"tarih|date", re.I))
        )
        date = date_tag.get_text(strip=True) if date_tag else ""

        item_clone = BeautifulSoup(str(item), "html.parser")
        for dt in item_clone.find_all(class_=re.compile(r"tarih|date", re.I)):
            dt.decompose()
        for dt in item_clone.find_all("time"):
            dt.decompose()

        title_tag = (
            item_clone.find(re.compile(r"h[1-6]"))
            or item_clone.find("a")
            or item_clone.find("strong")
        )
        title = title_tag.get_text(strip=True) if title_tag else item_clone.get_text(strip=True)[:120]

        if not title:
            continue

        content = item_clone.get_text(separator=" ", strip=True)
        announcement_id = _make_id(professor_url, title, date)
        announcements.append({
            "id": announcement_id,
            "title": title,
            "date": date,
            "content": content[:500],
            "url": professor_url,
        })

    return announcements


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_professor(profile_url: str) -> dict:
    """Scrape a single AVESİS professor profile page.

    Returns:
        {
            "professor_name": str,
            "profile_url": str,
            "announcements": list[dict],
            "error": str | None,
        }
    """
    result = {
        "professor_name": "",
        "profile_url": profile_url,
        "announcements": [],
        "error": None,
    }

    base_url = profile_url.rstrip("/")
    parsed = urlparse(base_url)

    # Build list of URLs to try
    if _is_ytu(profile_url):
        # YTÜ: announcements are on the /dokumanlar sub-page
        urls_to_try = [base_url + "/dokumanlar"]
        # Also fetch the base profile for the professor name
        name_url = base_url
    else:
        # Generic: try /duyurular first, then base URL
        urls_to_try = []
        if not parsed.path.rstrip("/").endswith("duyurular"):
            urls_to_try.append(base_url + "/duyurular")
        urls_to_try.append(base_url)
        name_url = base_url

    # Fetch professor name from the base profile page
    try:
        name_resp = requests.get(name_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        name_resp.raise_for_status()
        name_soup = BeautifulSoup(name_resp.text, "html.parser")
        result["professor_name"] = _extract_professor_name(name_soup)
    except requests.RequestException as e:
        logger.warning("Could not fetch profile for name: %s", e)
        result["professor_name"] = parsed.path.strip("/").split("/")[-1]

    # Fetch and parse announcements
    for url in urls_to_try:
        try:
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Network error fetching %s: %s", url, e)
            result["error"] = str(e)
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        if _is_ytu(profile_url):
            announcements = _parse_ytu_dokumanlar(soup, profile_url)
        else:
            section = _find_announcements_section(soup)
            announcements = _parse_announcements_generic(section, profile_url) if section else []

        if announcements:
            result["announcements"] = announcements
            result["error"] = None
            logger.info(
                "Found %d announcement(s) for %s",
                len(announcements),
                result["professor_name"],
            )
            return result

        logger.debug("No announcements found at %s", url)

    if not result["announcements"] and not result["error"]:
        result["error"] = "Duyurular bölümü bulunamadı."

    return result
