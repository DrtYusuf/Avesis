"""/seç — takip edilen hocaları inline butonlarla yönetme ekranı.

Ekranlar:
  • Ana menü      → takip listesi özeti ve giriş noktaları
  • Takip Listem  → şu an takip edilen hocalar; dokununca takipten çıkar
  • Hoca Ekle     → fakülte bölümleri → bölümdeki hocalar; dokununca takibe alır
  • Arama         → "/sec kızılay" ile isme göre süzülmüş liste

Eklenebilecek hocalar directory.load_faculty() ile sınırlıdır; o da yalnızca
config.FACULTY_NAME (varsayılan: Elektrik-Elektronik Fakültesi) kadrosunu döner.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import config
import directory
from bot import escape_md
from storage import (
    add_tracked,
    is_tracked,
    load_professor_names,
    load_tracked,
    remove_tracked,
    save_professor_names,
    store_search_query,
    load_search_query,
    _get_redis,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 8          # sayfa başına hoca butonu
LABEL_LIMIT = 40       # buton metni kırpma sınırı
CB = "s"               # callback_data öneki (64 bayt sınırı yüzünden kısa)

QUERY_KEY = "sec_query"


# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _authorized(update: Update) -> bool:
    """Takip listesini yalnızca botun bildirim gönderdiği sohbet değiştirebilir."""
    if not config.TELEGRAM_CHAT_ID:
        return True
    chat = update.effective_chat
    return chat is not None and str(chat.id) == str(config.TELEGRAM_CHAT_ID)


def _url_key(url: str) -> str:
    """Kısa, kararlı bir callback anahtarı (URL'ler 64 baytlık sınıra sığmaz)."""
    return hashlib.sha1(url.strip().rstrip("/").lower().encode("utf-8")).hexdigest()[:12]


def _clip(text: str, limit: int = LABEL_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _display_name(url: str, names: dict, faculty: list[dict]) -> str:
    """Bir profil URL'si için gösterilecek ad: dizin → ad önbelleği → URL kuyruğu."""
    entry = directory.find_by_url(faculty, url)
    if entry:
        return entry["display"]
    cached = names.get(url) or names.get(url.rstrip("/"))
    if cached:
        return cached
    return url.rstrip("/").split("/")[-1]


def _page_slice(items: list, page: int) -> tuple[list, int, int]:
    """Sayfayı sınırlar içine çekip (dilim, düzeltilmiş sayfa, toplam sayfa) döner."""
    total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    return items[start:start + PAGE_SIZE], page, total_pages


def _nav_row(prefix: str, page: int, total_pages: int) -> list[InlineKeyboardButton]:
    """◀️ 2/7 ▶️ satırı. prefix, sayfa numarasıyla tamamlanacak callback önekidir."""
    if total_pages <= 1:
        return []
    prev_page = page - 1 if page > 0 else total_pages - 1
    next_page = page + 1 if page < total_pages - 1 else 0
    return [
        InlineKeyboardButton("◀️", callback_data=f"{prefix}{prev_page}"),
        InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data=f"{CB}:n"),
        InlineKeyboardButton("▶️", callback_data=f"{prefix}{next_page}"),
    ]


async def _faculty(force_refresh: bool = False) -> list[dict]:
    """Fakülte kadrosunu olay döngüsünü bloklamadan getir."""
    return await asyncio.to_thread(directory.load_faculty, force_refresh)


# ── Ekranlar ──────────────────────────────────────────────────────────────────

def _render_home(tracked: list[str], faculty: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🎛 *Hoca Seçimi*\n\n"
        f"👨‍🏫 Takip edilen: *{len(tracked)}* hoca\n"
        f"🏛 Eklenebilir kadro: {escape_md(config.FACULTY_NAME)} "
        f"\\(*{len(faculty)}* kişi\\)\n\n"
        "🔎 İsimle aramak için: `/sec kizilay`"
    )
    keyboard = [
        [InlineKeyboardButton(f"📋 Takip Listem ({len(tracked)})", callback_data=f"{CB}:m:0")],
        [InlineKeyboardButton("➕ Hoca Ekle", callback_data=f"{CB}:D")],
        [
            InlineKeyboardButton("♻️ Kadroyu Yenile", callback_data=f"{CB}:R"),
            InlineKeyboardButton("✖️ Kapat", callback_data=f"{CB}:x"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _render_my(page: int, tracked: list[str], faculty: list[dict]):
    names = load_professor_names()
    if not tracked:
        text = (
            "📋 *Takip Listem*\n\n"
            "Şu anda takip edilen hoca yok\\.\n"
            "➕ *Hoca Ekle* ile başlayabilirsiniz\\."
        )
        return text, InlineKeyboardMarkup(
            [[InlineKeyboardButton("➕ Hoca Ekle", callback_data=f"{CB}:D")],
             [InlineKeyboardButton("🔙 Geri", callback_data=f"{CB}:h")]]
        )

    rows, page, total_pages = _page_slice(tracked, page)
    text = (
        f"📋 *Takip Listem* — *{len(tracked)}* hoca\n\n"
        "Takipten çıkarmak için hocaya dokunun\\."
    )
    keyboard = [
        [InlineKeyboardButton(
            f"❌ {_clip(_display_name(url, names, faculty))}",
            callback_data=f"{CB}:r:{_url_key(url)}:{page}",
        )]
        for url in rows
    ]
    nav = _nav_row(f"{CB}:m:", page, total_pages)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 Geri", callback_data=f"{CB}:h")])
    return text, InlineKeyboardMarkup(keyboard)


def _render_departments(tracked: list[str], faculty: list[dict]):
    tracked_set = {u.rstrip("/").lower() for u in tracked}
    deps = directory.departments(faculty)
    text = (
        "➕ *Hoca Ekle*\n\n"
        f"🏛 {escape_md(config.FACULTY_NAME)}\n"
        "Bir bölüm seçin\\. Parantez içinde *takip edilen / toplam* gösterilir\\."
    )
    keyboard = []
    for index, (dep, total) in enumerate(deps):
        following = sum(
            1 for p in faculty
            if p["department"] == dep and p["url"].rstrip("/").lower() in tracked_set
        )
        keyboard.append([InlineKeyboardButton(
            f"{_clip(dep, 30)} ({following}/{total})",
            callback_data=f"{CB}:d:{index}:0",
        )])
    keyboard.append([InlineKeyboardButton("🔙 Geri", callback_data=f"{CB}:h")])
    return text, InlineKeyboardMarkup(keyboard)


def _professor_rows(people: list[dict], tracked: list[str], toggle_prefix: str):
    """Her hoca için ✅/➕ işaretli bir buton satırı üret."""
    tracked_set = {u.rstrip("/").lower() for u in tracked}
    rows = []
    for p in people:
        mark = "✅" if p["url"].rstrip("/").lower() in tracked_set else "➕"
        rows.append([InlineKeyboardButton(
            f"{mark} {_clip(p['display'])}",
            callback_data=f"{toggle_prefix}{p['alias']}",
        )])
    return rows


def _render_department(dep_index: int, page: int, tracked: list[str], faculty: list[dict]):
    deps = directory.departments(faculty)
    if not deps:
        return _render_departments(tracked, faculty)
    dep_index = max(0, min(dep_index, len(deps) - 1))
    dep_name, dep_total = deps[dep_index]

    people = directory.in_department(faculty, dep_name)
    rows, page, total_pages = _page_slice(people, page)

    text = (
        f"🏫 *{escape_md(dep_name)}* — *{dep_total}* kişi\n\n"
        "✅ takip ediliyor · ➕ takibe al\n"
        "Değiştirmek için hocaya dokunun\\."
    )
    keyboard = _professor_rows(rows, tracked, f"{CB}:t:{dep_index}:{page}:")
    nav = _nav_row(f"{CB}:d:{dep_index}:", page, total_pages)
    if nav:
        keyboard.append(nav)
    keyboard.append([
        InlineKeyboardButton("🔙 Bölümler", callback_data=f"{CB}:D"),
        InlineKeyboardButton("🏠 Ana Menü", callback_data=f"{CB}:h"),
    ])
    return text, InlineKeyboardMarkup(keyboard)


def _render_search(query: str, page: int, tracked: list[str], faculty: list[dict]):
    matches = directory.search(faculty, query)
    if not matches:
        text = (
            f"🔎 *Arama:* {escape_md(query)}\n\n"
            f"{escape_md(config.FACULTY_NAME)} kadrosunda eşleşen hoca bulunamadı\\."
        )
        return text, InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Ana Menü", callback_data=f"{CB}:h")]]
        )

    rows, page, total_pages = _page_slice(matches, page)
    text = (
        f"🔎 *Arama:* {escape_md(query)} — *{len(matches)}* sonuç\n\n"
        "✅ takip ediliyor · ➕ takibe al"
    )
    keyboard = _professor_rows(rows, tracked, f"{CB}:q:{page}:")
    nav = _nav_row(f"{CB}:s:", page, total_pages)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🏠 Ana Menü", callback_data=f"{CB}:h")])
    return text, InlineKeyboardMarkup(keyboard)


# ── Komut ─────────────────────────────────────────────────────────────────────

def _extract_query(message_text: str) -> str:
    """"/sec kizilay" → "kizilay". Komut adı ASCII olmayabilir, elle ayırıyoruz."""
    parts = (message_text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def cmd_sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/seç — takip edilen hocaları seç. İsteğe bağlı: /seç <isim> ile ara."""
    message = update.effective_message
    if message is None:
        return
    if not _authorized(update):
        await message.reply_text("⛔ Bu komutu kullanma yetkiniz yok.")
        return

    try:
        faculty = await _faculty()
    except directory.DirectoryError as e:
        await message.reply_text(f"⚠️ {e}")
        return

    tracked = load_tracked()
    query = _extract_query(message.text)
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if query:
        if _get_redis() is not None:
            store_search_query(chat_id, query)
        else:
            context.user_data[QUERY_KEY] = query
        text, keyboard = _render_search(query, 0, tracked, faculty)
    else:
        if _get_redis() is not None:
            store_search_query(chat_id, "")
        else:
            context.user_data.pop(QUERY_KEY, None)
        text, keyboard = _render_home(tracked, faculty)

    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)


# ── Callback yönlendirici ─────────────────────────────────────────────────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/seç ekranlarındaki tüm buton dokunuşlarını karşılar."""
    query = update.callback_query
    if query is None:
        return

    if not _authorized(update):
        await query.answer("⛔ Yetkiniz yok.", show_alert=True)
        return

    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else "h"

    if action == "n":  # sayfa göstergesi — tıklanabilir ama işlevsiz
        await query.answer()
        return

    if action == "x":
        await query.answer("Kapatıldı")
        try:
            await query.message.delete()
        except TelegramError:
            pass
        return

    try:
        faculty = await _faculty(force_refresh=(action == "R"))
    except directory.DirectoryError as e:
        await query.answer(str(e), show_alert=True)
        return

    toast = None

    # ── Durum değiştiren işlemler ────────────────────────────────────────────
    if action == "r":                                   # takipten çıkar
        target_key = parts[2] if len(parts) > 2 else ""
        removed_url = next(
            (u for u in load_tracked() if _url_key(u) == target_key), None
        )
        if removed_url is None:
            toast = "Bu hoca zaten listede değil."
        else:
            names = load_professor_names()
            label = _display_name(removed_url, names, faculty)
            remove_tracked(removed_url)
            logger.info("Takipten çıkarıldı: %s", removed_url)
            toast = f"❌ Takipten çıkarıldı: {label}"

    elif action in ("t", "q"):                          # bölüm / arama listesinde geçiş
        alias = parts[-1]
        # Kısıt burada uygulanıyor: yalnızca fakülte kadrosundaki takma adlar geçerli.
        person = directory.find_by_alias(faculty, alias)
        if person is None:
            toast = f"Bu hoca {config.FACULTY_NAME} listesinde yok."
        elif is_tracked(person["url"]):
            remove_tracked(person["url"])
            logger.info("Takipten çıkarıldı: %s", person["url"])
            toast = f"❌ Takipten çıkarıldı: {person['display']}"
        else:
            add_tracked(person["url"])
            names = load_professor_names()
            names[person["url"]] = person["display"]
            save_professor_names(names)
            logger.info("Takibe alındı: %s", person["url"])
            toast = f"✅ Takibe alındı: {person['display']}"

    elif action == "R":
        toast = f"♻️ Kadro güncellendi: {len(faculty)} kişi"

    # ── Ekranı yeniden çiz ───────────────────────────────────────────────────
    tracked = load_tracked()

    if action in ("m", "r"):
        page = _int_at(parts, 2 if action == "m" else 3)
        text, keyboard = _render_my(page, tracked, faculty)
    elif action == "D":
        text, keyboard = _render_departments(tracked, faculty)
    elif action == "d":
        text, keyboard = _render_department(_int_at(parts, 2), _int_at(parts, 3), tracked, faculty)
    elif action == "t":
        text, keyboard = _render_department(_int_at(parts, 2), _int_at(parts, 3), tracked, faculty)
    elif action in ("s", "q"):
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if _get_redis() is not None:
            search_query = load_search_query(chat_id)
        else:
            search_query = context.user_data.get(QUERY_KEY, "")
        if not search_query:
            toast = toast or "Arama geçersiz, ana menüye dönüldü."
            text, keyboard = _render_home(tracked, faculty)
        else:
            text, keyboard = _render_search(search_query, _int_at(parts, 2), tracked, faculty)
    else:  # "h", "R" ve tanınmayan her şey
        text, keyboard = _render_home(tracked, faculty)

    await query.answer(toast or "")
    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard
        )
    except TelegramError as e:
        if "message is not modified" not in str(e).lower():
            logger.error("/seç ekranı güncellenemedi: %s", e)


def _int_at(parts: list[str], index: int, default: int = 0) -> int:
    try:
        return int(parts[index])
    except (IndexError, ValueError):
        return default
