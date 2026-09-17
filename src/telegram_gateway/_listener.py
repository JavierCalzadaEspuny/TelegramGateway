"""Real-time Telegram message listener with asyncio queue output."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from time import perf_counter

from telethon import TelegramClient, events

from ._exceptions import ConfigurationError
from ._models import TelegramMessage
from ._processing import MessageProcessor, ProcessingPolicy, ProcessingResult

logger = logging.getLogger(__name__)

# Sentinel placed on the queue when the listener stops so consumers can detect shutdown.
_SENTINEL: TelegramMessage | None = None


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


class TelegramListener:
    """Streams new messages from configured Telegram channels into an asyncio queue.

    Typical usage:

    1. Create, connect, and authorize a :class:`~telethon.TelegramClient`.
    2. Create a ``TelegramListener`` with that client, the channels to monitor,
       and, optionally, the subset to translate.
    3. Consume :class:`~telegram_gateway.TelegramMessage` objects from
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
        self._processor = MessageProcessor(
            client=client,
            image_channels=downloaded_image_channels,
            translation_channels=translated_channels,
            translation_target_language=self._translation_target_language,
            policy=ProcessingPolicy(
                translation_timeout=translation_timeout,
                translation_max_concurrency=translation_max_concurrency,
                translation_retries=0,
                retry_flood_waits=False,
            ),
        )
        self._started = False
        self.queue: asyncio.Queue[TelegramMessage | None] = asyncio.Queue(
            maxsize=queue_maxsize
        )

    async def start(self) -> None:
        """Start the listener and block until the supplied client disconnects."""
        if self._started:
            raise RuntimeError("TelegramListener has already been started.")
        self._started = True

        client = self._client
        try:
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
            client.remove_event_handler(self._on_new_message)
            client.remove_event_handler(self._on_album)
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

    def _enqueue_message(
        self, processed: ProcessingResult, *, processing_started: float
    ) -> None:
        """Safely enqueue one processed message without blocking updates."""
        streamed_message = processed.message
        queued = True
        try:
            self.queue.put_nowait(streamed_message)
        except asyncio.QueueFull:
            queued = False
            logger.warning(
                "Queue full (maxsize=%d) — dropping message from %r.",
                self.queue.maxsize,
                streamed_message.channel_title,
            )

        processing_ms = (perf_counter() - processing_started) * 1000
        logger.debug(
            "Processed Telegram message channel=%r message_id=%s "
            "processing_ms=%.1f translation_ms=%s image_download_ms=%.1f queued=%s",
            streamed_message.channel_username or streamed_message.channel_title,
            streamed_message.message_id,
            processing_ms,
            "n/a"
            if processed.translation_ms is None
            else f"{processed.translation_ms:.1f}",
            processed.image_download_ms,
            queued,
        )

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            processing_started = perf_counter()
            if event.message.grouped_id is not None:
                return

            processed = await self._processor.process([event.message])
            if processed is None:
                return
            self._enqueue_message(
                processed,
                processing_started=processing_started,
            )

        except Exception:
            logger.exception(
                "Unhandled error processing message from chat_id=%s.",
                event.message.chat_id,
            )

    async def _on_album(self, event: events.Album.Event) -> None:
        try:
            processing_started = perf_counter()
            processed = await self._processor.process(event.messages)
            if processed is None:
                return
            self._enqueue_message(
                processed,
                processing_started=processing_started,
            )

        except Exception:
            logger.exception(
                "Unhandled error processing album from chat_id=%s.",
                event.messages[0].chat_id if event.messages else "unknown",
            )
