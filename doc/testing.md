# Testing and operational verification

## What `example.py` is for

`example.py` is intentionally a manual end-to-end smoke test. It exercises the
real user session, Telegram channel filters, message normalization, image
downloads, translation, queue delivery, reconnect behavior, and graceful
shutdown. That makes it the best first check that this wrapper behaves correctly
with your account and your channels.

It is not an automated regression suite: it needs an already-authorized Telegram
session, runs continuously, and depends on external network behavior. It never
starts an interactive login.

## Run the real smoke test

Copy `.env.example` to `.env` and set credentials from `my.telegram.org`. Then
edit the typed Python configuration at the top of `example.py`:

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

The `.env` file is deliberately limited to credentials and session settings;
Python lists are not parsed from environment strings.

Run:

```bash
uv sync --extra examples
uv run example.py
```

Expected behavior:

- An absent or revoked session logs a manual-login instruction and exits without
  starting login or retrying credentials.
- New messages appear in the queue and print their original Arabic text.
- Successful translations print below the original.
- Each processed message logs its individual timings:
  `processing_ms`, `translation_ms`, and `image_download_ms`. The values are
  per-message measurements; no averages or accumulated metrics are collected.
- A Telegram timeout or quota error logs a warning but still delivers the
  original message with `translated_text=None`.
- `Ctrl-C` disconnects the client and terminates the process.

Leave it running for 15–30 minutes while messages arrive. Watch for repeated
disconnects, growing process memory, queue-full warnings, and translation
timeouts. Telegram controls the external service's quota and latency, so this
smoke test measures the behavior that matters in your deployment.

## Temporary behavioral tests

Permanent tests are deliberately not stored in this repository. When a code
change needs a regression test:

1. Create an exact temporary directory, for example
   `/private/tmp/telegramlistener-test-XXXXXX`.
2. Put one focused Python test module there. Keep the test independent from
   credentials and use a small fake only at the Telegram network boundary.
3. Run it with the repository source on `PYTHONPATH`:

   ```bash
   PYTHONPATH=src .venv/bin/python /private/tmp/telegramlistener-test-XXXXXX/test_behavior.py
   ```

4. Confirm the failure or success is caused by the behavior under test.
5. Delete the exact temporary directory and verify no `tests/` directory or test
   file was added to the repository.

For every change, also run the permanent checks:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src example.py
.venv/bin/python -m compileall -q src example.py
uv lock --check
uv build --wheel
```

## What to inspect in a message

For a translated message, verify that:

```python
message.text                 # sanitized Arabic source
message.translated_text      # English text, or None on failure
message.translation_language # "en" when translated, otherwise None
```

The translation must never overwrite `text`. Messages without text are not sent
to Telegram for translation; text inside images requires a separate OCR step.
