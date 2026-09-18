"""Create or refresh the local Telethon session for the smoke test."""

from __future__ import annotations

import asyncio
import logging

from _common import new_client, required_env, session_stem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    path = session_stem()
    client = new_client()
    try:
        await client.start(phone=required_env("TELEGRAM_PHONE"))
        logger.info(
            "Telegram session ready at %s", path.with_suffix(".session")
        )
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
