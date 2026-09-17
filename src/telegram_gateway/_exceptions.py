"""Library-specific exceptions."""


class TelegramGatewayError(Exception):
    """Base class for all telegram_gateway errors.

    Catch this to handle any library error in one clause.
    """


class ConfigurationError(TelegramGatewayError):
    """Raised when listener configuration is invalid."""


class TranslationError(TelegramGatewayError):
    """Raised when Telegram cannot translate text as requested.

    Automatic channel translation catches this error and preserves the original
    message.
    """
