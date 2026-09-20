# History

`TelegramHistory` retrieves a finite range from configured channels:

```python
from telegram_gateway import TelegramHistory, TelegramSession

async with TelegramSession() as client:
    history = TelegramHistory(
        client,
        channels,
        image_channels=(),
        translation_channels=(),
        translation_target_language="en",
        translation_timeout=30.0,
        translation_retries=2,
        history_wait_time=1.0,
    )
    messages = await history.fetch(start=..., end=..., show_progress=False)
```

The client must already be connected and authorized. `TelegramSession` is the
standard owner, though any compatible connected client can be supplied.
History never logs in or disconnects it. Create a new instance when its fixed
channels or processing options change.

## Range and retrieval

`start` and `end` are non-negative Unix seconds. The range is half-open:
`start <= timestamp < end`. Both values must fit the timestamp portion of the
deterministic message ID, and `start` must be earlier than `end`.

Channels are fetched sequentially with Telethon pagination and
`history_wait_time`. Retrieval starts at the exclusive end and stops after
reaching a message older than the start. The complete result is sorted by
timestamp, channel ID, and Telegram message ID.

`show_progress=True` displays one `tqdm` bar. Its total is the requested time
interval multiplied by the number of channels. It estimates temporal coverage,
not message count. The default is silent.

## Messages, albums, images, and translation

Adjacent items with the same Telegram album ID become one `TelegramMessage`.
The first item by message ID supplies identity and text; configured photos are
downloaded in message-ID order.

Image failures are logged and preserve the logical message. Translation runs
only for `translation_channels`; successful output is stored separately from
the original text.

History retries translation timeouts and transient Telegram server failures up
to `translation_retries`. It also waits for Telegram `FloodWait` durations
before retrying. Other translation failures are logged without a retry. Any
translation failure preserves the original message.

Channel resolution, authorization, and history retrieval failures propagate to
the caller.

## Memory

`fetch()` returns one complete list, including downloaded image bytes. Memory
therefore grows with range size, channel volume, and image size. Choose bounded
ranges and persist or batch results in the calling application.
