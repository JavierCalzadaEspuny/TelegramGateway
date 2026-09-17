"""Library-specific exceptions."""


class TelegramListenerError(Exception):
    """Base class for all telegramlistener errors.

    Catch this to handle any library error in one clause.
    """


class ConfigurationError(TelegramListenerError):
    """Raised when listener configuration is invalid."""


class TranslationError(TelegramListenerError):
    """Raised when Telegram cannot translate text as requested.

    Automatic channel translation catches this error and preserves the original
    message.
    """
