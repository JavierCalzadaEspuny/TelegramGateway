# Login

`telegram-login` prepares and authorizes a Telegram session in the directory
from which it is run. It replaces project-specific login scripts while keeping
each repository's credentials and sessions local.

## Preparation

```bash
uv run telegram-login --prepare
```

Preparation is non-interactive and idempotent. It creates missing paths under
`Path.cwd()`:

```text
.telegram/
├── .env
├── .gitignore
└── sessions/
```

An existing `.env` is never replaced. The initial file is:

```dotenv
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=
TELEGRAM_2FA_PASSWORD=
```

The generated `.gitignore` is repaired on every preparation so credentials and
sessions remain ignored:

```gitignore
*
!.gitignore
```

## Authorization

```bash
uv run telegram-login
```

The normal command prepares the layout first, so running `--prepare` separately
is optional. It reads `.telegram/.env` and prompts for an API ID, API hash, or
phone only when the corresponding value is absent or blank.

The session stem is the configured phone reduced to digits:

```text
TELEGRAM_PHONE=+34 600 123 456
              ↓
.telegram/sessions/34600123456.session
```

An existing authorized session is reused without requesting a Telegram code.
Otherwise, the code is read interactively and never persisted. If Telegram
requires 2FA and the password is blank, the command requests it without echoing
it.

Newly entered values remain in memory until Telegram confirms authorization.
Only then are blank variables filled in `.env`; existing non-empty values are
never overwritten. A failed or interrupted login therefore leaves the
credential file unchanged.

## Ownership and security

The command owns and disconnects only the `TelegramClient` it creates. It does
not expose a session manager, client factory, or path helper. Consumer code
uses the documented `.telegram/sessions/<phone-digits>.session` convention.

`.telegram/.env`, 2FA passwords, and `*.session` files are secrets. The session
file grants access to the Telegram account and must not be copied into source
control or shared. Generated directories and sensitive files receive
restrictive permissions when the platform supports them.

Every path is relative to the command's current working directory. Run login
and the consuming application from the same project root.

Remember to add `.telegram` to your global `.gitignore` rules.
