"""Shared Telegram message normalization and enrichment."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import emoji
import ftfy
from telethon import TelegramClient
from telethon.errors import FloodWaitError, ServerError, TimedOutError
from telethon.tl import functions, types
from telethon.tl.custom.message import Message

from ._models import TelegramMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessingPolicy:
    """Controls bounded translation behavior for one message coordinator."""

    translation_timeout: float
    translation_max_concurrency: int
    translation_retries: int
    retry_flood_waits: bool


def _sanitize(text: str | None) -> str | None:
    """Remove emoji and repair text, returning ``None`` for empty input."""
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
    """Return validated channel usernames."""
    if isinstance(channels, str):
        raise ValueError(f"{parameter} must be a sequence of usernames.")

    validated = tuple(channels)
    if any(not isinstance(channel, str) or not channel for channel in validated):
        raise ValueError(f"{parameter} must contain only usernames.")
    if not allow_empty and not validated:
        raise ValueError(f"{parameter} cannot be empty.")
    return validated


def _validate_channel_subset(
    channels: Sequence[str],
    monitored_channels: Sequence[str],
    *,
    parameter: str,
) -> frozenset[str]:
    """Return channels after ensuring they are monitored."""
    validated = frozenset(
        _validate_channels(channels, parameter=parameter, allow_empty=True)
    )
    unknown = validated.difference(monitored_channels)
    if unknown:
        raise ValueError(
            f"{parameter} must be monitored channels; unknown: "
            f"{', '.join(sorted(unknown))}."
        )
    return validated


def _normalize_target_language(target_language: str) -> str:
    """Return a normalized two-letter ISO 639-1 language code."""
    if not isinstance(target_language, str):
        raise ValueError("Target language must be a string.")
    normalized = target_language.strip().lower()
    if len(normalized) != 2 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError(
            "Target language must be a two-letter ISO 639-1 code such as 'en' or 'es'."
        )
    return normalized


def _validate_positive_number(value: object, *, parameter: str) -> float:
    """Return a finite positive number."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{parameter} must be greater than zero.")
    return float(value)


def _validate_non_negative_integer(value: object, *, parameter: str) -> int:
    """Return a non-negative integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{parameter} must be a non-negative integer.")
    return value


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
    ) -> TelegramMessage | None:
        """Normalize a Telegram message or album with optional enrichment."""
        if not messages:
            return None

        ordered_messages = sorted(messages, key=lambda message: message.id)
        base_message = ordered_messages[0]
        channel_id, channel_title, channel_username = await self._resolve_chat_meta(
            base_message
        )
        text = _sanitize(base_message.text)
        images = await self._download_configured_images(
            ordered_messages,
            channel_username,
        )
        has_photo = any(
            getattr(message, "photo", None) is not None for message in ordered_messages
        )
        if text is None and not images and not has_photo:
            return None

        translated_text, translation_language = await self._translate_if_configured(
            text,
            channel_title,
            channel_username,
        )
        return TelegramMessage(
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
    ) -> list[bytes]:
        """Download photos in message-ID order when the channel opts in."""
        if channel_username not in self._image_channels:
            return []

        images: list[bytes] = []
        for message in messages:
            image_bytes = await _download_image_bytes(message)
            if image_bytes is not None:
                images.append(image_bytes)
        return images

    async def _translate_if_configured(
        self,
        text: str | None,
        channel_title: str,
        channel_username: str | None,
    ) -> tuple[str | None, str | None]:
        """Translate optional enrichment without replacing the original text."""
        if text is None or channel_username not in self._translation_channels:
            return None, None

        try:
            translated_text = _sanitize(
                await self._translate_text(text, self._translation_target_language)
            )
        except Exception as exc:
            logger.warning(
                "Translation failed for channel %r: %s. Emitting the original message.",
                channel_title,
                exc,
            )
            translated_text = None

        if translated_text is None:
            return None, None
        return translated_text, self._translation_target_language

    async def _translate_text(self, text: str, target_language: str) -> str:
        """Translate text, retrying only as the configured policy permits."""
        request = functions.messages.TranslateTextRequest(
            text=[types.TextWithEntities(text=text, entities=[])],
            to_lang=target_language,
        )
        for attempt in range(self._policy.translation_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._send_translation_request(request),
                    timeout=self._policy.translation_timeout,
                )
            except FloodWaitError as exc:
                if (
                    not self._policy.retry_flood_waits
                    or attempt == self._policy.translation_retries
                ):
                    raise
                await asyncio.sleep(exc.seconds)
            except (asyncio.TimeoutError, ServerError, TimedOutError):
                if attempt == self._policy.translation_retries:
                    raise
            else:
                if not result.result or not result.result[0].text:
                    raise RuntimeError("Telegram returned no translated text.")
                return result.result[0].text

        raise RuntimeError("Translation retry loop ended unexpectedly.")

    async def _send_translation_request(
        self,
        request: functions.messages.TranslateTextRequest,
    ) -> types.messages.TranslateResult:
        async with self._translation_semaphore:
            return await self._client(request)
