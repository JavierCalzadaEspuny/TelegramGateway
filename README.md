# TelegramGateway

TelegramGateway is a small async wrapper around Telethon. It does four things:

- `telegram-login` prepares and authorizes a project-local Telegram session.
- `TelegramSession` opens and owns the authorized runtime client.
- `TelegramListener` sends new channel messages to an `asyncio.Queue`.
- `TelegramHistory` returns a bounded historical range as a list.

The two retrieval workflows produce immutable `TelegramMessage` objects. The
library can group albums, download configured photos, translate configured
channels, and generate a stable 26-character ID for each Telegram source
message.

The login command is the only interactive component. Runtime applications give
`TelegramSession` a project root; it loads credentials, finds the phone-named
session, connects, verifies authorization, and disconnects its client.

## Install

```bash
pip install git+https://github.com/JavierCalzadaEspuny/TelegramGateway.git
```

With uv:

```bash
uv add git+https://github.com/JavierCalzadaEspuny/TelegramGateway.git
```

## Login

Run the command from the repository that should own the session:

```bash
uv run telegram-login --prepare
uv run telegram-login
```

`--prepare` creates an idempotent local layout without asking for credentials:

```text
.telegram/
├── .env
├── .gitignore
└── sessions/
```

The normal command also prepares missing paths. It reads existing values from
`.telegram/.env`, prompts only for missing credentials, and writes those new
values only after Telegram authorizes the session. Telegram codes are never
stored. A 2FA password is requested only when Telegram requires it.

Sessions use the digits from `TELEGRAM_PHONE` as their name, for example:

```text
.telegram/sessions/34600123456.session
```

All paths are relative to the current working directory. The generated
`.telegram/.gitignore` ignores every credential and session file while keeping
itself trackable. See [doc/login.md](doc/login.md).

## Runtime session

Use `TelegramSession` instead of reading credentials or constructing a
`TelegramClient` in each application:

```python
from pathlib import Path

from telegram_gateway import TelegramSession

async with TelegramSession(Path.cwd()) as client:
    # Pass the connected client to TelegramListener or TelegramHistory.
    ...
```

The project root defaults to `Path.cwd()`. Additional keyword arguments are
forwarded to Telethon, for example `TelegramSession(receive_updates=False)`.
Missing configuration, missing session files, and unauthorized sessions raise
`TelegramSessionError` without starting an interactive login. See
[doc/session.md](doc/session.md).

## Listener

```python
import asyncio

from telegram_gateway import TelegramListener, TelegramSession

async with TelegramSession() as client:
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
from telegram_gateway import TelegramHistory, TelegramSession

async with TelegramSession() as client:
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

The manual scripts under `smoke/` use `TelegramSession` with the project-local
login. Set workflow options directly in `smoke/listener.py` and
`smoke/history.py`; see [doc/testing.md](doc/testing.md). Architecture and
ownership boundaries are in [doc/architecture.md](doc/architecture.md).
