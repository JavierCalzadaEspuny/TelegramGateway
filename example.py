"""End-to-end usage example for telegramlistener.

Run:
    uv run example.py

Prerequisites:
    Edit CHANNELS and TRANSLATION_CHANNELS below, copy .env.example to .env,
    fill in your Telegram credentials, then:
    uv sync --extra examples

The listener logs per-message processing, translation, and image-download times
at INFO. No averages or metric history are collected.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress

from dotenv import load_dotenv

from telegramlistener import (
    SessionError,
    SessionManager,
    TelegramListener,
    TelegramStreamedMessage,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Keep runtime configuration as real Python values. Change these lists directly
# when you want to monitor or translate a different set of channels.
CHANNELS: list[str] = [
    "testosint01",
    "me_observer_TG",
    "AjaNews",
    "almayadeen",
    "SabrenNewss",
    "UKMTOFeed",
]
IMAGE_CHANNELS: list[str] = ["testosint01", "UKMTOFeed"]
TRANSLATION_CHANNELS: list[str] = ["AjaNews", "almayadeen", "SabrenNewss"]
TRANSLATION_TARGET_LANGUAGE = "en"
TRANSLATION_TIMEOUT = 3.0
TRANSLATION_MAX_CONCURRENCY = 5
QUEUE_MAXSIZE = 1000

load_dotenv()


async def consume(queue: asyncio.Queue[TelegramStreamedMessage | None]) -> None:
    while True:
        msg = await queue.get()
        if msg is None:
            queue.task_done()
            break

        print("-" * 150)
        print(msg)
        print("-" * 150)
        print("")

        queue.task_done()


async def main() -> None:
    manager = SessionManager(
        api_id=int(os.environ["TELEGRAM_API_ID"]),
        api_hash=os.environ["TELEGRAM_API_HASH"],
        phone=os.environ["TELEGRAM_PHONE"],
        session_name=os.getenv("TELEGRAM_SESSION_NAME", "telegram"),
    )

    async with TelegramListener(
        session_manager=manager,
        channels=CHANNELS,
        image_channels=IMAGE_CHANNELS,
        translation_channels=TRANSLATION_CHANNELS,
        translation_target_language=TRANSLATION_TARGET_LANGUAGE,
        translation_timeout=TRANSLATION_TIMEOUT,
        translation_max_concurrency=TRANSLATION_MAX_CONCURRENCY,
        queue_maxsize=QUEUE_MAXSIZE,
    ) as listener:
        consumer = asyncio.create_task(consume(listener.queue))
        try:
            await listener.start()
        finally:
            consumer.cancel()
            with suppress(asyncio.CancelledError):
                await consumer


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SessionError as exc:
        logging.getLogger(__name__).error(
            "Telegram session unavailable: %s No automatic login was started.",
            exc,
        )
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Stopped.")
