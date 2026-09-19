"""Run the real TelegramListener smoke test with local configuration."""

from __future__ import annotations

import asyncio
import logging

from telethon.errors import AuthKeyError, UnauthorizedError

from telegram_gateway import TelegramListener, TelegramMessage

from _common import connected_client

CHANNELS: list[str] = ["testosint01"]
IMAGE_CHANNELS: list[str] = ["testosint01"]
TRANSLATION_CHANNELS: list[str] = ["testosint01"]
TRANSLATION_TARGET_LANGUAGE = "en"
TRANSLATION_TIMEOUT = 3.0
TRANSLATION_MAX_CONCURRENCY = 2
QUEUE_MAXSIZE = 1000

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def consume(queue: asyncio.Queue[TelegramMessage | None]) -> None:
    while True:
        message = await queue.get()
        try:
            if message is None:
                break
            print(message)
        finally:
            queue.task_done()


async def main() -> None:
    if not CHANNELS:
        raise RuntimeError("Set CHANNELS at the top of smoke/listener.py")

    try:
        client = await connected_client()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return
    try:
        listener = TelegramListener(
            client=client,
            channels=CHANNELS,
            image_channels=IMAGE_CHANNELS,
            translation_channels=TRANSLATION_CHANNELS,
            translation_target_language=TRANSLATION_TARGET_LANGUAGE,
            translation_timeout=TRANSLATION_TIMEOUT,
            translation_max_concurrency=TRANSLATION_MAX_CONCURRENCY,
            queue_maxsize=QUEUE_MAXSIZE,
        )
        consumer = asyncio.create_task(consume(listener.queue))
        try:
            await listener.start()
        finally:
            await consumer
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (AuthKeyError, UnauthorizedError) as exc:
        logger.error(
            "Telegram session unavailable: %s No interactive login was started.",
            exc,
        )
    except KeyboardInterrupt:
        logger.info("Stopped.")
