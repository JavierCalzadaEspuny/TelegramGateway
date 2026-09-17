# Historical retrieval

`TelegramHistory` retrieves a complete, bounded set of channel messages with a
caller-owned, already connected and authorized `TelegramClient`. It does not
log in, write JSON, store a database record, run OCR, or persist the returned
messages.

```python
from telegram_gateway import TelegramHistory

history = TelegramHistory(
    client=client,
    channels=["AjaNews", "almayadeen"],
    image_channels=["AjaNews"],
    translation_channels=["almayadeen"],
    translation_target_language="en",
    translation_timeout=30.0,
    translation_max_concurrency=1,
    translation_retries=2,
    history_wait_time=1.0,
)
messages = await history.fetch(start=1_767_225_600, end=1_767_312_000)
```

## Range contract

`fetch(start: int, end: int)` accepts non-negative Unix seconds only. The range
is half-open: it includes messages where `start <= timestamp < end`. `start`
must be earlier than `end`.

The caller must pass a connected client. `fetch()` checks this before validating
the range or retrieving channels and raises `RuntimeError` if it is disconnected.

Convert human dates, time zones, and calendar boundaries in the calling
application before calling `fetch`. This avoids ambiguous date parsing in the
library and makes adjacent range queries non-overlapping:

```text
[start, end) then [end, next_end)
```

## Retrieval and processing

Channels are retrieved sequentially. For each channel, Telethon paginates in
its native descending order from the exclusive end boundary and uses
`history_wait_time` between requests. TelegramGateway filters the half-open
range locally and stops once it reaches a message older than `start`. After
processing, it sorts the complete result by timestamp, channel ID, and
Telegram message ID.

Adjacent Telegram album items are grouped into one `TelegramMessage`. The
first item supplies the ID, timestamp, channel metadata, and text; all photos
are considered in message-ID order. Photo bytes are downloaded only when the
channel is in `image_channels`. A failed download is logged and does not remove
the logical message; a photo-only message therefore remains available with an
empty `images` tuple when downloads are disabled or unavailable.

Text is Unicode-repaired and emoji-stripped. Translation is requested only for
`translation_channels`; `text` always remains the sanitized original, while a
successful translation appears in `translated_text` and
`translation_language`. Every result has a deterministic 26-character ID, so
the same Telegram source message has the same ID in live and historical flows.

## Translation, waits, and errors

History is deliberately slower than live processing. Its translation timeout,
concurrency, retry count, and Telethon pagination wait are configurable.
Translation timeouts, transient Telethon server failures, and ordinary
translation-provider failures are retried up to `translation_retries`, then
fail open with the original text. On `FloodWait`, history waits for Telegram's
requested duration and retries under that same limit; an exhausted FloodWait
also produces the original message without a translation. A non-transient
translation `RPCError`, `ConnectionError`, or `OSError` is logged and fails
open immediately without a retry. Authorization, configuration, channel
resolution, and history-retrieval failures are not enrichment failures and
propagate to the caller.

Image-download failures and translation failures are local enrichment failures
and preserve the message. Invalid configuration and ranges raise
`ConfigurationError`. Failures resolving a channel or retrieving its history
are not hidden; they propagate to the caller, which owns retry, restart, and
persistence policy.

## Memory and persistence

`fetch()` returns a full `list[TelegramMessage]`, including any downloaded
image bytes. Memory therefore grows with the requested time range, number of
channels, message volume, and image size. Choose bounded ranges and persist,
stream onward, or batch the returned data in the calling application. The
package intentionally has no storage layer.
