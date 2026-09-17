"""Real-time Telegram message listener with asyncio queue output."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from time import perf_counter
from typing import cast

import emoji
import ftfy
from telethon import TelegramClient, events
from telethon.tl import functions, types
from telethon.tl.custom.message import Message

from ._exceptions import ConfigurationError, TranslationError
from ._models import TelegramStreamedMessage

logger = logging.getLogger(__name__)

# Sentinel placed on the queue when the listener stops so consumers can detect shutdown.
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


def _validate_channels(
    channels: Sequence[str],
    *,
    parameter: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    """Validate channel usernames without changing the caller's input."""
    if isinstance(channels, str):
        raise ConfigurationError(f"{parameter} must be a sequence of usernames.")

    validated = tuple(channels)
    if any(not isinstance(channel, str) or not channel for channel in validated):
        raise ConfigurationError(f"{parameter} must contain only usernames.")
    if not allow_empty and not validated:
        raise ConfigurationError(f"{parameter} cannot be empty.")
    return validated


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

    1. Create, connect, and authorize a :class:`~telethon.TelegramClient`.
    2. Create a ``TelegramListener`` with that client, the channels to monitor,
       and, optionally, the subset to translate.
    3. Consume :class:`~telegramlistener.TelegramStreamedMessage` objects from
       :attr:`queue`.

    Authentication belongs to the caller. Telethon handles transient connection
    recovery according to the options used to create the client. The listener
    waits until that client disconnects and propagates terminal errors. The
    listener never disconnects the supplied client. Instances are single-use;
    create a new listener after shutdown.

    **Backpressure**: pass ``queue_maxsize`` to cap queue depth. When the queue
    is full, incoming messages are dropped and a warning is emitted to prevent
    blocking the Telethon event loop.

    Args:
        client: A connected and authorized :class:`~telethon.TelegramClient`.
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
        client: TelegramClient,
        channels: Sequence[str],
        *,
        image_channels: Sequence[str] = (),
        translation_channels: Sequence[str] = (),
        translation_target_language: str = "en",
        translation_timeout: float = 3.0,
        translation_max_concurrency: int = 2,
        queue_maxsize: int = 0,
    ) -> None:
        monitored_channels = _validate_channels(
            channels,
            parameter="channels",
            allow_empty=False,
        )
        downloaded_image_channels = frozenset(
            _validate_channels(
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
            _validate_channels(
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

        self._client = client
        self._channels = monitored_channels
        self._image_channels = downloaded_image_channels
        self._translation_channels = translated_channels
        self._translation_target_language = _normalize_target_language(
            translation_target_language
        )
        self._translation_timeout = translation_timeout
        self._translation_semaphore = asyncio.Semaphore(translation_max_concurrency)
        self._started = False
        self.queue: asyncio.Queue[TelegramStreamedMessage | None] = asyncio.Queue(
            maxsize=queue_maxsize
        )
        self._chat_meta: dict[int, tuple[str, str | None]] = {}

    async def _translate_text(self, text: str, target_language: str) -> str:
        """Translate plain text through the listener's active Telegram client."""
        if not text.strip():
            raise TranslationError("Text to translate cannot be empty.")
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
        """Start the listener and block until the supplied client disconnects."""
        if self._started:
            raise RuntimeError("TelegramListener has already been started.")
        self._started = True

        try:
            client = self._client
            if not client.is_connected():
                raise RuntimeError(
                    "TelegramListener requires a connected TelegramClient."
                )

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
            await client.run_until_disconnected()
        finally:
            self._signal_shutdown()

    def _signal_shutdown(self) -> None:
        """End the queue without blocking, even when its buffer is full."""
        try:
            self.queue.put_nowait(_SENTINEL)
        except asyncio.QueueFull:
            self.queue.get_nowait()
            self.queue.task_done()
            self.queue.put_nowait(_SENTINEL)
            logger.warning("Queue full during shutdown; dropped one buffered message.")

    async def _download_configured_images(
        self, messages: Sequence[Message]
    ) -> tuple[list[bytes], float]:
        """Return opted-in photos and milliseconds spent attempting downloads."""
        if not messages or not self._image_channels:
            return [], 0.0

        _, _, channel_username = await _resolve_chat_meta(messages[0], self._chat_meta)
        if channel_username not in self._image_channels:
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
        if text and channel_username in self._translation_channels:
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
        logger.debug(
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
