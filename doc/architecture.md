# TelegramListener — Architecture Reference

This document is a complete reference for the `telegramlistener` library. It is intended to give a future agent (or developer) a full understanding of how the codebase works without needing to read the source first.

---

## Purpose

`telegramlistener` is a Python library that listens to public Telegram channels in real time and streams their messages into an `asyncio.Queue`. Consumers read `TelegramStreamedMessage` objects from the queue at their own pace. The library handles session authentication, reconnection with exponential backoff, text sanitization, optional Telegram-backed translation, images, albums, and backpressure.

---

## Repository layout

```
TelegramListener/
├── src/telegramlistener/
│   ├── __init__.py        # Public API surface
│   ├── _listener.py       # TelegramListener — core streaming class
│   ├── _session.py        # SessionManager — auth lifecycle
│   ├── _models.py         # TelegramStreamedMessage
│   └── _exceptions.py     # Library exception hierarchy
├── example.py             # End-to-end usage script
├── AGENTS.md              # Repository rules for maintainers and agents
├── doc/testing.md         # Smoke-test and temporary-test workflow
├── pyproject.toml         # Package metadata, deps, tool config
└── .env.example           # Required environment variables
```

All public symbols are re-exported from `__init__.py`:
`SessionManager`, `TelegramListener`, `TelegramStreamedMessage`, `TelegramListenerError`, `SessionError`, `ConfigurationError`, `TranslationError`.

---

## Data models (`_models.py`)

---

### `TelegramStreamedMessage`

A frozen dataclass produced by `TelegramListener` for every incoming message.

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | `int` | Unix timestamp (UTC seconds) of the original Telegram message. |
| `channel_title` | `str` | Human-readable channel title (e.g. `"Al Jazeera"`). |
| `channel_username` | `str \| None` | Telegram channel username when available. |
| `channel_id` | `int` | Numeric Telegram channel identifier. Negative for channels/supergroups. |
| `text` | `str \| None` | Sanitized original text or caption. |
| `images` | `tuple[bytes, ...]` | Immutable attached photos downloaded into memory when the channel is configured in `image_channels`. |
| `translated_text` | `str \| None` | Optional translation of `text`. |
| `translation_language` | `str \| None` | ISO 639-1 target language when a translation is present. |
| `id` | `str` | Auto-generated time-sortable ULID (26 chars). Not set via `__init__`. |

`id` is created in `__post_init__` via `ulid.ULID()`. Because ULIDs embed a millisecond timestamp, messages can be sorted by `id` to recover arrival order.

The `__repr__` includes the original and translated text fields as stored on the
message, together with channel metadata and the number of downloaded images.

---

## Exceptions (`_exceptions.py`)

```
TelegramListenerError          ← catch-all base
├── SessionError               ← missing/revoked session; call run_manual_login()
├── ConfigurationError         ← invalid listener or translation configuration
└── TranslationError           ← Telegram cannot complete a requested translation
```

---

## Session management (`_session.py`)

### `SessionManager`

