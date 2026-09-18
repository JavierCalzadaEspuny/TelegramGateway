"""Run the real TelegramListener smoke test with local configuration."""

from __future__ import annotations

import asyncio
import logging
import os

from telethon.errors import AuthKeyError, UnauthorizedError

from telegram_gateway import TelegramListener, TelegramMessage

from _common import connected_client, float_env, int_env, list_env

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
    channels = list_env("TELEGRAM_LISTENER_MONITOR_CHANNELS")
    if not channels:
        raise RuntimeError("TELEGRAM_LISTENER_MONITOR_CHANNELS cannot be empty")

    try:
        client = await connected_client()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return
    try:
        listener = TelegramListener(
            client=client,
            channels=channels,
            image_channels=list_env("TELEGRAM_LISTENER_IMAGE_CHANNELS"),
            translation_channels=list_env("TELEGRAM_LISTENER_TRANSLATION_CHANNELS"),
            translation_target_language=os.getenv(
                "TELEGRAM_LISTENER_TRANSLATION_TARGET_LANGUAGE", "en"
            ),
            translation_timeout=float_env(
                "TELEGRAM_LISTENER_TRANSLATION_TIMEOUT", 3
            ),
            translation_max_concurrency=int_env(
                "TELEGRAM_LISTENER_TRANSLATION_MAX_CONCURRENCY", 2
            ),
            queue_maxsize=int_env("TELEGRAM_LISTENER_QUEUE_MAXSIZE", 1000),
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
