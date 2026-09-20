# TelegramGateway contributor guide

## Scope

TelegramGateway is a small Telethon wrapper with four entry points:

- `telegram-login` prepares and authorizes a project-local session.
- `TelegramSession` loads that session and owns one connected runtime client.
- `TelegramListener` sends configured live channels to
  `asyncio.Queue[TelegramMessage | None]`.
- `TelegramHistory` returns configured channels from a bounded half-open
  Unix-second range as `list[TelegramMessage]`.

Keep project-local login, images, albums, optional translation, deterministic
IDs, listener backpressure, historical retries, and optional history progress.
Do not add message persistence, JSON output, databases, OCR, workers,
notifications, or application policy.

## Ownership

The login command owns `.telegram/.env`, phone-named sessions, interactive
authorization, and its temporary client. It writes newly entered credentials
only after successful authorization and never stores Telegram codes.

`TelegramSession` owns runtime configuration loading, session-path derivation,
client creation, connection, authorization checks, and disconnection. It never
starts interactive authorization. Callers own when the lifecycle begins and
ends, client options, storage, and restart policy. Listener and history must
not disconnect a supplied client. Do not add global paths, account managers,
profiles, automatic login, or a phone CLI option.

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
    _session.py
    login.py
smoke/
    listener.py
    history.py
doc/
    architecture.md
    session.md
    listener.md
    history.md
    login.md
    testing.md
```

Keep control flow direct. Do not add facades, services, repositories, adapters,
configuration frameworks, or dependencies without a demonstrated need.
Smoke workflow settings belong as constants in their scripts; do not add a
second environment file or smoke-specific configuration layer.

## Verification

Do not add permanent tests. Use exact disposable paths under `/private/tmp`,
then remove them. Do not run real Telegram calls during routine review.

```bash
.venv/bin/python -m compileall -q src smoke/listener.py smoke/history.py
uv lock --check
uv build --wheel
git diff --check
```

Remove generated build and cache artifacts. Confirm that no credentials,
sessions, `.env`, tests, or generated data are tracked.

Do not commit, push, merge, or create a pull request unless explicitly asked.
