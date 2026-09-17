"""Run the real TelegramListener smoke test with local configuration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import AuthKeyError, UnauthorizedError

from telegramlistener import TelegramListener, TelegramStreamedMessage

SMOKE_DIR = Path(__file__).resolve().parent
load_dotenv(SMOKE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in {SMOKE_DIR / '.env'}")
    return value


def _list_env(name: str) -> list[str]:
    return cast(list[str], json.loads(os.getenv(name, "[]")))


def _session_stem() -> Path:
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "telegram").strip()
    if not session_name or Path(session_name).name != session_name:
        raise RuntimeError("TELEGRAM_SESSION_NAME must be a simple filename")
    return SMOKE_DIR / session_name


async def consume(queue: asyncio.Queue[TelegramStreamedMessage | None]) -> None:
    while True:
        message = await queue.get()
        try:
            if message is None:
                break

            print("-" * 150)
            print(message)
            print("-" * 150)
            print("")
        finally:
            queue.task_done()


async def main() -> None:
    session_stem = _session_stem()
    session_file = session_stem.with_suffix(".session")
    if not session_file.exists():
        logger.error(
            "Telegram session is missing at %s. Run `uv run smoke/login.py` "
            "once while present to enter the SMS/2FA codes.",
            session_file,
        )
        return

    channels = _list_env("TELEGRAM_MONITOR_CHANNELS")
    if not channels:
        raise RuntimeError(
            f"TELEGRAM_MONITOR_CHANNELS is required in {SMOKE_DIR / '.env'}"
        )

    async with TelegramClient(
        str(session_stem),
        int(_required_env("TELEGRAM_API_ID")),
        _required_env("TELEGRAM_API_HASH"),
        auto_reconnect=True,
    ) as client:
        if not await client.is_user_authorized():
            logger.error(
                "Telegram session at %s is not authorized. Run `uv run "
                "smoke/login.py` manually.",
                session_file,
            )
            return

        logger.info(
            "Telegram session authorized. Monitoring %d channel(s). Press "
            "Ctrl-C to stop.",
            len(channels),
        )
        listener = TelegramListener(
            client=client,
            channels=channels,
            image_channels=_list_env("TELEGRAM_IMAGE_CHANNELS"),
            translation_channels=_list_env("TELEGRAM_TRANSLATION_CHANNELS"),
            translation_target_language=os.getenv(
                "TELEGRAM_TRANSLATION_TARGET_LANGUAGE", "en"
            ),
            translation_timeout=float(os.getenv("TELEGRAM_TRANSLATION_TIMEOUT", "3")),
            translation_max_concurrency=int(
                os.getenv("TELEGRAM_TRANSLATION_MAX_CONCURRENCY", "2")
            ),
            queue_maxsize=int(os.getenv("TELEGRAM_QUEUE_MAXSIZE", "1000")),
        )
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
    except (AuthKeyError, UnauthorizedError) as exc:
        logger.error(
            "Telegram session unavailable: %s No interactive login was started.",
            exc,
        )
    except KeyboardInterrupt:
        logger.info("Stopped.")
