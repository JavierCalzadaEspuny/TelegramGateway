"""Create or refresh the local Telethon session for the smoke test."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

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


def _session_stem() -> Path:
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "telegram").strip()
    if not session_name or Path(session_name).name != session_name:
        raise RuntimeError("TELEGRAM_SESSION_NAME must be a simple filename")
    return SMOKE_DIR / session_name


async def main() -> None:
    session_stem = _session_stem()
    session_stem.parent.mkdir(parents=True, exist_ok=True)
    async with TelegramClient(
        str(session_stem),
        int(_required_env("TELEGRAM_API_ID")),
        _required_env("TELEGRAM_API_HASH"),
    ) as client:
        await client.start(phone=_required_env("TELEGRAM_PHONE"))
        logger.info(
            "Telegram session ready at %s", session_stem.with_suffix(".session")
        )


if __name__ == "__main__":
    asyncio.run(main())
