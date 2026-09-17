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

The package is tested and locked against Telethon 1.45.0.

---

## Quick Start

```python
from pathlib import Path

from telethon import TelegramClient
from telegramlistener import TelegramListener

session = Path("telegram")
if not session.with_suffix(".session").exists():
    raise RuntimeError("Create the Telegram session manually before starting")

client = TelegramClient(session, api_id=..., api_hash=..., auto_reconnect=True)
async with client:
    if not await client.is_user_authorized():
        raise RuntimeError("The Telegram session is not authorized")

    listener = TelegramListener(
        client=client,
        channels=["cnn", "ajanews"],
        translation_channels=["ajanews"],
        translation_target_language="en",
    )
    await listener.start()  # blocks; messages arrive on listener.queue
```

The caller owns authentication. The runtime path above never calls `start()` or
asks for a phone code. If the session is missing or unauthorized, stop the
application and perform manual setup separately.

### Real smoke test

The repository includes an external integration check in `smoke/`. It keeps the
credentials and Telethon session beside its configuration without adding any
authentication code to the library. See [Running the smoke test](#running-the-smoke-test)
for the one-time login and runtime commands.

---

## Migrating from 0.2

Version 0.3 keeps constructor-only configuration and makes the lifecycle
boundary explicit: the caller owns the `TelegramClient` context, while the
listener only registers handlers and delivers queue items. Create and authorize
the client, then pass it as `client=...`. Listener instances remain single-use;
create a new instance to change channels or restart after shutdown.

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


async with client:
    listener = TelegramListener(
        client=client,
        channels=["cnn", "ajanews"],
        translation_channels=["ajanews"],
    )
    consumer = asyncio.create_task(consume(listener.queue))
    try:
        await listener.start()
    finally:
        consumer.cancel()
```

---

## API Reference

### `TelegramListener`

Streams new messages from configured channels into `listener.queue`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client` | `TelegramClient` | — | Connected and authorized Telethon client |
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
| `await start()` | Start once and block. Telethon handles transient reconnection |

`TelegramListener` never disconnects the supplied client. Use Telethon's
`async with TelegramClient(...)` context or call `client.disconnect()` in the
application that created it.

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

Pass the exact Telegram channel usernames you want to monitor. Configuration is
fixed for the lifetime of the listener; create a new listener to monitor a
different set.

```python
listener = TelegramListener(
    client=client,
    channels=["cnn", "AjaNews"],
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
    client=client,
    channels=["cnn", "ajanews", "franceinfo"],
    translation_channels=["ajanews", "franceinfo"],
    translation_target_language="en",
    translation_timeout=3.0,
    translation_max_concurrency=2,
)
```

Use the same channel names in `channels` and `translation_channels`. Telegram
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
listener = TelegramListener(client=client, channels=["cnn"])
```

The raw Telegram method is available only to user accounts. Translation uses
the same client that delivers the events.

---

### Exceptions

All library exceptions inherit from `TelegramListenerError`.

| Exception | When |
|-----------|------|
| `TelegramListenerError` | Base class — catch this to handle any library error |
| `ConfigurationError` | Missing channels or invalid translation language |
| `TranslationError` | Telegram cannot translate the text |

---

## Smoke-test configuration

The library does not read environment variables. The external integration
scripts in `smoke/` do, so the test setup stays outside the package:

```bash
cp smoke/.env.example smoke/.env
```

The channel variables are JSON arrays, not comma-separated strings:

```env
TELEGRAM_MONITOR_CHANNELS=["testosint01","AjaNews"]
TELEGRAM_IMAGE_CHANNELS=["testosint01"]
TELEGRAM_TRANSLATION_CHANNELS=["AjaNews"]
```

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_API_ID` | Yes | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | Yes | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_PHONE` | Only for `login.py` | International format, e.g. `+34612345678` |
| `TELEGRAM_SESSION_NAME` | No | Session filename, defaults to `telegram` |
| `TELEGRAM_MONITOR_CHANNELS` | Yes | JSON list of monitored usernames |
| `TELEGRAM_IMAGE_CHANNELS` | No | JSON list of image-download channels |
| `TELEGRAM_TRANSLATION_CHANNELS` | No | JSON list of translation channels |
| `TELEGRAM_TRANSLATION_TARGET_LANGUAGE` | No | Two-letter language code, defaults to `en` |
| `TELEGRAM_TRANSLATION_TIMEOUT` | No | Translation timeout in seconds, defaults to `3` |
| `TELEGRAM_TRANSLATION_MAX_CONCURRENCY` | No | Concurrent translations, defaults to `2` |
| `TELEGRAM_QUEUE_MAXSIZE` | No | Queue size, defaults to `1000` |

The session is stored at `smoke/<TELEGRAM_SESSION_NAME>.session`. Both the
session and `smoke/.env` are ignored by Git. Translation uses the same Telegram
credentials and session; no additional service account is needed.

---

## Reconnection

The caller should create the client with Telethon's native
`auto_reconnect=True`. The client retries transient transport failures using
its `connection_retries` and `retry_delay` settings. `TelegramListener` waits
on `run_until_disconnected()` once and does not add a second retry loop, custom
backoff, jitter, polling, or session cleanup.

If Telethon exhausts its native retries, the connection error is propagated to
the caller. A supervisor such as Docker can then decide whether to restart the
application. Authentication failures are also propagated; the caller must
stop and perform manual login rather than retrying credentials.

---

## Logging

The library is silent by default (uses `NullHandler`). Enable logging at any level:

```python
import logging

logging.getLogger("telegramlistener").setLevel(logging.DEBUG)
```

At `DEBUG`, the listener emits one timing line for every message that reaches
the queue. It includes `processing_ms` for the complete listener path,
`translation_ms` for the Telegram translation request when applicable, and
`image_download_ms` for actual configured image-download attempts. Metadata
resolution and channel-filter checks are excluded. The values are measured per
message; the library does not calculate averages or retain metric history.

At `INFO`, startup and operational warnings remain visible without producing a
line for every message.

Example:

```text
Processed Telegram message channel='AjaNews' message_id=123456 processing_ms=284.6 translation_ms=281.9 image_download_ms=0.0 queued=True
```

`queued=False` means the message was dropped because `queue_maxsize` was full.
Use `TELEGRAM_IMAGE_CHANNELS=[]` in `smoke/.env` to measure translation without
image-download time.

The listener does not enable Telethon's `catch_up` mode. Replaying updates that
arrived while the client was offline is a separate application policy from this
real-time stream.

---

## Running the Smoke Test

Run these commands from the repository root:

```bash
uv sync --extra examples
cp smoke/.env.example smoke/.env   # fill in your credentials and channels
uv run smoke/login.py               # one-time interactive setup
uv run smoke/run.py
```

`smoke/login.py` creates the persistent session and is the only command that
asks for the SMS code or 2FA password. Run it only when you are present. The
long-lived `smoke/run.py` command never starts login; it loads all parameters
from `smoke/.env`, prints original and translated messages, and runs until
`Ctrl-C`. See [doc/testing.md](doc/testing.md) for expected behavior and the
temporary-test policy.

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
