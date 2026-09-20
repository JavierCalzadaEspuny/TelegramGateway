# Listener

`TelegramListener` converts Telethon events into
`asyncio.Queue[TelegramMessage | None]`.

```python
from telegram_gateway import TelegramListener, TelegramSession

async with TelegramSession() as client:
    listener = TelegramListener(
        client,
        channels,
        image_channels=(),
        translation_channels=(),
        translation_target_language="en",
        translation_timeout=3.0,
        translation_max_concurrency=2,
        queue_maxsize=0,
    )
    await listener.start()
```

The client must already be connected and authorized. `TelegramSession` is the
standard owner, though any compatible connected client can be supplied. The
listener never logs in or disconnects it. A listener is single-use; create a
new instance after `start()` finishes or when its fixed configuration changes.

## Queue and lifecycle

`start()` registers handlers for new messages and albums, then waits for the
client to disconnect. It removes its handlers and adds `None` to `queue` on
shutdown.

`queue_maxsize=0` is unbounded. When a bounded queue is full, the incoming
message is dropped and a warning is logged so Telegram's update loop is not
blocked. If the queue is full during shutdown, one buffered message is removed
to make room for `None`.

Telethon owns transport reconnection. Errors from the client lifecycle reach
the caller. An error processing one event is logged and does not stop later
events.

## Messages, albums, images, and translation

A normal event becomes one `TelegramMessage`. Telegram album events are sorted
by Telegram message ID and become one message; the first item supplies identity
and text.

Photos are downloaded only when the channel username is in `image_channels`.
Download failures are logged and preserve the logical message. Photo-only
messages therefore remain available with an empty `images` tuple when download
is disabled or fails.

Text is Unicode-repaired and emoji-stripped. Translation runs only for
`translation_channels`, is limited by `translation_timeout` and
`translation_max_concurrency`, and has no retries in the live path. Translation
failure preserves the original text and leaves the translation fields empty.
