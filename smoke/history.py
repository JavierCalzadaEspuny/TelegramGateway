"""Run the historical TelegramHistory smoke test with local configuration."""

from __future__ import annotations

import asyncio
import logging

from telethon.errors import AuthKeyError, UnauthorizedError

from telegram_gateway import TelegramHistory, TelegramSession, TelegramSessionError

CHANNELS: list[str] = ["testosint01"]
IMAGE_CHANNELS: list[str] = ["testosint01"]
TRANSLATION_CHANNELS: list[str] = ["testosint01"]
START = 1789675200  # Thu Sep 17 2026 22:00:00 GMT+0200
END = 1789678800    # Thu Sep 17 2026 23:00:00 GMT+0200
TRANSLATION_TARGET_LANGUAGE = "en"
TRANSLATION_TIMEOUT = 5.0
TRANSLATION_RETRIES = 2
HISTORY_WAIT_TIME = 1.0
SHOW_PROGRESS = True

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not CHANNELS:
        raise RuntimeError("Set CHANNELS at the top of smoke/history.py")

    try:
        async with TelegramSession() as client:
            history = TelegramHistory(
                client=client,
                channels=CHANNELS,
                image_channels=IMAGE_CHANNELS,
                translation_channels=TRANSLATION_CHANNELS,
                translation_target_language=TRANSLATION_TARGET_LANGUAGE,
                translation_timeout=TRANSLATION_TIMEOUT,
                translation_retries=TRANSLATION_RETRIES,
                history_wait_time=HISTORY_WAIT_TIME,
            )
            messages = await history.fetch(
                start=START,
                end=END,
                show_progress=SHOW_PROGRESS,
            )
    except TelegramSessionError as exc:
        logger.error("%s", exc)
        return

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
