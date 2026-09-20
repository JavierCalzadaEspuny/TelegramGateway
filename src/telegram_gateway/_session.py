"""Project-local Telegram client lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from dotenv import dotenv_values
from telethon import TelegramClient


class TelegramSessionError(RuntimeError):
    """The project-local Telegram configuration or session is unusable."""


@dataclass(frozen=True, slots=True)
class _TelegramConfig:
    api_id: int
    api_hash: str
    session_stem: Path
    session_file: Path


def _paths(root: Path) -> tuple[Path, Path]:
    telegram_dir = root / ".telegram"
    return telegram_dir / ".env", telegram_dir / "sessions"


def _parse_api_id(value: str) -> int:
    try:
        api_id = int(value)
    except ValueError as exc:
        raise ValueError("TELEGRAM_API_ID must be an integer") from exc
    if api_id <= 0:
        raise ValueError("TELEGRAM_API_ID must be greater than zero")
    return api_id


def _normalize_phone(phone: str) -> str:
    normalized = "".join(character for character in phone if character.isdigit())
    if not normalized:
        raise ValueError("TELEGRAM_PHONE must contain at least one digit")
    return normalized


def _load_config(root: Path) -> _TelegramConfig:
    env_file, sessions_dir = _paths(root)
    if not env_file.is_file():
        raise TelegramSessionError(
            f"Telegram configuration not found at {env_file}. "
            "Run `uv run telegram-login` from the project root."
        )

    values = dotenv_values(env_file, interpolate=False)

    def required(name: str) -> str:
        value = values.get(name)
        if value is None or not value.strip():
            raise TelegramSessionError(
                f"{name} is missing from {env_file}. "
                "Run `uv run telegram-login` from the project root."
            )
        return value.strip()

    try:
        api_id = _parse_api_id(required("TELEGRAM_API_ID"))
        normalized_phone = _normalize_phone(required("TELEGRAM_PHONE"))
    except ValueError as exc:
        raise TelegramSessionError(str(exc)) from exc

    session_stem = sessions_dir / normalized_phone
    return _TelegramConfig(
        api_id=api_id,
        api_hash=required("TELEGRAM_API_HASH"),
        session_stem=session_stem,
        session_file=session_stem.with_suffix(".session"),
    )


class TelegramSession:
    """Own one connected client backed by a project-local login session."""

    def __init__(
        self,
        project_root: Path | str | None = None,
        **client_options: object,
    ) -> None:
        self._root = Path.cwd() if project_root is None else Path(project_root)
        self._client_options = client_options
        self._client: TelegramClient | None = None

    @property
    def client(self) -> TelegramClient:
        """Return the owned connected client."""
        if self._client is None:
            raise RuntimeError("Telegram session is not connected")
        return self._client

    async def connect(self) -> TelegramClient:
        """Load, connect, and authorize the project-local Telegram client."""
        if self._client is not None:
            raise RuntimeError("Telegram session is already connected")

        config = _load_config(self._root)
        if not config.session_file.is_file():
            raise TelegramSessionError(
                f"Telegram session not found at {config.session_file}. "
                "Run `uv run telegram-login` from the project root."
            )

        client = TelegramClient(
            str(config.session_stem),
            config.api_id,
            config.api_hash,
            **self._client_options,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramSessionError(
                    f"Telegram session at {config.session_file} is not authorized. "
                    "Run `uv run telegram-login` from the project root."
                )
        except BaseException:
            await client.disconnect()
            raise

        self._client = client
        return client

    async def disconnect(self) -> None:
        """Disconnect the owned client, if connected."""
        if self._client is None:
            return
        client = self._client
        await client.disconnect()
        self._client = None

    async def __aenter__(self) -> TelegramClient:
        return await self.connect()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.disconnect()
