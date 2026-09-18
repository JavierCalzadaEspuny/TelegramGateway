"""Run the historical TelegramHistory smoke test with local configuration."""

from __future__ import annotations

import asyncio
import logging
import os

from telethon.errors import AuthKeyError, UnauthorizedError

from telegram_gateway import TelegramHistory

from _common import bool_env, connected_client, float_env, int_env, list_env

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    channels = list_env("TELEGRAM_HISTORY_CHANNELS")
    if not channels:
        raise RuntimeError("TELEGRAM_HISTORY_CHANNELS cannot be empty")

    try:
        client = await connected_client()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return
    try:
        history = TelegramHistory(
            client=client,
            channels=channels,
            image_channels=list_env("TELEGRAM_HISTORY_IMAGE_CHANNELS"),
            translation_channels=list_env("TELEGRAM_HISTORY_TRANSLATION_CHANNELS"),
            translation_target_language=os.getenv(
                "TELEGRAM_HISTORY_TRANSLATION_TARGET_LANGUAGE", "en"
            ),
            translation_timeout=float_env("TELEGRAM_HISTORY_TRANSLATION_TIMEOUT", 5),
            translation_retries=int_env(
                "TELEGRAM_HISTORY_TRANSLATION_RETRIES", 2
            ),
            history_wait_time=float_env("TELEGRAM_HISTORY_WAIT_TIME", 1),
        )
        messages = await history.fetch(
            start=int_env("TELEGRAM_HISTORY_START"),
            end=int_env("TELEGRAM_HISTORY_END"),
            show_progress=bool_env("TELEGRAM_HISTORY_SHOW_PROGRESS"),
        )
    finally:
        await client.disconnect()

    for message in messages:
        print(message)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (AuthKeyError, UnauthorizedError) as exc:
        logger.error(
            "Telegram session unavailable: %s No interactive login was started.",
            exc,
        )
