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
from main import check_professors

first_run = not os.path.exists(config.SEEN_FILE)
asyncio.run(check_professors(silent=first_run))
