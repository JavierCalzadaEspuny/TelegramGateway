# Architecture

```text
telegram-login -> .telegram/.env + .telegram/sessions/<phone>.session

caller-owned TelegramClient
    ├── TelegramListener -> asyncio.Queue[TelegramMessage | None]
    └── TelegramHistory  -> list[TelegramMessage]
                  \-> MessageProcessor
```

The explicit login command owns preparation, interactive authorization, and
the temporary client it creates. Runtime callers own client creation,
connection, authorization checks, disconnection, message storage, and restart
policy. Listener and history never invoke interactive login.

## Modules

- `_listener.py`: Telethon events, queue backpressure, and shutdown.
- `_history.py`: bounded sequential pagination, album grouping, sorting, and
  optional progress.
- `_processing.py`: shared validation, text cleanup, channel metadata, images,
  and translation.
- `_models.py`: immutable `TelegramMessage` and deterministic IDs.
- `login.py`: project-local credential preparation and interactive login.
- `__init__.py`: the three public types.

Both workflows use the same processing rules but different latency policies.
Listener translation is concurrency-limited and never retried. History is
sequential and may retry known transient translation failures. Images and
translation fail open; retrieval errors do not.

Login deliberately remains a standalone command. There is no public session
manager, path helper, client factory, global configuration, or automatic
runtime authentication. The package has no message persistence, JSON writer,
database, OCR, worker, notification, or application-policy layer.
