# Verification

## Manual smoke workflow

```bash
uv sync
uv run telegram-login --prepare
uv run telegram-login
uv run smoke/listener.py
uv run smoke/history.py
```

`telegram-login` reads credentials from `.telegram/.env` and creates the
phone-named session under `.telegram/sessions/`. The smoke scripts use
`TelegramSession` to load, connect, validate, and disconnect that client. Set
channels, time ranges, and enrichment options in the constants at the top of
each smoke script before running it.

Listener runs until interrupted and prints received messages. History performs
one finite range query, optionally displays progress, and prints its result.
Neither script persists messages.

Keep `.telegram/`, credentials, codes, passwords, and session files private.

## Repository checks

Do not add permanent tests. Use a disposable diagnostic under `/private/tmp`
for focused behavior checks and remove it afterwards.

Before completion run:

```bash
.venv/bin/python -m compileall -q src smoke/listener.py smoke/history.py
uv lock --check
uv build --wheel
git diff --check
```

Remove generated build directories, package metadata, caches, and temporary
diagnostics after checking them. Do not run real Telegram smoke scripts during
routine review.
