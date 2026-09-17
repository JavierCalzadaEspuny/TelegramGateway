# Testing and operational verification

## Smoke checks

The `smoke/` scripts exercise a real account and an already authorized session.
They are manual integration checks, not package authentication code.

```bash
cp smoke/.env.example smoke/.env
uv sync --extra examples
uv run smoke/login.py
uv run smoke/listener.py
uv run smoke/history.py
```

Fill in `smoke/.env` before running these commands. It is private, as are the
session file, API hash, phone number, SMS code, and 2FA password. Channel
settings are JSON arrays. Listener settings use the `TELEGRAM_LISTENER_*`
prefix; history settings use `TELEGRAM_HISTORY_*`, so each smoke can be run
with a different channel list and enrichment configuration.

`smoke/login.py` is the only command that prompts for credentials. Both runtime
scripts use the same authorized session and must stop with a clear instruction,
without retrying login, if it is absent or unauthorized.

Leave `smoke/listener.py` running while messages arrive. Confirm that it prints
live `TelegramMessage` values, groups albums, downloads photos only for its
configured image channels, keeps original text when translation fails, and
stops cleanly with `Ctrl-C`.

`smoke/history.py` performs one finite `[TELEGRAM_HISTORY_START,
TELEGRAM_HISTORY_END)` query, using Unix seconds from `smoke/.env`, and prints
each returned `TelegramMessage`. It is not a live listener and it does not
write the returned list anywhere.

## Temporary behavioral tests

Permanent tests are intentionally not stored in this repository. For a focused
regression check, create one test in an exact temporary directory under
`/private/tmp`, run it against the repository source, and remove that directory
immediately. Do not add a `tests/` directory, fixtures, snapshots, or test-only
dependencies.

## Permanent checks

Run before completion:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src smoke/listener.py smoke/history.py smoke/login.py
.venv/bin/python -m compileall -q src smoke/listener.py smoke/history.py smoke/login.py
uv lock --check
uv build --wheel
git diff --check
```

Remove disposable build outputs when they are not being published and confirm
that no temporary test files remain.
