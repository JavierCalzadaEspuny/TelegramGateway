# AGENTS.md — TelegramListener Contribution Guide

## Mission

TelegramListener is a small Python wrapper around Telethon. Its job is narrow:
listen to configured Telegram channels and place simple
`TelegramStreamedMessage` objects on an `asyncio.Queue`.

The main goal of this repository is easy long-term maintenance. Code should be
boring, explicit, short, and easy to understand without following a framework
or a chain of abstractions.

When making a decision, prefer this order:

1. Correctness and protection of credentials.
2. A small, readable implementation.
3. Reuse of reliable existing functionality.
4. Performance improvements supported by evidence.
5. Extra features only when they solve a demonstrated need.

## Core principles

### Keep it simple

- Follow KISS and YAGNI.
- Prefer direct control flow over cleverness.
- Keep functions small and focused on one job.
- Prefer plain Python data structures and standard-library primitives.
- Do not introduce a framework, dependency-injection layer, service object,
  configuration system, or generic abstraction unless it clearly removes more
  complexity than it adds.
- Do not build infrastructure for hypothetical future requirements.
- If a solution needs a long explanation, first check whether the design can be
  made smaller.

### Reuse mature functionality

Use existing libraries for functionality they already provide well. In this
project that means, for example:

- Telethon owns Telegram protocol handling, event delivery, authorization
  primitives, and transient connection recovery.
- `python-dotenv` loads local smoke-test configuration.
- The standard library handles JSON parsing, paths, logging, queues, and
  asynchronous coordination.
- `ftfy`, `emoji`, and Telegram's translation method provide focused behavior
  that should not be reimplemented locally.

Before writing new code, ask whether Telethon, the standard library, or an
already-installed dependency already solves the problem. A new dependency is
acceptable when it is established, focused, maintained, and removes meaningful
code or operational risk. Do not add a dependency to replace a couple of clear
standard-library lines.

Do not wrap a library merely to expose the same API under a new name. Add a
wrapper only when this project needs a concrete policy, such as the listener's
queue contract or fail-open translation behavior.

## Repository scope

```text
src/telegramlistener/
    __init__.py       Public API
    _listener.py      Telethon client-to-queue adapter
    _models.py        TelegramStreamedMessage
    _exceptions.py    Package-level exceptions
smoke/
    login.py          One-shot interactive session setup
    run.py            Existing-session end-to-end smoke test
    .env.example      Local smoke-test configuration template
doc/
    architecture.md   Runtime design and ownership boundaries
    testing.md        Verification and smoke-test workflow
```

This package is a real-time listener. It does not include historical message
export, dataset generation, OCR, persistence, or account administration.
Those responsibilities belong to the application using the package.

## Ownership boundaries

The caller owns:

- API credentials;
- the persistent Telethon session;
- one-time login and 2FA entry;
- creation, connection, and authorization of `TelegramClient`;
- disconnection of the `TelegramClient` it created;
- process-level restart policy.

`TelegramListener` owns:

- fixed channel configuration;
- Telethon event handlers;
- message sanitization and optional enrichment;
- image download for explicitly configured channels;
- translation through the same authorized client;
- queue delivery and listener-level telemetry.

The public setup is constructor-based:

```python
listener = TelegramListener(
    client=authorized_client,
    channels=["AjaNews", "almayadeen", "SabrenNewss"],
    translation_channels=["AjaNews", "almayadeen", "SabrenNewss"],
    translation_target_language="en",
    translation_timeout=3.0,
    translation_max_concurrency=2,
    queue_maxsize=1000,
)
```

The client must already be connected and authorized. Runtime code must not call
Telethon's interactive `start()`, request a phone code, disconnect a client it
did not create, or clean up session files. Manual login is a separate,
deliberate operation in `smoke/login.py`.

Configuration is validated once and kept exactly as supplied. Listener
instances are single-use; create a new instance to change channels or restart.
Do not reintroduce mutable setters such as `set_channels()` or
`set_translation_channels()`.

## Runtime behavior

- Create handlers with Telethon's event system and wait on
  `run_until_disconnected()`.
- Let Telethon handle transient transport reconnection through the client
  options. Do not add a second retry loop, polling health check, custom
  backoff, jitter, or session cleanup policy.
- If Telethon exhausts its native retries, let the error reach the caller or
  process supervisor.
- Translation is optional enrichment and must fail open: the original message
  is emitted when translation times out, fails, or returns an unusable result.
- Keep translation time bounded, including time waiting for concurrency
  capacity. Do not add retries or batching to the real-time path.
- `text` always remains the sanitized original text. Translation belongs in
  `translated_text` and must never silently replace `text`.
- A bounded queue may drop incoming messages when full; it must never block the
  Telethon update loop waiting for a slow consumer.
