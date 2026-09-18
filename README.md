# TelegramGateway

TelegramGateway is a small async wrapper around Telethon. It does two things:

- `TelegramListener` sends new channel messages to an `asyncio.Queue`.
- `TelegramHistory` returns a bounded historical range as a list.

Both produce immutable `TelegramMessage` objects. The library can group albums,
download configured photos, translate configured channels, and generate a
stable 26-character ID for each Telegram source message.

The caller owns credentials, login, the Telethon session, the connected client,
and persistence. TelegramGateway never starts an interactive login or
disconnects a client supplied by the caller.

## Install

```bash
pip install git+https://github.com/JavierCalzadaEspuny/TelegramGateway.git
```

With uv:

```bash
uv add git+https://github.com/JavierCalzadaEspuny/TelegramGateway.git
```

## Client

Create and authorize one client before using either workflow:

```python
from telethon import TelegramClient

client = TelegramClient("telegram", api_id=..., api_hash=...)
await client.connect()
if not await client.is_user_authorized():
    raise RuntimeError("Create the Telegram session first")
```

Disconnect it in the calling application when finished.

## Listener

```python
import asyncio

from telegram_gateway import TelegramListener

listener = TelegramListener(
    client,
    ["AjaNews", "almayadeen"],
    image_channels=["AjaNews"],
    translation_channels=["almayadeen"],
    queue_maxsize=1000,
)

async def consume() -> None:
    while (message := await listener.queue.get()) is not None:
        print(message)

consumer = asyncio.create_task(consume())
await listener.start()
await consumer
```

`start()` runs until the client disconnects. A full bounded queue drops the
incoming message rather than blocking Telethon. `None` marks shutdown. See
[doc/listener.md](doc/listener.md).

## History

```python
from telegram_gateway import TelegramHistory

history = TelegramHistory(
    client,
    ["AjaNews", "almayadeen"],
    image_channels=["AjaNews"],
    translation_channels=["almayadeen"],
)
messages = await history.fetch(
    start=1_767_225_600,
    end=1_767_312_000,
    show_progress=True,
)
```

The result contains `[start, end)` in Unix seconds and is sorted by timestamp,
channel ID, and Telegram message ID. See [doc/history.md](doc/history.md).

Channels and processing options are fixed per coordinator. Create another
`TelegramListener` or `TelegramHistory` with the same connected client when
those options change.

## Message

| Field | Value |
| --- | --- |
| `id` | Stable 26-character ID derived from timestamp, channel ID, and message ID. |
| `message_id` | Telegram message ID within the channel. |
| `timestamp` | Unix seconds. |
| `channel_title` | Channel display title. |
| `channel_username` | Public username or `None`. |
| `channel_id` | Telegram channel ID. |
| `text` | Sanitized original text or `None`. |
| `images` | Tuple of downloaded photo bytes. |
| `translated_text` | Optional translated text. |
| `translation_language` | Target language when translation succeeded. |

`message.to_dict()` returns these fields without encoding image bytes or
writing files.

## Repository checks

The package reads no environment variables. The manual scripts under `smoke/`
load `smoke/.env`; see [doc/testing.md](doc/testing.md). Architecture and
ownership boundaries are in [doc/architecture.md](doc/architecture.md).
