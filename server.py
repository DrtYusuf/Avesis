import asyncio
import logging
import os
import sys

from flask import Flask, request, jsonify

import config
from main import check_professors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

CHECK_SECRET = os.getenv("CHECK_SECRET", "")


@app.route("/check", methods=["POST"])
def check():
    if CHECK_SECRET:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token != CHECK_SECRET:
            return jsonify({"error": "Unauthorized"}), 401

    first_run = not os.path.exists(config.SEEN_FILE)
    try:
        asyncio.run(check_professors(silent=first_run))
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error("Check failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logger.info("AVESİS Tracker server başlatılıyor (port %d)...", port)
    app.run(host="0.0.0.0", port=port)
