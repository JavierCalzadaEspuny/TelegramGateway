"""Real-time Telegram message listener with asyncio queue output."""

from __future__ import annotations

import asyncio
import logging
import math
import random
from collections.abc import Sequence
from time import perf_counter
from typing import cast

import emoji
import ftfy
from telethon import TelegramClient, events
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    UserDeactivatedError,
)
from telethon.tl import functions, types
from telethon.tl.custom.message import Message

from ._exceptions import ConfigurationError, SessionError, TranslationError
from ._models import TelegramStreamedMessage
from ._session import SessionManager

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 60.0
_FATAL_ERRORS = (AuthKeyDuplicatedError, AuthKeyUnregisteredError, UserDeactivatedError)

# Sentinel placed on the queue by aclose() so consumers can detect shutdown.
_SENTINEL: TelegramStreamedMessage | None = None


def _sanitize(text: str | None) -> str | None:
    """
    Removes emojis and fixes broken unicode text.
    Returns None when the input is empty or sanitizes down to an empty string.
    """
    if text is None:
        return None
    sanitized = emoji.replace_emoji(ftfy.fix_text(text), replace="").strip()
    return sanitized or None


def _normalize_channel(channel: str) -> str:
    """Normalize a Telegram username for consistent matching."""
    return channel.strip().lstrip("@").lower()


