"""Shared configuration for manual smoke scripts."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

SMOKE_DIR = Path(__file__).resolve().parent
load_dotenv(SMOKE_DIR / ".env")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in {SMOKE_DIR / '.env'}")
    return value


def list_env(name: str) -> list[str]:
    value = json.loads(os.getenv(name, "[]"))
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"{name} must be a JSON array of strings")
    return value


def int_env(name: str, default: int | None = None) -> int:
    raw = os.getenv(name, "" if default is None else str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return raw == "true"


def session_stem() -> Path:
    name = os.getenv("TELEGRAM_SESSION_NAME", "telegram").strip()
    if not name or Path(name).name != name:
        raise RuntimeError("TELEGRAM_SESSION_NAME must be a simple filename")
    return SMOKE_DIR / name


def new_client() -> TelegramClient:
    return TelegramClient(
        str(session_stem()),
        int(required_env("TELEGRAM_API_ID")),
        required_env("TELEGRAM_API_HASH"),
        auto_reconnect=True,
    )


async def connected_client() -> TelegramClient:
    session_file = session_stem().with_suffix(".session")
    if not session_file.exists():
        raise RuntimeError(
            f"Telegram session is missing at {session_file}. "
            "Run `uv run smoke/login.py` manually."
        )

    client = new_client()
    try:
        await client.connect()
        if await client.is_user_authorized():
            return client
        raise RuntimeError(
            f"Telegram session at {session_file} is not authorized. "
            "Run `uv run smoke/login.py` manually."
        )
    except BaseException:
        await client.disconnect()
        raise
