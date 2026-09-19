"""Shared project-local Telegram client for manual smoke scripts."""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values
from telethon import TelegramClient

PROJECT_DIR = Path.cwd()
TELEGRAM_ENV = PROJECT_DIR / ".telegram" / ".env"
SESSIONS_DIR = PROJECT_DIR / ".telegram" / "sessions"
CREDENTIALS = dotenv_values(TELEGRAM_ENV, interpolate=False)


def credential(name: str) -> str:
    value = CREDENTIALS.get(name)
    value = value.strip() if value else ""
    if not value:
        raise RuntimeError(f"{name} is required in {TELEGRAM_ENV}")
    return value


def session_file() -> Path:
    phone = credential("TELEGRAM_PHONE")
    normalized_phone = "".join(
        character for character in phone if character.isdigit()
    )
    if not normalized_phone:
        raise RuntimeError("TELEGRAM_PHONE must contain at least one digit")
    return SESSIONS_DIR / f"{normalized_phone}.session"


def new_client() -> TelegramClient:
    session = session_file().with_suffix("")
    try:
        api_id = int(credential("TELEGRAM_API_ID"))
    except ValueError as exc:
        raise RuntimeError(
            f"TELEGRAM_API_ID must be an integer in {TELEGRAM_ENV}"
        ) from exc
    return TelegramClient(
        str(session),
        api_id,
        credential("TELEGRAM_API_HASH"),
        auto_reconnect=True,
    )


async def connected_client() -> TelegramClient:
    path = session_file()
    if not path.exists():
        raise RuntimeError(
            f"Telegram session is missing at {path}. "
            "Run `uv run telegram-login` manually."
        )

    client = new_client()
    try:
        await client.connect()
        if await client.is_user_authorized():
            return client
        raise RuntimeError(
            f"Telegram session at {path} is not authorized. "
            "Run `uv run telegram-login` manually."
        )
    except BaseException:
        await client.disconnect()
        raise
