"""LAYER 2 — telegraphic prose compression with hard syntax protection.

Two rules dominate this module:

1. **Protect first, compress second.** Inline code, URLs, quoted literals,
   paths, CLI flags, and identifiers are replaced with sentinels before any
   word is touched, then restored. A compressor that edits ``user.profile`` is
   a bug, not a style choice.
2. **Never return empty for non-empty input.** If a tier's rules would erase
   everything, the previous tier's result is returned. Silent data loss is
   worse than a weak compression ratio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nanotok.config import DEFAULT_CONFIG, NanotokConfig
from nanotok.models import CompressionReport, CompressionTier
from nanotok.textspans import ProtectedText, protect_spans, split_fenced_blocks
from nanotok.tokens import compare_tokens, estimate_tokens

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

_FILLER_PHRASES: tuple[tuple[str, str], ...] = (
    (r"please note that", ""),
    (r"it is important to note that", ""),
    (r"it'?s important to note that", ""),
    (r"it is important to", ""),
    (r"please", ""),
    (r"kindly", ""),
    (r"in order to", "to"),
    (r"due to the fact that", "because"),
    (r"at this point in time", "now"),
    (r"a large number of", "many"),
    (r"a lot of", "many"),
    (r"make sure to", "ensure"),
    (r"make sure that", "ensure"),
    (r"as a result", "therefore"),
    (r"here is", ""),
    (r"here are", ""),
    (r"let me", ""),
    (r"i will", ""),
    (r"i have", ""),
    (r"you can", ""),
    (r"you should", "must"),
    (r"you need to", "must"),
    (r"we need to", "must"),
    (r"we should", "must"),
    (r"is able to", "can"),
    (r"in addition", "also"),
    (r"for example", "e.g."),
    (r"such as", "e.g."),
    (r"with regard to", "regarding"),
    (r"based on", "from"),
    (r"in terms of", "for"),
    (r"perlu diketahui bahwa", ""),
    (r"pada dasarnya", ""),
    (r"dengan demikian", "therefore"),
    (r"oleh karena itu", "therefore"),
    (r"sebagai contoh", "e.g."),
    (r"misalnya", "e.g."),
    (r"silakan", ""),
    (r"mohon", ""),
    (r"tolong", ""),
    (r"harap", ""),
    (r"yang mana", ""),
    (r"hal ini", "ini"),
    (r"untuk dapat", "untuk"),
    (r"agar supaya", "agar"),
    (r"dikarenakan", "karena"),
    (r"disebabkan oleh", "karena"),
)

_OPERATOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "causes": (
        r"leads? to",
        r"results? in",
        r"causes?",
        r"menyebabkan",
        r"mengakibatkan",
        r"menghasilkan",
    ),
    "returns": (r"returns?", r"mengembalikan"),
    "from": (r"berasal dari",),
    "with": (r"with", r"dengan"),
    "without": (r"without", r"tanpa"),
    "because": (r"because", r"karena"),
    "location": (r"at", r"pada"),
    "and": (r"and", r"dan"),
    "conflict": (r"not", r"tidak", r"bukan"),
}

_L1_REMOVE_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "i",
        "you",
        "we",
        "they",
        "me",
        "my",
        "our",
        "your",
        "saya",
        "anda",
        "kita",
        "kami",
    }
)

_L2_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "that",
        "which",
        "who",
        "whom",
        "this",
        "these",
        "those",
        "its",
        "it",
        "yang",
        "adalah",
        "merupakan",
        "ini",
        "itu",
        "tersebut",
        "akan",
        "sudah",
        "telah",
        "juga",
        "sangat",
        "lebih",
        "dapat",
        "bisa",
        "agar",
        "supaya",
        "jika",
        "maka",
        "sebagai",
        "secara",
        "hal",
    }
)

_LINE_PREFIX = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*))")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[]|$)")
_SPACE_RUN = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?])")
_TRAILING_SENTENCE_MARK = re.compile(r"[.!?]+$")
_WORD_PATTERN = re.compile(r"\S+")

_FILLER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{phrase}\b", re.IGNORECASE), replacement)
    for phrase, replacement in _FILLER_PHRASES
)
_REMOVE_WORD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE) for word in _L1_REMOVE_WORDS
)
_STOPWORD_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE) for word in _L2_STOPWORDS
)


@dataclass(frozen=True)
class DocumentCompression:
    """Compressed document plus token accounting."""

    text: str
    compressed_segments: int
    report: CompressionReport

    def to_mapping(self) -> dict[str, object]:
        return {
            "compressed_segments": self.compressed_segments,
            "report": self.report.to_mapping(),
        }


def compress_document(
    text: str,
    *,
    tier: CompressionTier = CompressionTier.L1,
    config: NanotokConfig | None = None,
) -> DocumentCompression:
    """Compress prose while leaving fenced code byte-identical."""
    resolved_config = config or DEFAULT_CONFIG
    output_parts: list[str] = []
    compressed_segments = 0

    for segment in split_fenced_blocks(text):
        if segment.is_code:
            output_parts.append(segment.text)
            continue
        compressed_segment = _compress_prose_segment(segment.text, tier, resolved_config)
        if compressed_segment != segment.text:
            compressed_segments += 1
        output_parts.append(compressed_segment)

    compressed_text = "".join(output_parts) or text
    return DocumentCompression(
        text=compressed_text,
        compressed_segments=compressed_segments,
        report=compare_tokens(text, compressed_text),
    )


def compress_prose(
    text: str,
    *,
    tier: CompressionTier = CompressionTier.L1,
    config: NanotokConfig | None = None,
) -> str:
    """Compress a prose-only string (no fenced blocks expected).

    Returns the input unchanged when every rule would erase it.
    """
    resolved_config = config or DEFAULT_CONFIG
    if not text.strip():
        return text

    protected = protect_spans(text)
    compressed_lines: list[str] = []

    for raw_line in protected.text.splitlines():
        if not raw_line.strip():
            continue
        prefix_match = _LINE_PREFIX.match(raw_line)
        line_prefix = prefix_match.group(1) if prefix_match else ""
        body = raw_line[len(line_prefix) :]
        sentence_outputs: list[str] = []
        for sentence in _split_sentences(body):
            compressed_sentence = _compress_sentence(sentence, tier, protected, resolved_config)
            if compressed_sentence:
                sentence_outputs.append(compressed_sentence)
        if sentence_outputs:
            first_line = f"{line_prefix}{sentence_outputs[0]}".rstrip()
            compressed_lines.append(first_line)
            compressed_lines.extend(sentence_outputs[1:])

    if not compressed_lines:
        return protected.restore(text).strip()
    return "\n".join(compressed_lines)


def _compress_prose_segment(
    segment_text: str, tier: CompressionTier, config: NanotokConfig
) -> str:
    """Compress one prose segment, preserving its surrounding newlines."""
    body = segment_text.strip("\n")
    if not body:
        return segment_text
    leading_newlines = segment_text[: len(segment_text) - len(segment_text.lstrip("\n"))]
    trailing_newlines = segment_text[len(segment_text.rstrip("\n")) :]
    return f"{leading_newlines}{compress_prose(body, tier=tier, config=config)}{trailing_newlines}"


def _split_sentences(line: str) -> list[str]:
    sentences = [chunk.strip() for chunk in _SENTENCE_BOUNDARY.split(line)]
    return [sentence for sentence in sentences if sentence]


def _compress_sentence(
    sentence: str,
    tier: CompressionTier,
    protected: ProtectedText,
    config: NanotokConfig,
) -> str:
    working = sentence
    for pattern, replacement in _FILLER_PATTERNS:
        working = pattern.sub(replacement, working)

    for pattern in _REMOVE_WORD_PATTERNS:
        working = pattern.sub("", working)

    if tier is not CompressionTier.L1:
        working = _apply_operators(working, config)
        for pattern in _STOPWORD_PATTERNS:
            working = pattern.sub("", working)

    working = _normalize_spacing(working)
    working = _TRAILING_SENTENCE_MARK.sub("", working).strip()

    if tier is CompressionTier.L3:
        machine_line = _machine_only(working, config)
        level_two_sentence = _compress_sentence(sentence, CompressionTier.L2, protected, config)
        restored_level_two = _normalize_spacing(
            _TRAILING_SENTENCE_MARK.sub("", _restore_or_empty(level_two_sentence))
        )
        if machine_line and len(machine_line.split()) >= 2:
            working = machine_line
        elif restored_level_two:
            working = restored_level_two

    return protected.restore(working).strip()


def _restore_or_empty(text: str) -> str:
    return text


def _apply_operators(text: str, config: NanotokConfig) -> str:
    resolved = text
    for operator_name, keywords in _OPERATOR_KEYWORDS.items():
        symbol = config.operators.get(operator_name)
        if not symbol:
            continue
        for keyword in keywords:
            resolved = re.sub(rf"\b{keyword}\b", symbol, resolved, flags=re.IGNORECASE)
    return resolved


def _normalize_spacing(text: str) -> str:
    normalized = _SPACE_RUN.sub(" ", text)
    normalized = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", normalized)
    return normalized.strip(" \t,")


def _machine_only(text: str, config: NanotokConfig) -> str:
    """Keep only machine-meaningful tokens (Layer 3 raw mode)."""
    operator_symbols = set(config.operators.values())
    kept_tokens = [
        token for token in _WORD_PATTERN.findall(text) if _is_machine_token(token, operator_symbols)
    ]
    return " ".join(kept_tokens)


def _is_machine_token(token: str, operator_symbols: set[str]) -> bool:
    if "\x00" in token:
        return True
    if token in operator_symbols:
        return True
    if any(character in token for character in "-><=>@/\\#$_!+*&|{}[]()"):
        return True
    if any(character.isdigit() for character in token):
        return True
    return token.isupper() and len(token) >= 2


def tier_savings(text: str, config: NanotokConfig | None = None) -> dict[str, int]:
    """Token counts for the original plus each tier — used by ``nanotok bench``."""
    resolved_config = config or DEFAULT_CONFIG
    counts = {"original": estimate_tokens(text)}
    for tier in CompressionTier:
        counts[tier.value] = estimate_tokens(
            compress_document(text, tier=tier, config=resolved_config).text
        )
    return counts
