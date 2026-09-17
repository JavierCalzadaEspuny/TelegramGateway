"""Shared Telegram message normalization and enrichment."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import cast

import emoji
import ftfy
from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError, ServerError, TimedOutError
from telethon.tl import functions, types
from telethon.tl.custom.message import Message

from ._exceptions import TranslationError
from ._models import TelegramMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessingPolicy:
    """Controls bounded translation behavior for one message coordinator."""

    translation_timeout: float
    translation_max_concurrency: int
    translation_retries: int
    retry_flood_waits: bool


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """A processed message with private enrichment telemetry."""

    message: TelegramMessage
    translation_ms: float | None
    image_download_ms: float


def _sanitize(text: str | None) -> str | None:
    """Remove emoji and repair text, returning ``None`` for empty input."""
    if text is None:
        return None
    sanitized = emoji.replace_emoji(ftfy.fix_text(text), replace="").strip()
    return sanitized or None


async def _download_image_bytes(message: Message) -> bytes | None:
    """Safely attempt to download one message photo as bytes."""
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


class MessageProcessor:
    """Build normalized messages from one Telegram message or an album."""

    def __init__(
        self,
        *,
        client: TelegramClient,
        image_channels: frozenset[str],
        translation_channels: frozenset[str],
        translation_target_language: str,
        policy: ProcessingPolicy,
    ) -> None:
        self._client = client
        self._image_channels = image_channels
        self._translation_channels = translation_channels
        self._translation_target_language = translation_target_language
        self._policy = policy
        self._translation_semaphore = asyncio.Semaphore(
            policy.translation_max_concurrency
        )
        self._chat_meta: dict[int, tuple[str, str | None]] = {}

    async def process(
        self,
        messages: Sequence[Message],
    ) -> ProcessingResult | None:
        """Normalize a Telegram message or album with optional enrichment."""
        if not messages:
            return None

        ordered_messages = sorted(messages, key=lambda message: message.id)
        base_message = ordered_messages[0]
        channel_id, channel_title, channel_username = await self._resolve_chat_meta(
            base_message
        )
        text = _sanitize(base_message.text)
        images, image_download_ms = await self._download_configured_images(
            ordered_messages,
            channel_username,
        )
        has_photo = any(
            getattr(message, "photo", None) is not None for message in ordered_messages
        )
        if text is None and not images and not has_photo:
            return None

        (
            translated_text,
            translation_language,
            translation_ms,
        ) = await self._translate_if_configured(
            text,
            channel_title,
            channel_username,
        )
        processed_message = TelegramMessage(
            message_id=base_message.id,
            timestamp=int(base_message.date.timestamp()),
            channel_title=channel_title,
            channel_username=channel_username,
            channel_id=channel_id,
            text=text,
            images=tuple(images),
            translated_text=translated_text,
            translation_language=translation_language,
        )
        return ProcessingResult(
            message=processed_message,
            translation_ms=translation_ms,
            image_download_ms=image_download_ms,
        )

    async def _resolve_chat_meta(self, message: Message) -> tuple[int, str, str | None]:
        """Resolve and cache the chat title and Telegram username by ID."""
        chat_id = message.chat_id
        if chat_id not in self._chat_meta:
            chat = await message.get_chat()
            self._chat_meta[chat_id] = (
                getattr(chat, "title", str(chat_id)),
                getattr(chat, "username", None),
            )

        channel_title, channel_username = self._chat_meta[chat_id]
        return chat_id, channel_title, channel_username

    async def _download_configured_images(
        self,
        messages: Sequence[Message],
        channel_username: str | None,
    ) -> tuple[list[bytes], float]:
        """Download photos in message-ID order when the channel opts in."""
        if channel_username not in self._image_channels:
            return [], 0.0

        download_started = perf_counter()
        images: list[bytes] = []
        for message in messages:
            image_bytes = await _download_image_bytes(message)
            if image_bytes is not None:
                images.append(image_bytes)
        return images, (perf_counter() - download_started) * 1000

    async def _translate_if_configured(
        self,
        text: str | None,
        channel_title: str,
        channel_username: str | None,
    ) -> tuple[str | None, str | None, float | None]:
        """Translate optional enrichment without replacing the original text."""
        if text is None or channel_username not in self._translation_channels:
            return None, None, None

        translation_started = perf_counter()
        try:
            translated_text = _sanitize(
                await self._translate_text(text, self._translation_target_language)
            )
        except TranslationError as exc:
            logger.warning(
                "Translation failed for channel %r: %s. Emitting the original message.",
                channel_title,
                exc,
            )
            translated_text = None

        translation_ms = (perf_counter() - translation_started) * 1000
        if translated_text is None:
            return None, None, translation_ms
        return translated_text, self._translation_target_language, translation_ms

    async def _translate_text(self, text: str, target_language: str) -> str:
        """Translate text, retrying only as the configured policy permits."""
        if not text.strip():
            raise TranslationError("Text to translate cannot be empty.")

        request = functions.messages.TranslateTextRequest(
            text=[types.TextWithEntities(text=text, entities=[])],
            to_lang=target_language,
        )
        attempt = 0
        while True:
            try:
                result = await asyncio.wait_for(
                    self._send_translation_request(request),
                    timeout=self._policy.translation_timeout,
                )
            except FloodWaitError as exc:
                if (
                    not self._policy.retry_flood_waits
                    or attempt >= self._policy.translation_retries
                ):
                    raise TranslationError(
                        f"Telegram translation failed: {exc}"
                    ) from exc
                attempt += 1
                await asyncio.sleep(exc.seconds)
            except asyncio.TimeoutError as exc:
                if attempt >= self._policy.translation_retries:
                    raise TranslationError(
                        "Telegram translation timed out after "
                        f"{self._policy.translation_timeout:g} seconds."
                    ) from exc
                attempt += 1
            except (ServerError, TimedOutError) as exc:
                if attempt >= self._policy.translation_retries:
                    raise TranslationError(
                        f"Telegram translation failed: {exc}"
                    ) from exc
                attempt += 1
            except (RPCError, ConnectionError, OSError) as exc:
                raise TranslationError(f"Telegram translation failed: {exc}") from exc
            except Exception as exc:
                if attempt >= self._policy.translation_retries:
                    raise TranslationError(
                        f"Telegram translation failed: {exc}"
                    ) from exc
                attempt += 1
            else:
                if not result.result or not result.result[0].text:
                    raise TranslationError("Telegram returned no translated text.")
                return cast(str, result.result[0].text)

    async def _send_translation_request(
        self,
        request: functions.messages.TranslateTextRequest,
    ) -> types.messages.TranslateResult:
        async with self._translation_semaphore:
            return await self._client(request)
