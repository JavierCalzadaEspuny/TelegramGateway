"""Data models."""

from __future__ import annotations

from dataclasses import dataclass, field

import ulid


@dataclass(frozen=True)
class TelegramStreamedMessage:
    """An immutable, normalized message received from a monitored channel.

    Produced by :class:`TelegramListener` and placed on its ``queue``.

    Attributes:
        timestamp: Unix timestamp (UTC seconds) of the original Telegram message.
        channel_title: Human-readable Telegram channel title.
        channel_username: Telegram channel username/slug when available.
        channel_id: Numeric Telegram channel identifier.
        text: Sanitized message text — unicode-fixed, emoji-stripped, or None when
            the message has no text/caption.
        images: Immutable tuple of in-memory binary payloads for attached
            photos. The tuple may be empty when the message has no images.
        translated_text: Optional translation of ``text``. ``None`` when the
            channel is not configured for translation or translation failed.
        translation_language: ISO 639-1 target language used for
            ``translated_text``, or ``None`` when no translation is available.
        id: Time-sortable ULID string (26 characters), unique per instance.

    Example:
        >>> msg = TelegramStreamedMessage(
        ...     timestamp=1700000000,
        ...     channel_title="Al Jazeera",
        ...     channel_username="aljazeera",
        ...     channel_id=-1001234567890,
        ...     text="Breaking news...",
        ...     images=(),
        ...     translated_text="Últimas noticias...",
        ...     translation_language="es",
        ... )
        >>> len(msg.id)
        26
    """

    id: str = field(init=False)
    timestamp: int
    channel_title: str
    channel_username: str | None
    channel_id: int
    text: str | None
    images: tuple[bytes, ...] = ()
    translated_text: str | None = None
    translation_language: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(ulid.ULID()))
        object.__setattr__(self, "images", tuple(self.images))

    def __repr__(self) -> str:
        return (
            f"TelegramStreamedMessage("
            f"id={self.id!r}, "
            f"channel_title={self.channel_title!r}, "
            f"channel_username={self.channel_username!r}, "
            f"channel_id={self.channel_id!r}, "
            f"timestamp={self.timestamp}, "
            f"text={self.text!r}, "
            f"translated_text={self.translated_text!r}, "
            f"translation_language={self.translation_language!r}, "
            f"images={len(self.images)})"
        )
