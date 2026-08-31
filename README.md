# TelegramListener

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Stream Telegram channel messages to an asyncio queue. One coroutine produces; you consume.

---

## Install

```bash
pip install git+https://github.com/Cerval/TelegramListener.git
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add git+https://github.com/Cerval/TelegramListener.git
```

---

## Quick Start

```python
from telegramlistener import SessionManager, TelegramListener

manager = SessionManager(api_id=..., api_hash=..., phone="+34612345678")

# The session must have been authorized explicitly before this point.

async with TelegramListener(
    session_manager=manager,
    channels=["cnn", "ajanews"],
    translation_channels=["ajanews"],
    translation_target_language="en",
) as listener:
    await listener.start()                    # blocks; messages arrive on listener.queue
```

`TelegramListener` never starts an interactive login. Run
`await manager.run_manual_login()` explicitly, while you are present to enter
the SMS code or 2FA password, before the first listener run. If the session is
missing or revoked, the listener logs an error and exits without retrying login.

---

## Migrating from 0.1

Version 0.2 replaces runtime setters with constructor-only configuration. Move
the values previously passed to `set_channels()` and
`set_translation_channels()` into `TelegramListener(...)`. Listener instances
are intentionally single-use; create a new instance to change channels or
restart after shutdown.

---

## Consuming Messages

`listener.queue` is a standard
`asyncio.Queue[TelegramStreamedMessage | None]`. Run a consumer concurrently:

```python
async def consume(queue: asyncio.Queue) -> None:
    while True:
        msg = await queue.get()
        if msg is None:
            queue.task_done()
            break
        print(f"{msg.channel_title}: {msg.text}")
        if msg.translated_text:
            print(f"Translation ({msg.translation_language}): {msg.translated_text}")
        queue.task_done()

async with TelegramListener(
    session_manager=manager,
    channels=["cnn", "ajanews"],
    translation_channels=["ajanews"],
) as listener:
    consumer = asyncio.create_task(consume(listener.queue))
    try:
        await listener.start()
    finally:
        consumer.cancel()
```

---

## API Reference

### `SessionManager`

Manages Telethon session lifecycle: validation, interactive login, and cleanup.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_id` | `int` | — | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `api_hash` | `str` | — | Telegram API hash |
| `phone` | `str` | — | Phone number in international format, e.g. `"+34612345678"` |
| `session_name` | `str` | `"telegram"` | Filename stem for the `.session` file |
| `session_dir` | `Path \| None` | `~/.cache/telegramlistener/` | Directory for session files |

| Method | Returns | Description |
|--------|---------|-------------|
| `await is_operational()` | `bool` | `True` if authorized; preserves the session on transient errors |
| `await run_manual_login()` | `None` | Interactive terminal login; persists session |
| `await get_authorized_client()` | `TelegramClient` | Connected client; raises `SessionError` if no session |

`is_operational()` returns `False` for a temporary connection or Telegram error
without deleting the session file. The file is cleaned up only after Telegram
confirms that the session is unauthorized, revoked, or otherwise fatally invalid.

---

### `TelegramListener`

Streams new messages from configured channels into `listener.queue`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_manager` | `SessionManager` | — | Authorized session manager |
| `channels` | `Sequence[str]` | — | Channel usernames to monitor |
| `image_channels` | `Sequence[str]` | `()` | Monitored channels whose photos to download |
| `translation_channels` | `Sequence[str]` | `()` | Monitored channels to translate |
| `translation_target_language` | `str` | `"en"` | Two-letter ISO 639-1 target language |
| `translation_timeout` | `float` | `3.0` | Maximum total seconds per translation |
| `translation_max_concurrency` | `int` | `2` | Maximum simultaneous translations |
| `queue_maxsize` | `int` | `0` | Maximum buffered messages; `0` means unbounded |

| Attribute / Method | Description |
|--------------------|-------------|
| `queue` | `asyncio.Queue[TelegramStreamedMessage \| None]` — consume from here; `None` marks shutdown |
| `await start()` | Start once and block. Reconnects automatically on failures |
| `await aclose()` | Graceful shutdown, disconnects client |
| `stop()` | Fire-and-forget shutdown (use `aclose()` when you can await) |
| `async with listener:` | Calls `aclose()` on exit automatically |

---

### `TelegramStreamedMessage`

Immutable message object. Every instance has a time-sortable ULID `id`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Time-sortable ULID (26 chars), auto-generated |
| `timestamp` | `int` | Unix timestamp (UTC seconds) of the original message |
| `channel_title` | `str` | Human-readable channel title |
| `channel_username` | `str \| None` | Telegram channel username/slug when available |
| `channel_id` | `int` | Numeric Telegram channel identifier |
| `text` | `str \| None` | Sanitized text — unicode-fixed, emoji-stripped, or `None` when no text/caption is present |
| `images` | `tuple[bytes, ...]` | Immutable attached images; empty when there are none |
| `translated_text` | `str \| None` | Translation of `text`, or `None` when unavailable or not requested |
| `translation_language` | `str \| None` | ISO 639-1 target language for `translated_text`, or `None` |

## Message Shape

The listener normalizes every message into this shape:

