# TelegramGateway contributor guide

## Scope

TelegramGateway is a small Telethon wrapper with two workflows:

- `TelegramListener` sends configured live channels to
  `asyncio.Queue[TelegramMessage | None]`.
- `TelegramHistory` returns configured channels from a bounded half-open
  Unix-second range as `list[TelegramMessage]`.

Keep images, albums, optional translation, deterministic IDs, listener
backpressure, historical retries, and optional history progress. Do not add
authentication, persistence, JSON output, databases, OCR, workers,
notifications, or application policy.

## Ownership

The caller owns credentials, session files, login, client creation,
connection, authorization, disconnection, storage, and restart policy. Runtime
code must not call interactive `start()` or disconnect a supplied client.

Fixed channels and processing options are validated when a coordinator is
created. Do not add mutable setters. Use `ValueError` for invalid arguments and
`RuntimeError` for invalid runtime state.

Images and translation are optional enrichment and fail open. Retrieval,
authorization, and channel-resolution errors propagate. Listener translation
has bounded concurrency and no retry. History is sequential and retries only
known transient translation failures and configured FloodWaits.

## Layout

```text
src/telegram_gateway/
    __init__.py
    _listener.py
    _history.py
    _processing.py
    _models.py
smoke/
    _common.py
    login.py
    listener.py
    history.py
doc/
    architecture.md
    listener.md
    history.md
    testing.md
```

Keep control flow direct. Do not add facades, services, repositories, adapters,
configuration frameworks, or dependencies without a demonstrated need.

## Verification

Do not add permanent tests. Use exact disposable paths under `/private/tmp`,
then remove them. Do not run real Telegram calls during routine review.

```bash
.venv/bin/python -m compileall -q src smoke/login.py smoke/listener.py smoke/history.py smoke/_common.py
uv lock --check
uv build --wheel
git diff --check
```

Remove generated build and cache artifacts. Confirm that no credentials,
sessions, `.env`, tests, or generated data are tracked.

Do not commit, push, merge, or create a pull request unless explicitly asked.
