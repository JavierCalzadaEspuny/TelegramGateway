"""Historical Telegram channel retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.tl.custom.message import Message
from tqdm import tqdm

from ._models import TelegramMessage
from ._processing import (
    MessageProcessor,
    ProcessingPolicy,
    _normalize_target_language,
    _validate_channels,
    _validate_channel_subset,
    _validate_non_negative_integer,
    _validate_positive_number,
)

_MAX_UNIX_SECONDS = ((1 << 48) - 1) // 1000


def _validate_unix_range(start: object, end: object) -> tuple[int, int]:
    """Validate the public Unix-second, half-open history range."""
    validated_start = _validate_non_negative_integer(start, parameter="start")
    validated_end = _validate_non_negative_integer(end, parameter="end")
    if validated_start > _MAX_UNIX_SECONDS or validated_end > _MAX_UNIX_SECONDS:
        raise ValueError(
            "start and end must fit the deterministic ULID timestamp range."
        )
    if validated_start >= validated_end:
        raise ValueError("start must be earlier than end.")
    return validated_start, validated_end


class TelegramHistory:
    """Fetch normalized Telegram channel messages within a Unix-second range."""

    def __init__(
        self,
        client: TelegramClient,
        channels: Sequence[str],
        *,
        image_channels: Sequence[str] = (),
        translation_channels: Sequence[str] = (),
        translation_target_language: str = "en",
        translation_timeout: float = 30.0,
        translation_retries: int = 2,
        history_wait_time: float = 1.0,
    ) -> None:
        monitored_channels = _validate_channels(
            channels,
            parameter="channels",
            allow_empty=False,
        )
        downloaded_image_channels = _validate_channel_subset(
            image_channels,
            monitored_channels,
            parameter="image_channels",
        )
        translated_channels = _validate_channel_subset(
            translation_channels,
            monitored_channels,
            parameter="translation_channels",
        )

        normalized_timeout = _validate_positive_number(
            translation_timeout,
            parameter="translation_timeout",
        )

        self._client = client
        self._channels = monitored_channels
        self._history_wait_time = _validate_positive_number(
            history_wait_time,
            parameter="history_wait_time",
        )
        self._processor = MessageProcessor(
            client=client,
            image_channels=downloaded_image_channels,
            translation_channels=translated_channels,
            translation_target_language=_normalize_target_language(
                translation_target_language
            ),
            policy=ProcessingPolicy(
                translation_timeout=normalized_timeout,
                translation_max_concurrency=1,
                translation_retries=_validate_non_negative_integer(
                    translation_retries,
                    parameter="translation_retries",
                ),
                retry_flood_waits=True,
            ),
        )

    async def fetch(
        self,
        *,
        start: int,
        end: int,
        show_progress: bool = False,
    ) -> list[TelegramMessage]:
        """Return every configured channel message in ``[start, end)``."""
        if not self._client.is_connected():
            raise RuntimeError(
                "Telegram client must be connected before fetching history."
            )
        start_seconds, end_seconds = _validate_unix_range(start, end)
        try:
            end_utc = datetime.fromtimestamp(end_seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(
                "History range is outside the supported UTC datetime range."
            ) from exc
        messages: list[TelegramMessage] = []
        interval = end_seconds - start_seconds
        total = len(self._channels) * interval

        with tqdm(
            total=total,
            desc="History",
            dynamic_ncols=True,
            disable=not show_progress,
        ) as progress:
            for channel_index, channel in enumerate(self._channels):
                entity = await self._client.get_entity(channel)
                await self._fetch_channel(
                    entity,
                    start=start_seconds,
                    end=end_seconds,
                    end_utc=end_utc,
                    messages=messages,
                    progress=progress,
                    progress_offset=channel_index * interval,
                )
                progress.update((channel_index + 1) * interval - progress.n)

        messages.sort(
            key=lambda message: (
                message.timestamp,
                message.channel_id,
                message.message_id,
            )
        )
        return messages

    async def _fetch_channel(
        self,
        entity: object,
        *,
        start: int,
        end: int,
        end_utc: datetime,
        messages: list[TelegramMessage],
        progress: tqdm,
        progress_offset: int,
    ) -> None:
        """Process one channel's historical stream in iterator order."""
        album: list[Message] = []
        album_id: int | None = None

        async for message in self._client.iter_messages(
            entity,
            offset_date=end_utc,
            wait_time=self._history_wait_time,
        ):
            timestamp = int(message.date.timestamp())
            if timestamp < start:
                await self._flush(album, messages)
                break
            if not start <= timestamp < end:
                continue

            completed = progress_offset + end - max(start, min(timestamp, end))
            progress.update(completed - progress.n)

            grouped_id = message.grouped_id
            if grouped_id is None:
                await self._flush(album, messages)
                album_id = None
                await self._process([message], messages)
            elif album and grouped_id == album_id:
                album.append(message)
            else:
                await self._flush(album, messages)
                album = [message]
                album_id = grouped_id

        await self._flush(album, messages)

    async def _flush(
        self,
        album: list[Message],
        messages: list[TelegramMessage],
    ) -> None:
        """Process one completed adjacent album, if present."""
        if album:
            await self._process(album, messages)
            album.clear()

    async def _process(
        self,
        source_messages: Sequence[Message],
        messages: list[TelegramMessage],
    ) -> None:
        """Append one processed logical message."""
        message = await self._processor.process(source_messages)
        if message is not None:
            messages.append(message)
