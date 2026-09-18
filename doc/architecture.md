# Architecture

```text
caller-owned TelegramClient
    ├── TelegramListener -> asyncio.Queue[TelegramMessage | None]
    └── TelegramHistory  -> list[TelegramMessage]
                  \-> MessageProcessor
```

The caller owns credentials, login, session files, client lifecycle, storage,
and restart policy. TelegramGateway owns only retrieval and normalization.

## Modules

- `_listener.py`: Telethon events, queue backpressure, and shutdown.
- `_history.py`: bounded sequential pagination, album grouping, sorting, and
  optional progress.
- `_processing.py`: shared validation, text cleanup, channel metadata, images,
  and translation.
- `_models.py`: immutable `TelegramMessage` and deterministic IDs.
- `__init__.py`: the three public types.

Both workflows use the same processing rules but different latency policies.
Listener translation is concurrency-limited and never retried. History is
sequential and may retry known transient translation failures. Images and
translation fail open; retrieval errors do not.

The package has no authentication, persistence, JSON writer, database, OCR,
worker, notification, or application-policy layer.