- `timestamp`: always present.
- `channel_title`: always present.
- `channel_username`: present when Telegram exposes a channel username.
- `channel_id`: always present.
- `id`: always present.
- `text`: either a sanitized string or `None`.
- `images`: always an immutable tuple, possibly empty.
- `translated_text`: translated text when requested successfully; otherwise `None`.
- `translation_language`: target language when a translation is present; otherwise `None`.

That means these cases are all valid:

- text only: `text="hello"`, `images=()`
- images only: `text=None`, `images=(...)`
- text and images: `text="caption"`, `images=(...)`
- translated text: `text="مرحبا"`, `translated_text="Hello"`, `translation_language="en"`

---

### Channels

`channels` accepts channel usernames with or without a leading `@`. Configuration
is fixed for the lifetime of the listener; create a new listener to monitor a
different set.

```python
listener = TelegramListener(
    session_manager=manager,
    channels=["cnn", "@AjaNews"],
)
```

---

### Translation

Translation is opt-in and uses Telegram's own
[`messages.translateText`](https://core.telegram.org/method/messages.translateText)
MTProto method through the listener's existing user connection. No translation
API key, local model, or second `TelegramClient` is required.

Pass the monitored channels and the subset to translate together:

```python
listener = TelegramListener(
    session_manager=manager,
    channels=["cnn", "ajanews", "franceinfo"],
    translation_channels=["ajanews", "franceinfo"],
    translation_target_language="en",
    translation_timeout=3.0,
    translation_max_concurrency=2,
)
```

Channel names are case-insensitive and may include a leading `@`. Telegram
detects the source language automatically; `translation_target_language` must be
a two-letter ISO 639-1 code such as `"en"`, `"es"`, or `"fr"`.
Every translation channel must also appear in `channels`.

For translated channels:

- `text` always keeps the sanitized original.
- `translated_text` contains the translated text.
- `translation_language` contains the normalized target language.
- Translation failures are logged and the original message is still emitted.
- Messages without text are not sent for translation. Images require a separate
  OCR step if they contain text.

By default the listener allows two translation requests at once and applies a
three-second total timeout, including time waiting for translation capacity.
Both values are configurable. Telegram may enforce undocumented quotas or return
transient errors; a translation failure does not prevent the original message
from being emitted. The normal queue-full drop policy still applies.

Omitting `translation_channels` disables automatic translation:

```python
listener = TelegramListener(session_manager=manager, channels=["cnn"])
```

The raw Telegram method is available only to user accounts, which matches the
phone-based `SessionManager` login flow used by this library.

---

### Exceptions

All library exceptions inherit from `TelegramListenerError`.

| Exception | When |
|-----------|------|
| `TelegramListenerError` | Base class — catch this to handle any library error |
| `SessionError` | Session missing, revoked, or login failed |
| `ConfigurationError` | Missing channels or invalid translation language |
| `TranslationError` | Manual translation requested without a running listener, or Telegram cannot translate the text |

---

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_API_ID` | Yes | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | Yes | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_PHONE` | Yes | International format, e.g. `+34612345678` |
| `TELEGRAM_SESSION_NAME` | No | Defaults to `telegram` |

Session files are stored at `~/.cache/telegramlistener/<session_name>.session`.
Login is an explicit operation; subsequent listener runs reuse the saved session
automatically and never prompt for credentials.

`example.py` keeps its channel lists and typed listener settings directly in
Python. The `.env` file is only for credentials and session settings; lists are
not encoded as comma-separated strings.

Translation uses the same Telegram credentials and session. It does not require
an additional environment variable or third-party service account.

---

## Reconnection

The listener reconnects on transient failures using exponential backoff: 2 s → 4 s → 8 s → … capped at 60 s, with ±1 s jitter. It stops permanently only if:

- The Telegram session is revoked or the account is deactivated, or
- `stop()` / `aclose()` is called explicitly.

---

## Logging

The library is silent by default (uses `NullHandler`). Enable logging at any level:

```python
import logging
logging.getLogger("telegramlistener").setLevel(logging.DEBUG)
```

At `INFO`, the listener emits one timing line for every message that reaches the
queue. It includes `processing_ms` for the complete listener path,
`translation_ms` for the Telegram translation request when applicable, and
`image_download_ms` for actual configured image-download attempts. Metadata
resolution and channel-filter checks are excluded. The values are measured per
message; the library does not calculate averages or retain metric history.

Example:

```text
Processed Telegram message channel='AjaNews' message_id=123456 processing_ms=284.6 translation_ms=281.9 image_download_ms=0.0 queued=True
```

`queued=False` means the message was dropped because `queue_maxsize` was full.
Use `IMAGE_CHANNELS = []` in the example to measure translation without image
download time.

---

## Running the Example

```bash
uv sync --extra examples
cp .env.example .env   # fill in your credentials
uv run example.py
```

`example.py` is the manual end-to-end smoke test. Edit its `CHANNELS` and
`TRANSLATION_CHANNELS` lists directly, then it loads credentials from `.env`,
prints original and translated messages, and runs until `Ctrl-C`. See
[doc/testing.md](doc/testing.md) for the expected behavior and the temporary-test
policy.

---

## Contributing

1. Fork, create a branch.
2. Run the checks documented in [AGENTS.md](AGENTS.md).
3. Use temporary behavioral tests only; do not add a `tests/` directory or
   commit test files.
4. Open a pull request with the runtime smoke-test observations when behavior
   involving Telegram changes.

---

## License

[MIT](LICENSE)
