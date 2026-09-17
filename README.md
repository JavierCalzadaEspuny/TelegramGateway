# TelegramGateway

TelegramGateway is a small Telethon wrapper for two jobs: streaming new channel
messages to an `asyncio.Queue`, and retrieving a bounded range of historical
messages as a list. It produces immutable `TelegramMessage` objects with a
deterministic, 26-character ID derived from the source channel, message, and
timestamp.

The package does not authenticate an account, store messages, write JSON, run
OCR, or manage a database. The application creates, connects, authorizes, and
disconnects its own `TelegramClient`.

## Install

```bash
pip install git+https://github.com/JavierCalzadaEspuny/TelegramListener.git
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add git+https://github.com/JavierCalzadaEspuny/TelegramListener.git
```

## One client, two workflows

Create and authorize the client before constructing either coordinator. The
library never calls interactive login or asks for an SMS or 2FA code.

```python
from telethon import TelegramClient
from telegram_gateway import TelegramHistory, TelegramListener

client = TelegramClient("telegram", api_id=..., api_hash=...)
try:
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Create the Telegram session manually first")

    listener = TelegramListener(client=client, channels=["AjaNews"])
    history = TelegramHistory(client=client, channels=["AjaNews"])
finally:
    await client.disconnect()
```

Use one workflow at a time unless the application deliberately coordinates
their concurrent use of the same client.

## Live queue

`TelegramListener` watches configured channels until the client disconnects.
Consume `listener.queue` concurrently; `None` marks listener shutdown.

```python
import asyncio

from telegram_gateway import TelegramListener


async def consume(listener: TelegramListener) -> None:
    while True:
        message = await listener.queue.get()
        try:
            if message is None:
                return
            print(message)
        finally:
            listener.queue.task_done()


listener = TelegramListener(
    client=client,
    channels=["AjaNews", "almayadeen"],
    image_channels=["AjaNews"],
    translation_channels=["almayadeen"],
    translation_target_language="en",
    queue_maxsize=1000,
)
consumer = asyncio.create_task(consume(listener))
try:
    await listener.start()
finally:
    consumer.cancel()
```

A full bounded queue drops an incoming message instead of blocking Telegram's
update loop. Telethon owns reconnect behavior; terminal client errors reach the
caller.

## Historical list

`TelegramHistory.fetch()` returns every configured channel message in the
half-open Unix-second range `[start, end)`, sorted by timestamp, channel ID,
and Telegram message ID.

```python
from telegram_gateway import TelegramHistory

history = TelegramHistory(
    client=client,
    channels=["AjaNews", "almayadeen"],
    image_channels=["AjaNews"],
    translation_channels=["almayadeen"],
    translation_target_language="en",
)
messages = await history.fetch(
    start=1767225600,
    end=1767_312000,
)

for message in messages:
    print(message)
```

Pass integers in Unix seconds only. Convert calendar dates in the calling
application and choose the end boundary so it is excluded. See
[doc/history.md](doc/history.md) for pagination, FloodWait, memory, and error
behavior.

## Message processing

Both workflows use the same processing rules:

- Text is Unicode-repaired, emoji-stripped, and kept in `text`.
- An album becomes one `TelegramMessage`; its first message supplies text and
  identity, and configured photos are downloaded in message-ID order.
- `images` is an immutable tuple of bytes. Downloads occur only for channels
  listed in `image_channels` and fail open when an image cannot be fetched.
- Translation is opt-in for `translation_channels`; successful output is in
  `translated_text` and `translation_language`, never in place of `text`.
- Translation failures leave the original message available. Live processing
  has a short bounded timeout and no retries; history can use a slower policy
  with FloodWait retries before falling back to the original message.

`TelegramMessage` is an immutable normalized representation of one Telegram
message (or one grouped album):

| Field | Contents |
| --- | --- |
| `id` | Deterministic 26-character identifier derived from the timestamp, channel ID, and Telegram message ID. |
| `message_id` | Original Telegram message ID within the channel. |
| `timestamp` | Message timestamp as Unix seconds. |
| `channel_title` | Display title of the source channel. |
| `channel_username` | Public channel username, or `None` when unavailable. |
| `channel_id` | Telegram channel ID. |
| `text` | Sanitized original message text, or `None`. It is never replaced by a translation. |
| `images` | Immutable tuple of downloaded image bytes. It is empty when no configured image was downloaded. |
| `translated_text` | Optional translated text, or `None` when translation is disabled or unavailable. |
| `translation_language` | Target language of `translated_text`, or `None`. |

The convenience property `source_id` returns `(channel_id, message_id)`. The
deterministic ID is stable for the same Telegram source message, including
across live and history retrieval.

`message.to_dict()` returns the same fields as a plain Python dictionary. Image
data remains as the original `bytes` tuple; the method does not encode images or
write JSON files.

## Configuration and smoke checks

The library reads no environment variables. The repository's smoke scripts
load local values from `smoke/.env`; JSON arrays configure channel lists.

```bash
cp smoke/.env.example smoke/.env
uv sync --extra examples
uv run smoke/login.py
uv run smoke/listener.py
uv run smoke/history.py
```

`smoke/login.py` is the only interactive command. `listener.py` stays running
while messages arrive; `history.py` makes one finite range query with the same
authorized session. Keep `smoke/.env` and session files private. For the full
workflow, see [doc/testing.md](doc/testing.md).
