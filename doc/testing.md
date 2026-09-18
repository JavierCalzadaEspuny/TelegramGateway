# Verification

## Manual smoke workflow

```bash
cp smoke/.env.example smoke/.env
uv sync --extra smoke
uv run smoke/login.py
uv run smoke/listener.py
uv run smoke/history.py
```

`login.py` is the only interactive script. Listener and history require the
same existing authorized session and never request credentials. Their channel
and enrichment settings use independent `TELEGRAM_LISTENER_*` and
`TELEGRAM_HISTORY_*` variables.

Listener runs until interrupted and prints received messages. History performs
one finite range query, optionally displays progress, and prints its result.
Neither script persists messages.

Keep `smoke/.env`, credentials, codes, passwords, and `*.session` files private.

## Repository checks

Do not add permanent tests. Use a disposable diagnostic under `/private/tmp`
for focused behavior checks and remove it afterwards.

Before completion run:

```bash
.venv/bin/python -m compileall -q src smoke/login.py smoke/listener.py smoke/history.py smoke/_common.py
uv lock --check
uv build --wheel
git diff --check
```

Remove generated build directories, package metadata, caches, and temporary
diagnostics after checking them. Do not run real Telegram smoke scripts during
routine review.