Owns all authentication logic. `TelegramListener` delegates auth entirely to this class.

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_id` | `int` | required | From https://my.telegram.org |
| `api_hash` | `str` | required | From https://my.telegram.org |
| `phone` | `str` | required | International format, e.g. `"+34612345678"` |
| `session_name` | `str` | `"telegram"` | Stem of the `.session` file |
| `session_dir` | `Path \| None` | `~/.cache/telegramlistener/` | Directory for session files |

Session files are Telethon SQLite databases. The full path on disk is `{session_dir}/{session_name}.session`. The directory is created automatically if missing.

**Key methods:**

#### `is_operational() -> bool` (async)

1. Returns `False` immediately if the `.session` file does not exist.
2. Connects a fresh `TelegramClient` and calls `is_user_authorized()`.
3. If authorization returns `False`, or a fatal error (`AuthKeyDuplicatedError`, `AuthKeyUnregisteredError`, `UserDeactivatedError`) is raised, the session file is deleted (`_cleanup()`) and `False` is returned.
4. Any other exception is treated as a transient health-check failure, returns
   `False`, and preserves the session file.
5. Returns `True` only when the session is confirmed valid.

#### `run_manual_login()` (async)

Interactive terminal login flow. Wraps `TelegramClient.start(phone=...)`, which handles SMS code and optional 2FA password prompts. Call this **once** before the first `TelegramListener.start()`. If the session is already valid, it is a no-op. On failure, the session file is cleaned up and `SessionError` is raised.

#### `get_authorized_client() -> TelegramClient` (async)

Creates one client, connects it, verifies authorization on that same connection,
and returns it connected. It does not call `is_operational()` first or open a
second validation connection. Raises `SessionError` if no valid session exists.
The caller is responsible for calling `client.disconnect()` when done.

#### `session_file -> Path` (property)

Read-only path to the `.session` file on disk.

---

## Core listener (`_listener.py`)

### `TelegramListener`

Registers a Telethon event handler, feeds messages into an `asyncio.Queue`, and manages the connection lifecycle.

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_manager` | `SessionManager` | required | An authorized session manager |
| `channels` | `Sequence[str]` | required | Channel usernames to monitor |
| `image_channels` | `Sequence[str]` | `()` | Monitored channels whose photos to download |
| `translation_channels` | `Sequence[str]` | `()` | Monitored channels to translate |
| `translation_target_language` | `str` | `"en"` | Two-letter ISO 639-1 target language |
| `translation_timeout` | `float` | `3.0` | Maximum total seconds per translation |
| `translation_max_concurrency` | `int` | `2` | Maximum simultaneous translations |
| `queue_maxsize` | `int` | `0` (unbounded) | Maximum messages buffered in `queue` |

**Public attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `queue` | `asyncio.Queue[TelegramStreamedMessage \| None]` | Consumers read from this. `None` is the shutdown sentinel. |

---

### Lifecycle

```
TelegramListener(...)      ← complete, immutable configuration
        │
        ▼
    start()                ← blocks; registers handlers, runs reconnect loop
        │
   (running)
        │
  stop() / aclose()        ← graceful shutdown
```

Channel configuration is supplied once to the constructor. Usernames are
normalized by stripping whitespace, an optional leading `@`, and capitalization.
Duplicates are removed while preserving order. Translation channels must be a
subset of monitored channels. Listener instances are single-use; create a new
listener to change configuration or restart after shutdown.

**`start()` (async, blocking)**

1. Obtains an authorized client via `SessionManager.get_authorized_client()`.
2. Registers `_on_new_message` and `_on_album` as Telethon event handlers, scoped to the configured channel usernames.
3. Enters the reconnect loop:
   - Calls `client.run_until_disconnected()`.
   - On **fatal errors** (`AuthKeyDuplicatedError`, `AuthKeyUnregisteredError`, `UserDeactivatedError`): cleans up the invalid session and raises `SessionError`; no automatic login or retry is started.
   - On **any other exception**: computes backoff delay = `min(60, 2^attempt) + jitter(0–1 s)`, waits, then reconnects the existing client if needed.
   - Exits the loop when `stop()` / `aclose()` sets `_stop_event`.
5. A `finally` block clears runtime state, disconnects the client, and puts
   `None` on the queue. This also runs after cancellation or setup failure. If a
   bounded queue is full, one buffered item is dropped so shutdown cannot block.

**Reconnect backoff:**

| Attempt | Base delay | Cap |
|---------|-----------|-----|
| 1 | 2 s | — |
| 2 | 4 s | — |
| 3 | 8 s | — |
| … | 2^n s | 60 s |

Each delay also has `random.uniform(0, 1)` seconds of jitter to avoid thundering herds.

**`stop()`** (sync)

