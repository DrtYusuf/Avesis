"""Vercel serverless function — cron-triggered professor check."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

import config
from bot import set_bot
from telegram import Bot
import main as _main

_loop = asyncio.new_event_loop()
_initialized = False


async def _ensure_init():
    global _initialized
    if not _initialized:
        _initialized = True
        _main._check_lock = asyncio.Lock()
        set_bot(Bot(token=config.TELEGRAM_BOT_TOKEN))


async def _run_check():
    await _ensure_init()

    first_run = not bool(_main.load_seen())
    total = await _main.check_professors(silent=first_run)
    return total


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            asyncio.set_event_loop(_loop)
            total = _loop.run_until_complete(_run_check())

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "new": total}).encode())
        except Exception as e:
            logger.error("Check hatasi: %s", e, exc_info=True)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())

    def log_message(self, format, *args):
        pass
