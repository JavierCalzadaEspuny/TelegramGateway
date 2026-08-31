# TelegramListener agent guidance

## Purpose

This repository is a small Python wrapper around Telethon. It listens to public
Telegram channels and emits normalized `TelegramStreamedMessage` objects through
an `asyncio.Queue`. Optional translation is an enrichment step performed by
Telegram through the same authorized user connection.

Keep the project KISS: prefer a small explicit API, standard-library building
blocks, and code that can be understood without tracing a framework. Do not add
an abstraction unless it removes real complexity from the public workflow.

## Architecture

- `SessionManager` owns credentials, login, and the persistent Telethon session.
- `TelegramListener` owns one complete, fixed configuration and one active
  client. It is single-use; create a new instance to change channels or restart.
- `TelegramListener._translate_text()` calls Telegram's raw
  `messages.translateText` MTProto method through that same client. There is no
  separate translator object or second connection.
- `TelegramStreamedMessage` preserves the sanitized original in `text` and puts
  an optional result in `translated_text` with `translation_language`.
- `SessionManager.is_operational()` preserves the session file on transient
  connection errors and cleans it only after confirmed invalidation.

The public setup is constructor-based:

```python
listener = TelegramListener(
    session_manager=manager,
    channels=["AjaNews", "almayadeen", "SabrenNewss"],
    translation_channels=["AjaNews", "almayadeen", "SabrenNewss"],
    translation_target_language="en",
    translation_timeout=3.0,
    translation_max_concurrency=2,
    queue_maxsize=1000,
)
```

Do not reintroduce `set_channels()` or `set_translation_channels()`. Configuration
is validated once, normalized, and then remains stable. Translation is an
internal enrichment step; do not add a second public translation service unless
the library gains a real non-channel use case.

Translation must fail open: timeouts, quota errors, malformed responses, and
connection failures are logged and the original message is still emitted. Keep
the total timeout bounded, include semaphore wait time, and avoid retries or
batching in the real-time path because they add latency.

## Testing policy

Tests are intentionally temporary. Do not create a `tests/` directory, permanent
test modules, fixtures, snapshots, or test-only dependencies in this repository.
Write a focused test in a temporary directory when a change needs behavioral
verification, run it, inspect the result, and delete it immediately afterwards.
Never commit temporary tests.

For a temporary test file, use an exact directory under `/private/tmp` or the
system temporary directory. Remove that exact directory after the test finishes;
do not use broad recursive deletion targets.

The repository's permanent runtime verification is:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src example.py
.venv/bin/python -m compileall -q src example.py
uv lock --check
uv build --wheel
```

## Real smoke test

`example.py` is the manual end-to-end smoke test. It is the right tool for
checking the real Telegram session, channel subscriptions, image handling,
translation latency, and fail-open behavior. It is not a replacement for a
regression test, and it runs until interrupted.

Configure the channel lists and typed runtime settings directly at the top of
`example.py`:

```python
CHANNELS: list[str] = ["AjaNews", "almayadeen", "SabrenNewss"]
IMAGE_CHANNELS: list[str] = []
TRANSLATION_CHANNELS: list[str] = [
    "AjaNews",
    "almayadeen",
    "SabrenNewss",
]
TRANSLATION_TARGET_LANGUAGE = "en"
TRANSLATION_TIMEOUT = 3.0
TRANSLATION_MAX_CONCURRENCY = 2
QUEUE_MAXSIZE = 1000
```

Copy `.env.example` to `.env` only for credentials and the session name.

Then run:

```bash
uv sync --extra examples
uv run example.py
```

The example never starts an interactive login. If the session is absent or
revoked, it logs the manual-login instruction and exits without retrying
credentials. Each received message should print its original text and, when
Telegram answers before the timeout, its translation. The listener also logs
one timing line per processed message with `processing_ms`, `translation_ms`,
`image_download_ms`, and `queued`. `image_download_ms` measures only actual
image-download attempts, not metadata resolution. Press `Ctrl-C` and confirm the
process exits cleanly. A translation error is acceptable only when the original
message still reaches the consumer.

## Change discipline

When changing the public API, update the README, `doc/architecture.md`,
`doc/testing.md`, `example.py`, and `.env.example` together. Keep the model
contract explicit and do not silently replace `text` with translated content.
Before claiming completion, inspect `git diff --check`, verify there is no
`tests/` directory or temporary test file in the repository, and run the full
verification commands above.