Sets `_stop_event` and fires `client.disconnect()` as a background task via `asyncio.create_task`. Returns immediately — shutdown is asynchronous. Use when you cannot `await`.

**`aclose()`** (async)

Sets `_stop_event` and `await`s `client.disconnect()`. Guarantees the client is disconnected before returning. Prefer this over `stop()`. Automatically called by the `async with` context manager.

**Context manager:**

```python
async with TelegramListener(manager, channels=["ajanews"]) as listener:
    ...
# aclose() is called automatically on exit
```

---

### Message handlers (`_on_new_message`, `_on_album`)

Called by Telethon for every new message in the monitored channels.

1. Ignores individual events that belong to an album; `_on_album` handles the complete group.
2. Strips and sanitizes text via `_sanitize()` (unicode fix + emoji removal).
3. Downloads attached photos into memory only for channels in `image_channels`. Messages with neither text nor configured images are discarded.
4. Looks up and caches chat title and username by `chat_id`.
5. If the normalized username is configured for translation and text is present, calls the listener's private `_translate_text()` before constructing the output model.
6. On translation failure, logs a warning and continues with the original text and `translated_text=None`.
7. Constructs a frozen `TelegramStreamedMessage` and calls `queue.put_nowait(msg)`.
8. If the queue is full (`asyncio.QueueFull`), the message is **dropped** (not blocked) and a warning is logged. This preserves the Telethon event loop.
9. Any other unhandled exception is caught and logged; the handler never raises.

For every message that reaches the enqueue step, the listener logs individual
timings at `INFO`: total `processing_ms`, Telegram translation
`translation_ms` when applicable, and image `image_download_ms`. The image
measurement covers only actual configured image-download attempts; metadata
resolution and channel-filter checks are excluded. These are per-message
measurements only; the library does not aggregate averages or percentiles.

---

### Text sanitization

```python
def _sanitize(text: str) -> str:
    return emoji.replace_emoji(ftfy.fix_text(text), replace="").strip()
```

- `ftfy.fix_text`: fixes mojibake, wrong encoding, bad Unicode.
- `emoji.replace_emoji(..., replace="")`: removes all emoji characters.
- `.strip()`: trims surrounding whitespace.

Both original and translated strings pass through `_sanitize()` before reaching consumers. `text` is never replaced by the translation.

---

## Translation inside the listener (`_listener.py`)

