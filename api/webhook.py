"""Vercel serverless function — Telegram webhook handler."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from telegram import Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    MessageHandler, filters,
)

import config
from bot import set_bot
from main import cmd_kontrol, cmd_durum
from selection import cmd_sec, on_callback
import main as _main

# ── Singleton Application (reused across warm invocations) ───────────────────
_app: Application | None = None
_loop = asyncio.new_event_loop()


async def _init_app() -> Application:
    _main._check_lock = asyncio.Lock()

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .updater(None)
        .build()
    )
    app.add_handler(CommandHandler("kontrol", cmd_kontrol))
    app.add_handler(CommandHandler("durum", cmd_durum))
    app.add_handler(CommandHandler(["sec", "secim"], cmd_sec))
    app.add_handler(
        MessageHandler(
            filters.Regex(r"(?i)^/se[çc](?:im)?(?:@\w+)?(?:\s|$)"), cmd_sec
        )
    )
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^s:"))
    await app.initialize()
    set_bot(app.bot)
    return app


def _get_app() -> Application:
    global _app
    if _app is None:
        asyncio.set_event_loop(_loop)
        _app = _loop.run_until_complete(_init_app())
    return _app


# ── Vercel handler ───────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length))

            app = _get_app()
            update = Update.de_json(body, app.bot)
            _loop.run_until_complete(app.process_update(update))

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            logger.error("Webhook hatasi: %s", e, exc_info=True)
            self.send_response(200)  # Telegram'a 200 donmezse tekrar dener
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default stderr logging."""
        pass