- The caller owns the `TelegramClient` context and disconnects it after the
  listener stops.

## Configuration

The library itself does not read environment variables. Only the external
smoke scripts use `smoke/.env`.

Channel variables use JSON arrays because dotenv values are text:

```env
TELEGRAM_MONITOR_CHANNELS=["testosint01","AjaNews"]
TELEGRAM_IMAGE_CHANNELS=["testosint01"]
TELEGRAM_TRANSLATION_CHANNELS=["AjaNews"]
```

The real `smoke/.env` and Telethon session files contain secrets and must never
be committed. Keep them beside the smoke scripts locally; `.gitignore` covers
them. Never print API hashes, phone codes, 2FA passwords, session contents, or
raw credentials in logs or documentation.

## Python style

- Use type hints on public functions and meaningful internal boundaries.
- Use descriptive names instead of comments that explain opaque code.
- Write comments only for non-obvious reasons, external constraints, or safety
  decisions. Do not narrate obvious Python.
- Prefer early returns and straightforward validation over deeply nested logic.
- Keep public behavior explicit in constructor arguments and docstrings.
- Preserve the existing error boundary. Do not catch broad exceptions unless a
  local event must be isolated or a fail-open policy explicitly requires it.
- Avoid hidden global state, implicit background tasks, monkey-patching, and
  magic defaults.
- Do not silently broaden accepted input formats. If a format is required,
  reject invalid input clearly.
- Do not optimize or refactor unrelated code while making a focused change.

## Dependency policy

Before adding a dependency:

1. Check whether the standard library already provides a clear solution.
2. Check whether an existing dependency already provides the behavior.
3. Confirm that the dependency removes real code or operational risk.
4. Keep the public API smaller, not larger, after adding it.
5. Update `pyproject.toml`, `uv.lock`, and relevant documentation together.

Avoid dependencies that introduce frameworks, hidden lifecycle management,
duplicate retry systems, or configuration magic. Fewer dependencies is good,
but a small, reliable dependency is preferable to maintaining a larger custom
implementation of mature functionality.

## Testing and verification

Permanent tests are intentionally not stored in this repository. Do not create
a `tests/` directory, permanent test modules, fixtures, snapshots, or test-only
dependencies. When a change needs behavioral verification:

1. Create one focused test in an exact temporary directory under `/private/tmp`
   or the system temporary directory.
2. Run it and confirm that it fails for the intended reason before the fix when
   using test-driven development.
3. Implement the smallest change that makes it pass.
4. Re-run the test and inspect the result.
5. Remove that exact temporary directory immediately.

Run the repository checks before claiming a change is complete:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src smoke/run.py smoke/login.py
.venv/bin/python -m compileall -q src smoke/run.py smoke/login.py
uv lock --check
uv build --wheel
git diff --check
```

Remove disposable `build/`, `dist/`, `*.egg-info`, and cache artifacts after
verification when they are not being published. Confirm that no `tests/`
directory or temporary test file remains in the repository.

## Real smoke test

The smoke scripts are the manual end-to-end check against a real Telegram
account:

```bash
cp smoke/.env.example smoke/.env
uv sync --extra examples
uv run smoke/login.py
uv run smoke/run.py
```

`login.py` is the only command that performs interactive login. Run it only
while present to enter the SMS code and 2FA password. `run.py` must never prompt
for credentials. If the session is absent or unauthorized, it must stop without
retrying credentials. With a valid session, verify message delivery, albums,
configured images, translation fail-open behavior, telemetry, Ctrl-C shutdown,
and native Telethon reconnection.

## Documentation and change discipline

Keep documentation aligned with the implementation. When changing the public
API, update the README, `doc/architecture.md`, `doc/testing.md`, and
`smoke/.env.example` together. Update examples when names, defaults, or
ownership boundaries change.

Every change should be narrow and reviewable:

1. Inspect the current code and documentation before editing.
2. State the smallest design that satisfies the request.
3. Prefer deleting code or delegating to an existing library over adding a new
   layer.
4. Verify behavior and inspect the final diff.
5. Leave no generated files, credentials, temporary tests, or unexplained
   configuration behind.

Do not use destructive Git commands such as `git reset --hard` or
`git checkout --` unless the user explicitly requests them. Never delete broad
directories when a precise path is available.

## Definition of done

A change is ready only when:

- the implementation is the smallest clear solution;
- ownership and error behavior remain explicit;
- existing public contracts are preserved or documented as changed;
- documentation and configuration examples match the code;
- credentials and session files remain protected;
- focused behavioral verification has passed;
- the full repository checks have passed;
- `git diff --check` is clean; and
- no temporary tests or generated artifacts remain.
