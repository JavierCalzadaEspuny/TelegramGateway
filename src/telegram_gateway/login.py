"""Prepare and authorize a project-local Telegram session."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import tempfile
from collections.abc import Sequence
from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values, set_key
from telethon import TelegramClient

from ._session import _normalize_phone, _parse_api_id, _paths

_ENV_TEMPLATE = (
    "TELEGRAM_API_ID=\n"
    "TELEGRAM_API_HASH=\n"
    "TELEGRAM_PHONE=\n"
    "TELEGRAM_2FA_PASSWORD=\n"
)
_GITIGNORE = "*\n!.gitignore\n"


def _restrict(path: Path, mode: int) -> None:
    """Apply private permissions when the platform supports them."""
    try:
        path.chmod(mode)
    except OSError:
        pass


def _prepare(root: Path) -> tuple[Path, Path]:
    """Create the local Telegram layout without replacing credentials."""
    env_file, sessions_dir = _paths(root)
    telegram_dir = env_file.parent

    telegram_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    sessions_dir.mkdir(mode=0o700, exist_ok=True)
    _restrict(telegram_dir, 0o700)
    _restrict(sessions_dir, 0o700)

    if not env_file.exists():
        env_file.write_text(_ENV_TEMPLATE, encoding="utf-8")
    _restrict(env_file, 0o600)

    gitignore = telegram_dir / ".gitignore"
    if not gitignore.exists() or gitignore.read_text(encoding="utf-8") != _GITIGNORE:
        gitignore.write_text(_GITIGNORE, encoding="utf-8")

    return env_file, sessions_dir


def _missing_value(
    values: dict[str, str | None],
    staged: dict[str, str],
    name: str,
    prompt: str,
) -> str:
    """Return an existing value or prompt once and stage the answer."""
    value = values.get(name)
    if value is None or not value.strip():
        value = input(prompt)
        if not value.strip():
            raise ValueError(f"{name} cannot be empty.")
        staged[name] = value
    return value


def _persist(env_file: Path, staged: dict[str, str]) -> None:
    """Atomically fill values that remain absent from the environment file."""
    if not staged:
        return

    current = dict(dotenv_values(env_file, interpolate=False))
    updates = {
        name: value
        for name, value in staged.items()
        if not (current.get(name) or "").strip()
    }
    if not updates:
        return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".env.",
        dir=env_file.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(env_file, temporary)
        for name, value in updates.items():
            set_key(str(temporary), name, value, quote_mode="auto")
        _restrict(temporary, 0o600)
        os.replace(temporary, env_file)
    finally:
        temporary.unlink(missing_ok=True)


async def _login(root: Path) -> Path:
    """Authorize the configured account and persist newly validated values."""
    env_file, sessions_dir = _prepare(root)
    values = dict(dotenv_values(env_file, interpolate=False))
    staged: dict[str, str] = {}

    raw_api_id = _missing_value(
        values,
        staged,
        "TELEGRAM_API_ID",
        "Telegram API ID: ",
    )
    api_id = _parse_api_id(raw_api_id)

    api_hash = _missing_value(
        values,
        staged,
        "TELEGRAM_API_HASH",
        "Telegram API hash: ",
    ).strip()
    phone = _missing_value(
        values,
        staged,
        "TELEGRAM_PHONE",
        "Telegram phone: ",
    ).strip()
    session = sessions_dir / _normalize_phone(phone)

    configured_password = values.get("TELEGRAM_2FA_PASSWORD") or ""

    def password_callback() -> str:
        if configured_password:
            return configured_password
        entered_password = getpass("Telegram 2FA password: ")
        if not entered_password:
            raise ValueError("TELEGRAM_2FA_PASSWORD cannot be empty.")
        staged["TELEGRAM_2FA_PASSWORD"] = entered_password
        return entered_password

    def code_callback() -> str:
        code = input("Telegram code: ").strip()
        if not code:
            raise ValueError("Telegram code cannot be empty.")
        return code

    client = TelegramClient(str(session), api_id, api_hash)
    try:
        await client.start(
            phone=phone,
            password=password_callback,
            code_callback=code_callback,
        )
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram did not authorize the session.")
    finally:
        await client.disconnect()

    _persist(env_file, staged)
    session_file = session.with_suffix(".session")
    if session_file.exists():
        _restrict(session_file, 0o600)
    return session_file


def main(argv: Sequence[str] | None = None) -> None:
    """Run the project-local Telegram login command."""
    parser = argparse.ArgumentParser(
        prog="telegram-login",
        description="Prepare or authorize a project-local Telegram session.",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="create .telegram without starting an interactive login",
    )
    arguments = parser.parse_args(argv)
    root = Path.cwd()

    if arguments.prepare:
        _prepare(root)
        print(f"Telegram directory prepared at {root / '.telegram'}")
        return

    session_file = asyncio.run(_login(root))
    print(f"Telegram session ready at {session_file}")


if __name__ == "__main__":
    main()
