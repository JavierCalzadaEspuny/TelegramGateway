# Runtime session

`TelegramSession` owns one Telethon client backed by the project-local login:

```python
from telegram_gateway import TelegramSession

async with TelegramSession() as client:
    # The client is connected and authorized here.
    ...
```

The project root defaults to the current working directory. Pass it explicitly
when the application can start elsewhere:

```python
session = TelegramSession(project_root, receive_updates=False)
client = await session.connect()
try:
    ...
finally:
    await session.disconnect()
```

Keyword arguments after `project_root` are forwarded to Telethon's
`TelegramClient`. TelegramGateway always supplies the session path, API ID, and
API hash from the project-local login.

## Lifecycle

`connect()` reads `.telegram/.env`, derives the session name from the digits in
`TELEGRAM_PHONE`, requires the corresponding `.session` file, connects the
client, and checks authorization. It returns that connected client. The same
client is available through `session.client` until `disconnect()` succeeds.

Calling `connect()` twice or reading `client` before connecting is an invalid
runtime state. `disconnect()` is safe when already disconnected. Connection or
authorization failures disconnect the temporary client before propagating.

`TelegramSessionError` reports missing or malformed login configuration,
missing session files, and sessions that are no longer authorized. Run
`uv run telegram-login` from the same project root to create or renew the
login. Runtime session opening is deliberately non-interactive.

## Ownership

The `TelegramSession` instance owns and disconnects the client it creates.
`TelegramListener` and `TelegramHistory` borrow that connected client and never
disconnect it. The application still decides when the runtime starts and ends,
which client options it needs, and whether or how to restart after failure.
