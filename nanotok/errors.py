"""Exception hierarchy for nanotok.

Every failure that can reach the CLI derives from :class:`NanotokError`, so the
entrypoint can map error classes to stable exit codes without guessing.
"""

from __future__ import annotations


class NanotokError(Exception):
    """Base class for all nanotok failures."""


class ConfigError(NanotokError):
    """Raised when ``nanotok.config.json`` is missing, unreadable, or invalid."""


class InputError(NanotokError):
    """Raised when user supplied data violates the documented protocol."""


class TemplateError(NanotokError):
    """Raised when rule templates cannot be located or written."""
