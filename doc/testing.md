# Testing and operational verification

## What the smoke scripts are for

The `smoke/` folder is an external manual integration check for the package:

- `smoke/login.py` creates or refreshes the local Telethon session with an
  explicit interactive login.
- `smoke/run.py` refuses to log in, connects the existing session, starts
  `TelegramListener`, and prints received messages.

The repository is locked to Telethon 1.45.0. The smoke runtime uses
Telethon's client context manager for connection cleanup; `TelegramListener`
does not disconnect the client it receives.

This is the best check that the real account, session, channel filters, image
downloads, translation, queue delivery, and native reconnect behavior work
together. It runs continuously and depends on Telegram and network behavior.

## Configure and create the session

Run these commands from the repository root:

```bash
cp smoke/.env.example smoke/.env
```

Fill in `smoke/.env`. It contains the API credentials, phone number, session
name, JSON channel lists, and listener settings. The session is
stored as `smoke/<TELEGRAM_SESSION_NAME>.session` and is ignored by Git.

Channel lists use JSON array syntax:

```env
TELEGRAM_MONITOR_CHANNELS=["testosint01","AjaNews"]
TELEGRAM_IMAGE_CHANNELS=["testosint01"]
TELEGRAM_TRANSLATION_CHANNELS=["AjaNews"]
```

Create the session once, while present to enter the SMS code and 2FA password:

```bash
uv sync --extra examples
uv run smoke/login.py
```

`login.py` is the only command that performs interactive login. Do not run it
inside the long-lived listener container.

## Run the real smoke test

```bash
uv run smoke/run.py
```

Expected behavior:

- An absent or unauthorized session logs a manual-login instruction and exits
  without prompting or retrying credentials.
- A valid session logs that it is authorized and starts monitoring the
  configured channels.
- New messages appear in the output with their original text.
- Successful translations appear in `translated_text` without replacing
  `text`.
- Configured photos and albums are delivered together.
- A translation timeout or quota error logs a warning but still delivers the
  original message.
- A temporary network loss is handled by Telethon's native client reconnect
  settings; the listener has no second retry loop.
- `Ctrl-C` disconnects the client and terminates the process cleanly.

Leave it running while messages arrive. A quiet channel proves the connection
only; to verify event delivery, configure a channel that receives a message or
use a controlled test channel available to the account.

## Temporary behavioral tests

Permanent tests are deliberately not stored in this repository. When a code
change needs a regression test:

1. Create an exact temporary directory, for example
   `/private/tmp/telegramlistener-test-XXXXXX`.
2. Put one focused Python test module there. Keep it independent from
   credentials and use a small fake only at the Telegram network boundary.
3. Run it with the repository source on `PYTHONPATH`.
4. Confirm the result is caused by the behavior under test.
5. Delete the exact temporary directory and verify no `tests/` directory or test
   file was added to the repository.

## Permanent checks

For every change, run:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src smoke/run.py smoke/login.py
.venv/bin/python -m compileall -q src smoke/run.py smoke/login.py
uv lock --check
uv build --wheel
git diff --check
```

The build outputs are disposable and should be removed after verification if
they are not being published.
