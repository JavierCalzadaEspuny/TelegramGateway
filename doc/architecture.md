# TelegramListener — Architecture Reference

This document describes the small runtime boundary of the `telegramlistener`
package. It is deliberately focused on streaming messages; authentication and
historical exports belong to the application using the package.

## Purpose

`telegramlistener` receives real-time updates from configured Telegram channels
and places normalized `TelegramStreamedMessage` objects on an
`asyncio.Queue`. It optionally downloads configured photos and asks Telegram to
translate configured text through the same user client.

The package does not perform OCR, persist messages, authenticate accounts, or
implement a historical dataset exporter.

## Repository layout

```text
TelegramListener/
├── src/telegramlistener/
│   ├── __init__.py        # Public API
│   ├── _listener.py       # Client-to-queue adapter
│   ├── _models.py         # TelegramStreamedMessage
│   └── _exceptions.py     # Configuration and translation errors
├── smoke/
│   ├── run.py             # Existing-session runtime smoke test
│   ├── login.py           # Explicit one-shot session setup
│   └── .env.example       # Smoke-test configuration template
├── AGENTS.md              # Maintainer and agent guidance
├── doc/testing.md         # Verification workflow
├── pyproject.toml         # Package metadata and dependencies
└── .gitignore              # Local credentials and build artifacts
```

There is no session-management module. The caller creates a
`TelegramClient`, performs any required one-time login, checks authorization,
and passes the connected client to `TelegramListener`. Telethon 1.45.0 is the
supported version. The `smoke/` scripts are outside the package and exist only
to exercise that boundary with a real account. Their `.env` file is only a
local input layer: credentials and scalar settings remain strings, while
channel settings are JSON arrays converted once at the script boundary.

## Public API

```python
from telegramlistener import (
    ConfigurationError,
    TelegramListener,
    TelegramListenerError,
    TelegramStreamedMessage,
    TranslationError,
)
```

The main constructor is:

```python
TelegramListener(
    client=authorized_client,
    channels=[...],
    image_channels=[...],
    translation_channels=[...],
    translation_target_language="en",
    translation_timeout=3.0,
    translation_max_concurrency=2,
    queue_maxsize=0,
)
```

`client` must already be connected and authorized. The listener does not call
`connect()`, `start()`, `sign_in()`, or `is_user_authorized()`.

Configuration is validated once in the constructor and channel names are kept
exactly as supplied. Channel configuration is immutable for the lifetime of the
instance, and listener instances are single-use.

## Client lifecycle

The caller owns credentials and constructs the client with native Telethon
connection options:

```python
async with TelegramClient(
    session_path,
    api_id,
    api_hash,
    auto_reconnect=True,
) as client:
    if not await client.is_user_authorized():
        raise RuntimeError("Manual login required")

    listener = TelegramListener(client=client, channels=["cnn"])
    await listener.start()
```

The caller then creates the listener and starts it. `start()` registers the
event handlers and awaits `client.run_until_disconnected()` once. Telethon
owns transient transport reconnection using the options supplied to the
client. If Telethon cannot reconnect after its configured attempts, the error
propagates to the caller. The listener never disconnects the client supplied by
the caller.

The listener does not add a retry loop, exponential backoff, jitter, polling
health check, or session cleanup policy. A process supervisor may restart the
application after an unrecoverable error.

The listener does not enable Telethon's `catch_up` mode. Replaying updates that
arrived while the client was offline is an explicit application policy and is
separate from this real-time queue contract.

When the listener finishes, it places `None` on the queue as the shutdown
sentinel. If a bounded queue is full, it drops one buffered item to guarantee
that the sentinel can be delivered. The caller's `TelegramClient` context
manager disconnects the client after the listener returns.

## Event flow

```text
TelegramClient update
        │
        ├── NewMessage ──┐
        │                ├── normalize/enrich ──┐
        └── Album ───────┘                      │
                                                ▼
                              TelegramStreamedMessage
                                                │
                                                ▼
                                         asyncio.Queue
```

`events.NewMessage` handles individual messages. Individual events with a
`grouped_id` are ignored because `events.Album` delivers the complete album.
The album handler uses the first message for text and metadata and collects
configured photos from all messages in the album.

Each handler catches and logs errors local to one incoming event. A malformed
message or failed image download therefore does not terminate the update loop.

## Message processing

For each accepted event the listener:

1. resolves and caches channel title and username by chat ID;
2. repairs Unicode text with `ftfy`;
3. removes emoji and surrounding whitespace;
4. downloads photos only when the configured channel is in
   `image_channels`;
5. translates text only when the channel is in `translation_channels`;
6. builds an immutable `TelegramStreamedMessage`;
7. calls `queue.put_nowait()`;
8. logs processing timings and whether the item was queued.

Messages with neither text nor configured images are discarded. A full bounded
queue drops the incoming item and logs `queued=False`; the producer never
waits on a slow consumer.

## Data model

`TelegramStreamedMessage` is a frozen dataclass with:

| Field | Meaning |
|---|---|
| `id` | Generated time-sortable ULID. |
| `timestamp` | Original Telegram message timestamp in Unix seconds. |
| `channel_title` | Human-readable channel title. |
| `channel_username` | Channel username when Telegram exposes one. |
| `channel_id` | Numeric Telegram channel identifier. |
| `text` | Sanitized original text or caption. |
| `images` | Immutable tuple of downloaded photo bytes. |
| `translated_text` | Optional translated text. |
| `translation_language` | Target language when translation exists. |

The original text is never replaced by its translation. Consumers decide which
field to index, display, persist, or process.

## Translation

`_translate_text()` invokes Telegram's raw
[`messages.translateText`](https://core.telegram.org/method/messages.translateText)
request through the same `TelegramClient` used for updates. It does not create a
second client.

Translation is bounded by a semaphore and a total timeout that includes
waiting for capacity. Empty text is rejected locally. RPC errors, timeouts,
malformed responses, and connection failures become `TranslationError`; the
automatic handler logs the failure and still emits the original message.

Translation is intentionally one message at a time. Batching would require
buffering and would change the real-time queue contract.

## Telemetry

For each event reaching the enqueue step, the listener logs:

- `processing_ms`: total listener processing time;
- `translation_ms`: translation attempt time, when applicable;
- `image_download_ms`: time spent on actual configured photo downloads;
- `queued`: whether the item entered the queue.

The per-message timing line is logged at `DEBUG`; startup and operational
warnings use `INFO` or `WARNING`. The package does not retain metric history or
calculate aggregates.

## Error boundary

`TelegramListenerError` is the base for package-level errors. The package
raises `ConfigurationError` for invalid fixed configuration and uses
`TranslationError` internally for fail-open translation handling. Native
Telethon connection and authentication errors are not converted or retried by
the listener; the caller owns the process-level policy for those failures.

## Design invariants

- The listener is a thin client-to-queue adapter.
- Authentication is explicit and outside the listener.
- Runtime code never prompts for a phone code or 2FA password.
- Telethon is the only owner of transport reconnection.
- The output model always preserves the sanitized original text.
- Albums are emitted once, with their configured photos grouped together.
- Slow consumers cannot block the Telethon update loop.
- No historical retrieval or dataset export is hidden inside the real-time path.
