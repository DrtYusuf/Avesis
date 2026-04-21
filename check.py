import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

import os
import config
import main

first_run = not os.path.exists(config.SEEN_FILE)


async def run():
    main._check_lock = asyncio.Lock()
    await main.check_professors(silent=first_run)


asyncio.run(run())