`TelegramListener._translate_text()` calls Telethon's raw
[`messages.translateText`](https://core.telegram.org/method/messages.translateText)
request directly on the listener's active `TelegramClient`. There is no separate
translator object, service, or Telegram connection. Telegram detects the source
language, so the request only contains the plain text and target language.

Operational safeguards:

- Concurrency is configurable and defaults to two requests.
- The configurable timeout defaults to three seconds and includes both waiting
  for capacity and the Telegram RPC.
- Empty input is rejected locally without calling Telegram.
- Telegram RPC errors, timeouts, connection failures, and empty responses become `TranslationError`.
- Automatic channel translation catches `TranslationError` and emits the original message.

The automatic path translates one incoming message at a time. Telegram's batch capability is intentionally not used because the listener emits real-time events independently; batching would introduce an additional buffering delay and alter the queue contract.

---

## Public API surface

```python
from telegramlistener import (
    SessionManager,
    TelegramListener,
    TelegramStreamedMessage,
    TelegramListenerError,
    SessionError,
    ConfigurationError,
    TranslationError,
)
```

---

## Typical usage pattern

```python
import asyncio
from telegramlistener import SessionManager, TelegramListener

async def consume(queue):
    while True:
        msg = await queue.get()
        if msg is None:          # shutdown sentinel
            break
        print(msg)
        queue.task_done()

async def main():
    manager = SessionManager(
        api_id=12345,
        api_hash="abc...",
        phone="+34612345678",
    )

    # The session must be authorized explicitly before starting the listener.

    async with TelegramListener(
        session_manager=manager,
        channels=[
            "cnn",
            "ajanews",
        ],
        translation_channels=["ajanews"],
        translation_target_language="en",
        translation_timeout=3.0,
        queue_maxsize=1000,
    ) as listener:
        consumer = asyncio.create_task(consume(listener.queue))
        try:
            await listener.start()   # blocks until stopped or session invalid
        finally:
            consumer.cancel()

asyncio.run(main())
```

---

## Environment variables and example configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_API_ID` | yes | Numeric API ID from my.telegram.org |
| `TELEGRAM_API_HASH` | yes | API hash from my.telegram.org |
| `TELEGRAM_PHONE` | yes | Phone number in international format |
| `TELEGRAM_SESSION_NAME` | no | Session file stem (default: `telegram`) |

The channel lists and typed listener settings used by `example.py` are ordinary
Python values at the top of that file:

```python
CHANNELS: list[str] = ["AjaNews", "almayadeen", "SabrenNewss"]
IMAGE_CHANNELS: list[str] = []
TRANSLATION_CHANNELS: list[str] = [
    "AjaNews",
    "almayadeen",
    "SabrenNewss",
]
TRANSLATION_TARGET_LANGUAGE = "en"
TRANSLATION_TIMEOUT = 3.0
TRANSLATION_MAX_CONCURRENCY = 2
QUEUE_MAXSIZE = 1000
```

`.env` is intentionally limited to credentials and session settings. It does
not parse channel lists from comma-separated strings.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `telethon >= 1.36` | Telegram MTProto client |
| `ftfy >= 6.0` | Unicode text repair |
| `emoji >= 2.1` | Emoji detection and removal |
| `python-ulid >= 3.1` | Time-sortable unique IDs for messages |
| `python-dotenv` | (optional, examples only) Load `.env` files |

Python 3.10+ required. Tested on 3.10, 3.11, 3.12.

---

## Key design decisions

**Session isolation.** `SessionManager` owns all auth state. `TelegramListener`
never touches credentials directly; it obtains one authorized client from the
manager. Session handling can be replaced or tested without changing the
listener.

**Queue-based output.** Using `asyncio.Queue` decouples message production from consumption. Consumers can be slow, concurrent, or replaceable at runtime. The `queue_maxsize=0` default is unbounded, so callers must set a bound if they cannot guarantee keeping up.

**Drop-on-full backpressure.** `put_nowait` + warning is chosen over `await queue.put()` to avoid blocking the Telethon event loop. Messages are lost rather than stalling the connection.

**Sentinel for shutdown.** `None` is placed on the queue when the listener stops. Consumers should check for `None` to detect end-of-stream cleanly.

**Automatic reconnection.** Transient connection errors trigger exponential backoff (2^n seconds, capped at 60 s, plus uniform jitter). Fatal auth errors bypass the retry loop entirely and stop the listener.

**Lazy chat metadata.** `_chat_meta` is populated on first message per `chat_id`. This avoids upfront API calls for all channels at startup and keeps `start()` fast.

**Text normalization.** All messages are Unicode-repaired and emoji-stripped before reaching the queue. Non-Latin scripts such as Arabic remain intact for translation and downstream processing.

**Opt-in translation.** Translation is disabled when `translation_channels` is
empty. All configuration is constructor-based and fixed for the listener's
lifetime, keeping runtime state transitions out of the public API.

**Original text preservation.** `text` always contains the sanitized Telegram source. Translation is stored separately in `translated_text` with its `translation_language`, so downstream consumers decide which representation to search, display, or persist.

**Shared Telegram connection.** Translation uses the same authorized user client as event streaming. It does not open a second session and does not add a third-party API dependency.

**Graceful degradation.** Translation is enrichment, not a delivery requirement. Quota errors, timeouts, malformed responses, and connection failures are logged; the original message still reaches the output queue.