def _normalize_channels(
    channels: Sequence[str],
    *,
    parameter: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    """Normalize, validate, and deduplicate channel usernames."""
    if isinstance(channels, str):
        raise ConfigurationError(f"{parameter} must be a sequence of usernames.")
    if any(not isinstance(channel, str) for channel in channels):
        raise ConfigurationError(f"{parameter} must contain only usernames.")

    normalized = tuple(
        dict.fromkeys(_normalize_channel(channel) for channel in channels)
    )
    if not allow_empty and not normalized:
        raise ConfigurationError(f"{parameter} cannot be empty.")
    if any(not channel for channel in normalized):
        raise ConfigurationError(f"{parameter} cannot contain empty usernames.")
    return normalized


def _normalize_target_language(target_language: str) -> str:
    """Validate and normalize a two-letter ISO 639-1 language code."""
    if not isinstance(target_language, str):
        raise ConfigurationError("Target language must be a string.")
    normalized = target_language.strip().lower()
    if len(normalized) != 2 or not normalized.isascii() or not normalized.isalpha():
        raise ConfigurationError(
            "Target language must be a two-letter ISO 639-1 code such as 'en' or 'es'."
        )
    return normalized


async def _download_image_bytes(message: Message) -> bytes | None:
    """Safely attempts to download media from a message as bytes."""
    try:
        if getattr(message, "photo", None) is None:
            return None

        payload = await message.download_media(file=bytes)
        return payload if isinstance(payload, bytes) else None
    except Exception as exc:
        logger.warning(
            "Could not download image for chat_id=%s: %s",
            message.chat_id,
            exc,
        )
        return None


async def _resolve_chat_meta(
    message: Message,
    chat_meta: dict[int, tuple[str, str | None]],
) -> tuple[int, str, str | None]:
    """Resolves and caches chat title and Telegram username by ID."""
    chat_id = message.chat_id
    if chat_id not in chat_meta:
        chat = await message.get_chat()
        chat_meta[chat_id] = (
            getattr(chat, "title", str(chat_id)),
            getattr(chat, "username", None),
        )

    channel_title, channel_username = chat_meta[chat_id]
    return chat_id, channel_title, channel_username


class TelegramListener:
    """Streams new messages from configured Telegram channels into an asyncio queue.

    Typical usage:

    1. Create a :class:`SessionManager` and ensure it is operational.
    2. Create a ``TelegramListener`` with the channels to monitor and, optionally,
       the subset to translate.
    3. Consume :class:`~telegramlistener.TelegramStreamedMessage` objects from
       :attr:`queue`.

    The listener reconnects automatically on transient failures using exponential
    backoff (capped at 60 s). It stops only when :meth:`aclose` / :meth:`stop` is
    called, or when the Telegram session is permanently invalidated. Instances
    are single-use; create a new listener after shutdown.

    **Backpressure**: pass ``queue_maxsize`` to cap queue depth. When the queue
    is full, incoming messages are dropped and a warning is emitted to prevent
    blocking the Telethon event loop.

    Args:
        session_manager: An authorized :class:`SessionManager` instance.
        channels: Channel usernames to monitor.
        image_channels: Monitored channels whose photos should be downloaded.
            Empty by default, which disables image downloads.
        translation_channels: Monitored channels whose text and captions should
            be translated. Empty by default, which disables translation.
        translation_target_language: Two-letter ISO 639-1 destination language.
        translation_timeout: Maximum total seconds for one translation,
            including time waiting for translation capacity.
        translation_max_concurrency: Maximum translation requests in flight.
        queue_maxsize: Maximum number of messages buffered in :attr:`queue`.
            ``0`` (default) means unbounded.

    Raises:
        ConfigurationError: If any constructor setting is invalid.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        channels: Sequence[str],
        *,
        image_channels: Sequence[str] = (),
        translation_channels: Sequence[str] = (),
        translation_target_language: str = "en",
        translation_timeout: float = 3.0,
        translation_max_concurrency: int = 2,
        queue_maxsize: int = 0,
    ) -> None:
        monitored_channels = _normalize_channels(
            channels,
            parameter="channels",
            allow_empty=False,
        )
        downloaded_image_channels = frozenset(
            _normalize_channels(
                image_channels,
                parameter="image_channels",
                allow_empty=True,
            )
        )
        unknown_image_channels = downloaded_image_channels.difference(
            monitored_channels
        )
        if unknown_image_channels:
            unknown = ", ".join(sorted(unknown_image_channels))
            raise ConfigurationError(
                f"image_channels must be monitored channels; unknown: {unknown}."
            )
        translated_channels = frozenset(
            _normalize_channels(
                translation_channels,
                parameter="translation_channels",
                allow_empty=True,
            )
        )
        unknown_channels = translated_channels.difference(monitored_channels)
        if unknown_channels:
            unknown = ", ".join(sorted(unknown_channels))
            raise ConfigurationError(
                f"translation_channels must be monitored channels; unknown: {unknown}."
            )
        if (
            isinstance(translation_timeout, bool)
            or not isinstance(translation_timeout, (int, float))
            or not math.isfinite(translation_timeout)
            or translation_timeout <= 0
        ):
            raise ConfigurationError("translation_timeout must be greater than zero.")
        if (
            isinstance(translation_max_concurrency, bool)
            or not isinstance(translation_max_concurrency, int)
            or translation_max_concurrency <= 0
        ):
            raise ConfigurationError(
                "translation_max_concurrency must be a positive integer."
            )
        if (
            isinstance(queue_maxsize, bool)
            or not isinstance(queue_maxsize, int)
            or queue_maxsize < 0
        ):
            raise ConfigurationError("queue_maxsize must be a non-negative integer.")

        self._manager = session_manager
        self._channels = monitored_channels
        self._image_channels = downloaded_image_channels
        self._translation_channels = translated_channels
        self._translation_target_language = _normalize_target_language(
            translation_target_language
        )
        self._translation_timeout = translation_timeout
        self._translation_semaphore = asyncio.Semaphore(translation_max_concurrency)
        self._started = False
        self._client: TelegramClient | None = None
        self._stop_event = asyncio.Event()
        self._disconnect_task: asyncio.Task[None] | None = None
        self.queue: asyncio.Queue[TelegramStreamedMessage | None] = asyncio.Queue(
            maxsize=queue_maxsize
        )
        self._chat_meta: dict[int, tuple[str, str | None]] = {}

    async def _translate_text(self, text: str, target_language: str) -> str:
        """Translate plain text through the listener's active Telegram client."""
        if not text.strip():
            raise TranslationError("Text to translate cannot be empty.")
        if self._client is None:
            raise TranslationError(
                "TelegramListener is not running; translation requires its "
                "active user connection."
            )
        client = self._client

        request = functions.messages.TranslateTextRequest(
            text=[types.TextWithEntities(text=text, entities=[])],
            to_lang=target_language,
        )

        async def send_request() -> types.messages.TranslateResult:
            async with self._translation_semaphore:
                return await client(request)

        try:
            result = await asyncio.wait_for(
                send_request(),
                timeout=self._translation_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TranslationError(
                f"Telegram translation timed out after "
                f"{self._translation_timeout:g} seconds."
            ) from exc
        except Exception as exc:
            raise TranslationError(f"Telegram translation failed: {exc}") from exc

        if not result.result or not result.result[0].text:
            raise TranslationError("Telegram returned no translated text.")

        return cast(str, result.result[0].text)

    async def start(self) -> None:
        """Start the listener and block until stopped or invalidated."""
        if self._started:
            raise RuntimeError("TelegramListener has already been started.")
        if self._stop_event.is_set():
            raise RuntimeError("TelegramListener is closed and cannot be started.")
        self._started = True

        try:
            client = await self._manager.get_authorized_client()
            self._client = client

            client.add_event_handler(
                self._on_new_message,
                events.NewMessage(chats=self._channels),
            )
            client.add_event_handler(
                self._on_album,
                events.Album(chats=self._channels),
            )
            logger.info(
                "Listener started. Monitoring %d channel(s).",
                len(self._channels),
            )
            await self._run_until_stopped(client)
        finally:
            client = self._client
            if client is not None and client.is_connected():
                try:
                    await client.disconnect()
                except Exception as exc:
                    logger.warning("Telegram disconnect failed: %s", exc)
            self._client = None
            self._disconnect_task = None
            self._signal_shutdown()

    async def _run_until_stopped(self, client: TelegramClient) -> None:
        """Keep the client alive and reconnect after transient failures."""
        attempt = 0
        while not self._stop_event.is_set():
            try:
                await client.run_until_disconnected()
                break
            except _FATAL_ERRORS as exc:
                self._safely_cleanup_session()
                raise SessionError(
                    "Telegram session is invalid or revoked. "
                    "Manual login required; it was not started automatically."
                ) from exc
            except Exception as exc:
                if self._stop_event.is_set():
                    break

                attempt += 1
                delay = min(
                    _BACKOFF_CAP,
                    _BACKOFF_BASE**attempt,
                ) + random.uniform(0, 1)
                logger.warning(
                    "Unexpected error (%s). Reconnecting in %.1f s (attempt %d).",
                    exc,
                    delay,
                    attempt,
                )

                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._stop_event.wait()), timeout=delay
                    )
                    break
                except asyncio.TimeoutError:
                    pass

                try:
                    if not client.is_connected():
                        await client.connect()
                    attempt = 0
                except _FATAL_ERRORS as fatal_exc:
                    self._safely_cleanup_session()
                    raise SessionError(
                        "Telegram session is invalid or revoked during reconnect. "
                        "Manual login required; it was not started automatically."
                    ) from fatal_exc
                except Exception as reconnect_exc:
                    logger.error("Reconnection failed: %s. Retrying.", reconnect_exc)

    def _signal_shutdown(self) -> None:
        """End the queue without blocking, even when its buffer is full."""
        try:
            self.queue.put_nowait(_SENTINEL)
        except asyncio.QueueFull:
            self.queue.get_nowait()
            self.queue.task_done()
            self.queue.put_nowait(_SENTINEL)
            logger.warning("Queue full during shutdown; dropped one buffered message.")

    def _safely_cleanup_session(self) -> None:
        """Attempts best-effort cleanup of the session file."""
        try:
            self._manager._cleanup()
        except Exception:
            logger.debug("Session cleanup failed or is unavailable.")

    def stop(self) -> None:
        """Request a graceful shutdown non-blockingly."""
        self._stop_event.set()
        if self._client and self._client.is_connected():
            self._disconnect_task = asyncio.create_task(self._client.disconnect())

    async def aclose(self) -> None:
        """Shut down the listener and disconnect the Telegram client robustly."""
        self._stop_event.set()
        if self._client and self._client.is_connected():
            await self._client.disconnect()
        if self._disconnect_task is not None:
            await asyncio.shield(self._disconnect_task)

    async def __aenter__(self) -> TelegramListener:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _download_configured_images(
        self, messages: Sequence[Message]
    ) -> tuple[list[bytes], float]:
        """Return opted-in photos and milliseconds spent attempting downloads."""
        if not messages or not self._image_channels:
            return [], 0.0

        _, _, channel_username = await _resolve_chat_meta(messages[0], self._chat_meta)
        normalized_username = (
            _normalize_channel(channel_username) if channel_username else None
        )
        if normalized_username not in self._image_channels:
            return [], 0.0

        download_started = perf_counter()
        images: list[bytes] = []
        for message in messages:
            image_bytes = await _download_image_bytes(message)
            if image_bytes is not None:
                images.append(image_bytes)
        download_ms = (perf_counter() - download_started) * 1000
        return images, download_ms

    async def _enqueue_message(
        self,
        base_message: Message,
        text: str | None,
        images: list[bytes],
        *,
        processing_started: float,
        image_download_ms: float,
    ) -> None:
        """Enrich, construct, and safely enqueue one streamed message."""
        channel_id, channel_title, channel_username = await _resolve_chat_meta(
            base_message, self._chat_meta
        )
        translated_text = None
        translation_language = None
        translation_ms: float | None = None
        normalized_username = (
            _normalize_channel(channel_username) if channel_username else None
        )
        if (
            text
            and normalized_username
            and normalized_username in self._translation_channels
        ):
            translation_started = perf_counter()
            try:
                translated_text = _sanitize(
                    await self._translate_text(text, self._translation_target_language)
                )
            except TranslationError as exc:
                logger.warning(
                    "Translation failed for channel %r: %s. "
                    "Emitting the original message.",
                    channel_title,
                    exc,
                )
            else:
                if translated_text is not None:
                    translation_language = self._translation_target_language
            finally:
                translation_ms = (perf_counter() - translation_started) * 1000

        streamed_message = TelegramStreamedMessage(
            timestamp=int(base_message.date.timestamp()),
            channel_title=channel_title,
            channel_username=channel_username,
            channel_id=channel_id,
            text=text,
            images=tuple(images),
            translated_text=translated_text,
            translation_language=translation_language,
        )

        queued = True
        try:
            self.queue.put_nowait(streamed_message)
        except asyncio.QueueFull:
            queued = False
            logger.warning(
                "Queue full (maxsize=%d) — dropping message from %r.",
                self.queue.maxsize,
                channel_title,
            )

        processing_ms = (perf_counter() - processing_started) * 1000
        logger.info(
            "Processed Telegram message channel=%r message_id=%s "
            "processing_ms=%.1f translation_ms=%s image_download_ms=%.1f queued=%s",
            channel_username or channel_title,
            getattr(base_message, "id", "unknown"),
            processing_ms,
            "n/a" if translation_ms is None else f"{translation_ms:.1f}",
            image_download_ms,
            queued,
        )

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            processing_started = perf_counter()
            if event.message.grouped_id is not None:
                return

            message = event.message
            text = _sanitize((message.text or "").strip())

            images, image_download_ms = await self._download_configured_images(
                [message]
            )

            if not text and not images:
                return

            await self._enqueue_message(
                message,
                text,
                images,
                processing_started=processing_started,
                image_download_ms=image_download_ms,
            )

        except Exception:
            logger.exception(
                "Unhandled error processing message from chat_id=%s.",
                event.message.chat_id,
            )

    async def _on_album(self, event: events.Album.Event) -> None:
        try:
            processing_started = perf_counter()
            messages = event.messages
            if not messages:
                return

            text = _sanitize((messages[0].text or "").strip())

            images, image_download_ms = await self._download_configured_images(messages)

            if not images and not text:
                return

            await self._enqueue_message(
                messages[0],
                text,
                images,
                processing_started=processing_started,
                image_download_ms=image_download_ms,
            )

        except Exception:
            logger.exception(
                "Unhandled error processing album from chat_id=%s.",
                event.messages[0].chat_id if event.messages else "unknown",
            )
