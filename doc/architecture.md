# TelegramGateway architecture

`telegram_gateway` adapts one caller-owned Telethon client into live queue
delivery and bounded historical retrieval. It does not authenticate accounts,
persist data, write JSON, manage a database, perform OCR, or make application
decisions.

```text
TelegramClient
    ├── TelegramListener -> asyncio.Queue[TelegramMessage | None]
    └── TelegramHistory  -> list[TelegramMessage]
                  \-> shared processing and deterministic IDs
```

## Ownership and lifecycle

The caller creates, connects, authorizes, and disconnects `TelegramClient`;
one-time phone-code and 2FA login also stay outside the package. Both
coordinators require an already connected, authorized client and never perform
interactive authentication or disconnect it.

`TelegramListener` registers Telethon new-message and album handlers, then
waits on `run_until_disconnected()`. It produces queue items until shutdown,
when it sends `None`. Telethon owns transport reconnect policy. A bounded full
queue drops an incoming message instead of delaying the update loop. Its
handlers log and isolate processing failures for each event. Errors from the
client cycle in `start()` propagate to the caller, as do errors from
`TelegramHistory`.

`TelegramHistory` uses the same client to fetch each configured channel in
sequence. `fetch(start: int, end: int)` accepts Unix seconds only and returns
all processed logical messages in `[start, end)`, sorted by timestamp, channel
ID, and message ID. It holds that complete result list in memory; persistence
and batching belong to the caller.

## Shared processing, distinct latency policies

`_processing.py` is shared by both coordinators. It repairs Unicode, removes
emoji, resolves cached channel metadata, creates immutable `TelegramMessage`
objects, and assigns each a deterministic 26-character ID from timestamp,
channel ID, and Telegram message ID.

Albums become one logical message: the first item supplies identity and text,
while configured photos are downloaded in message-ID order. Image failures are
logged and skipped without dropping the logical photo message, which may have
an empty `images` tuple. Text remains the sanitized original in `text`; successful
translation is placed in `translated_text` and `translation_language`.

The live coordinator prioritizes latency: translation has a short bounded
timeout, no retries, and fails open. The history coordinator prioritizes a
complete bounded range: it uses Telethon pagination with configurable waits,
can retry translation failures and `FloodWaitError`, then emits the original
message if translation remains unavailable. Translation-specific non-transient
RPC, connection, and OS errors fail open without retries; native authorization,
channel-retrieval, and history-retrieval errors propagate to the caller.

## Files

```text
src/telegram_gateway/
    __init__.py       Public exports
    _listener.py      Live Telethon events to queue
    _history.py       Sequential, bounded channel retrieval
    _processing.py    Shared sanitization, images, translation, IDs
    _models.py        TelegramMessage
    _exceptions.py    Gateway configuration and translation errors
smoke/
    login.py          Explicit one-time session setup
    listener.py       Live queue smoke check
    history.py        Finite history smoke check
```

The smoke scripts are external integration checks. Their local `.env` and
Telethon session files are intentionally outside the package and must not be
committed.
