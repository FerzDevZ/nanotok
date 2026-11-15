"""Deterministic token estimation.

``tiktoken`` is intentionally avoided: the package must run with zero external
dependencies. The estimator blends a character heuristic (BPE models average
~3.8 chars/token on prose) with a lexical-unit count (code punctuation splits
into extra tokens), then averages both signals. Measured error against
``cl100k_base`` on this repository's fixtures stays inside ±15%; it is a
planning instrument, not a billing meter.
"""

from __future__ import annotations

import re

from nanotok.models import CompressionReport

_LEXICAL_UNIT = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_CHARS_PER_TOKEN = 3.8
_TOKENS_PER_UNIT = 1.15


def estimate_tokens(text: str) -> int:
    """Estimate BPE token count for ``text``.

    Whitespace-only input returns ``0`` so savings percentages never divide by
    zero on empty files.
    """
    if not text.strip():
        return 0
    lexical_units = _LEXICAL_UNIT.findall(text)
    character_estimate = len(text) / _CHARS_PER_TOKEN
    unit_estimate = len(lexical_units) * _TOKENS_PER_UNIT
    blended = (character_estimate + unit_estimate) / 2
    return max(1, round(blended))


def compare_tokens(original: str, compressed: str) -> CompressionReport:
    """Build a :class:`CompressionReport` from raw before/after text."""
    return CompressionReport(
        original_tokens=estimate_tokens(original),
        compressed_tokens=estimate_tokens(compressed),
    )
