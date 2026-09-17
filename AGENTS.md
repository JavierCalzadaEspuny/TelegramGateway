# AGENTS.md — TelegramGateway Contribution Guide

## Mission

TelegramGateway is a small Python wrapper around Telethon with two narrow
workflows:

- `TelegramListener` streams configured channels to an
  `asyncio.Queue[TelegramMessage | None]`.
- `TelegramHistory` returns configured-channel messages in a bounded,
  half-open Unix-second range as `list[TelegramMessage]`.

The package normalizes and optionally enriches Telegram messages. Credentials,
sessions, authentication, persistence, JSON output, databases, OCR, and
application policy belong to the caller.

Prefer correctness and credential protection, then a small readable
implementation, reuse of mature functionality, and only evidence-backed
performance work or features.

## Design boundaries

The caller owns API credentials, the persistent Telethon session, one-time
login and 2FA entry, client creation/connection/authorization/disconnection,
and process restart policy. Runtime package code must not call interactive
`start()`, request credentials, disconnect a client it did not create, or clean
up session files.

The coordinators own fixed channel configuration and Telethon retrieval. They
share one processor for text sanitization, album handling, configured image
downloads, optional translation, and deterministic 26-character message IDs.
`text` always remains the sanitized original; translation belongs only in
`translated_text` and `translation_language`.

`TelegramListener` is single-use, registers event handlers, and awaits
`run_until_disconnected()`. A bounded full queue drops the incoming message
rather than blocking Telethon's update loop; shutdown adds `None` as a
sentinel. Telethon owns transient transport reconnection.

`TelegramHistory.fetch(start: int, end: int)` accepts Unix seconds only and
returns `[start, end)`. It retrieves channels sequentially with Telethon
pagination, groups albums, and returns a complete in-memory list sorted across
channels. The caller converts human dates and persists the result if needed.

Translation is optional enrichment and fails open. The live path has no
translation retries. History may wait for and retry `FloodWaitError` according
to its configured retry policy, then emits the original message if retries are
exhausted. Translation-specific non-transient `RPCError`, `ConnectionError`,
and `OSError` are logged and fail open without retries; retrieval and other
non-translation client failures propagate. Image-download failures also leave
the logical message available. `TelegramHistory.fetch()` requires a connected
client and raises `RuntimeError` before retrieval when it is disconnected.

## Repository scope

```text
src/telegram_gateway/
    __init__.py       Public API
    _listener.py      Live client-to-queue coordinator
    _history.py       Bounded historical coordinator
    _processing.py    Shared normalization and enrichment
    _models.py        TelegramMessage
smoke/
    login.py          One-shot interactive session setup
    listener.py       Existing-session live smoke test
    history.py        Existing-session historical smoke test
    .env.example      Local smoke-test configuration template
doc/
    architecture.md   Runtime design and ownership boundaries
    history.md        Historical retrieval contract
    testing.md        Verification and smoke-test workflow
```

## Change discipline

- Keep control flow direct and avoid new frameworks, configuration systems,
  retry loops, hidden state, or abstractions without a demonstrated need.
- Reuse Telethon for protocol handling, event delivery, pagination,
  authorization primitives, and transport recovery; use the standard library
  for queues, paths, logging, and JSON parsing.
- Validate fixed configuration once. Do not add mutable channel setters.
- Do not add dependencies unless an existing dependency or the standard
  library cannot solve the need clearly and safely.
- Do not create permanent tests. Use one focused test in an exact temporary
  directory under `/private/tmp`, run it, then remove it immediately.
- Never commit `smoke/.env`, Telethon session files, credentials, codes, or
  generated build artifacts.

## Verification

Before completion, run:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src smoke/listener.py smoke/history.py smoke/login.py
.venv/bin/python -m compileall -q src smoke/listener.py smoke/history.py smoke/login.py
uv lock --check
uv build --wheel
git diff --check
```

Remove disposable `build/`, `dist/`, `*.egg-info`, and cache artifacts after
verification when they are not being published. Also confirm that no `tests/`
directory or temporary test file remains in the repository.

## Smoke workflow

```bash
cp smoke/.env.example smoke/.env
uv sync --extra examples
uv run smoke/login.py
uv run smoke/listener.py
uv run smoke/history.py
```

`login.py` alone performs interactive login. The other scripts must stop with a
clear instruction when the session is absent or unauthorized, without
prompting for credentials. Leave `listener.py` running while messages arrive;
`history.py` performs a finite `[start, end)` query using the same authorized
session.
