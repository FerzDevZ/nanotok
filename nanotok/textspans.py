"""Shared text-span utilities: markdown fencing and token protection.

Layer 1 and Layer 2 both need to know which bytes are *code* and which are
*prose*. Re-implementing that logic per layer is how a compressor eventually
mangles a template literal, so the rules live here once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nanotok.models import DocumentSegment

_PLACEHOLDER = re.compile("\x00(\\d+)\x00")

DEFAULT_PROTECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"`+[^`\n]+`+"),  # inline code
    re.compile(r"https?://[^\s)\]>\"']+"),  # URLs
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),  # emails
    re.compile(r"\"[^\"\n]{1,300}\""),  # double-quoted literals
    re.compile(r"'[^'\n]{1,300}'"),  # single-quoted literals
    re.compile(r"\[!WARN\]"),  # destructive-operation marker
    re.compile(r"(?<!\w)--?[A-Za-z][\w-]*"),  # CLI flags
    re.compile(r"(?<![\w/])[\w.@+-]+(?:/[\w.@+-]+)+"),  # paths with a slash
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b"),  # snake_case
    re.compile(r"\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b"),  # camelCase
    re.compile(r"\b[A-Za-z_]\w*(?:\.\w+)+\b"),  # dotted.symbols
    re.compile(r"\b[A-Za-z_]\w*\(\)"),  # calls like handler()
    re.compile(r"\b[a-z]+(?:-[a-z]+)+\b"),  # kebab-case
    re.compile(r"\bv?\d+(?:\.\d+)+(?:[-+][\w.]+)?\b"),  # versions and decimals
)


@dataclass(frozen=True)
class ProtectedText:
    """Text whose technical spans were swapped for opaque sentinels."""

    text: str
    spans: tuple[str, ...]

    def restore(self, text: str) -> str:
        """Reinsert original spans into ``text``."""

        def replace(match: re.Match[str]) -> str:
            span_index = int(match.group(1))
            return self.spans[span_index] if span_index < len(self.spans) else match.group(0)

        return _PLACEHOLDER.sub(replace, text)


def split_fenced_blocks(text: str) -> list[DocumentSegment]:
    """Split text into alternating prose and fenced-code segments.

    Segment text is an exact slice of the input, so ``"".join(text)`` restores
    the original document byte for byte. An unterminated fence is treated as
    code through end-of-document: truncated paste is the common case.
    """
    segments: list[DocumentSegment] = []
    buffered_lines: list[str] = []
    in_code_block = False

    for line in text.splitlines(keepends=True):
        is_fence = line.lstrip().startswith("```")
        if is_fence and not in_code_block:
            if buffered_lines:
                segments.append(DocumentSegment("".join(buffered_lines), False))
                buffered_lines = []
            in_code_block = True
            buffered_lines.append(line)
            continue
        if is_fence and in_code_block:
            buffered_lines.append(line)
            segments.append(DocumentSegment("".join(buffered_lines), True))
            buffered_lines = []
            in_code_block = False
            continue
        buffered_lines.append(line)

    if buffered_lines:
        segments.append(DocumentSegment("".join(buffered_lines), in_code_block))
    return segments


def protect_spans(
    text: str, patterns: tuple[re.Pattern[str], ...] = DEFAULT_PROTECTION_PATTERNS
) -> ProtectedText:
    """Replace technical spans with ``\\x00N\\x00`` sentinels.

    Patterns are applied in order; earlier patterns (inline code, URLs) win.
    Sentinels contain no word characters, so later identifier patterns cannot
    match inside an already-protected span.
    """
    collected_spans: list[str] = []

    def replace(match: re.Match[str]) -> str:
        collected_spans.append(match.group(0))
        return f"\x00{len(collected_spans) - 1}\x00"

    protected_text = text
    for pattern in patterns:
        protected_text = pattern.sub(replace, protected_text)
    return ProtectedText(protected_text, tuple(collected_spans))
