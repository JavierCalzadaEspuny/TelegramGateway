"""Run the historical TelegramHistory smoke test with local configuration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import AuthKeyError, UnauthorizedError

from telegram_gateway import TelegramHistory

SMOKE_DIR = Path(__file__).resolve().parent
load_dotenv(SMOKE_DIR / ".env")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in {SMOKE_DIR / '.env'}")
    return value


def _parse_int_env(name: str, default: str | None = None) -> int:
    value = os.getenv(name, default or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in {SMOKE_DIR / '.env'}")
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _list_env(name: str) -> list[str]:
    return cast(list[str], json.loads(os.getenv(name, "[]")))


def _session_stem() -> Path:
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "telegram").strip()
    if not session_name or Path(session_name).name != session_name:
        raise RuntimeError("TELEGRAM_SESSION_NAME must be a simple filename")
    return SMOKE_DIR / session_name


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

    channels = _list_env("TELEGRAM_HISTORY_CHANNELS")
    if not channels:
        raise RuntimeError(
            f"TELEGRAM_HISTORY_CHANNELS is required in {SMOKE_DIR / '.env'}"
        )

    client = TelegramClient(
        str(session_stem),
        int(_required_env("TELEGRAM_API_ID")),
        _required_env("TELEGRAM_API_HASH"),
        auto_reconnect=True,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error(
                "Telegram session at %s is not authorized. Run `uv run "
                "smoke/login.py` manually.",
                session_file,
            )
            return

        history = TelegramHistory(
            client=client,
            channels=channels,
            image_channels=_list_env("TELEGRAM_HISTORY_IMAGE_CHANNELS"),
            translation_channels=_list_env("TELEGRAM_HISTORY_TRANSLATION_CHANNELS"),
            translation_target_language=os.getenv(
                "TELEGRAM_HISTORY_TRANSLATION_TARGET_LANGUAGE", "en"
            ),
            translation_timeout=float(
                os.getenv("TELEGRAM_HISTORY_TRANSLATION_TIMEOUT", "5")
            ),
            translation_retries=int(
                os.getenv("TELEGRAM_HISTORY_TRANSLATION_RETRIES", "2")
            ),
            history_wait_time=float(os.getenv("TELEGRAM_HISTORY_WAIT_TIME", "1")),
        )
        messages = await history.fetch(
            start=_parse_int_env("TELEGRAM_HISTORY_START"),
            end=_parse_int_env("TELEGRAM_HISTORY_END"),
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
