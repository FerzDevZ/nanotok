"""LAYER 0 — pre-flight log and stack-trace sanitizer.

The sanitizer never edits prose semantics and never touches fenced code. It
removes three classes of payload noise before the model sees them:

1. ANSI escape sequences.
2. Stack frames that point inside installed dependencies or the runtime.
3. Consecutive duplicate lines and repeated blank lines.

Frames that point at project code (``/src/``, ``/app/``, ``/lib/``, ``/pages/``)
always survive, including ``<anonymous>`` frames — those are frequently the
most useful line in a Next.js traceback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nanotok.config import DEFAULT_CONFIG, NanotokConfig
from nanotok.models import CompressionReport
from nanotok.textspans import split_fenced_blocks
from nanotok.tokens import compare_tokens

_ANSI_PATTERN = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI sequences
    r"|\x1b\][^\x07]*(?:\x07|\x1b\\)"  # OSC sequences
    r"|\x1b[@-Z\\-_]"  # two-character escapes
)

_FRAME_PREFIXES = ("at ", "at async ", 'file "')
_GO_FRAME = re.compile(r"^[\w./\\-]+\.go:\d+")

_INTERNAL_MARKERS: tuple[str, ...] = (
    "node_modules/",
    "node:internal",
    "site-packages/",
    "dist-packages/",
    "webpack-internal://",
    "__pycache__",
    ".venv/",
    "at processticksandrejections",
    "at module._compile",
    "at module._load",
    "at require (node:internal",
)


@dataclass(frozen=True)
class SanitizeResult:
    """Sanitized text plus auditable removal counters."""

    text: str
    ansi_removed: int
    frames_removed: int
    duplicates_collapsed: int
    blank_lines_removed: int
    report: CompressionReport

    def to_mapping(self) -> dict[str, object]:
        return {
            "ansi_removed": self.ansi_removed,
            "frames_removed": self.frames_removed,
            "duplicates_collapsed": self.duplicates_collapsed,
            "blank_lines_removed": self.blank_lines_removed,
            "report": self.report.to_mapping(),
        }


def strip_ansi(text: str) -> tuple[str, int]:
    """Remove ANSI escape sequences, returning text and removed count."""
    return _ANSI_PATTERN.subn("", text)


def sanitize_log(raw_text: str, config: NanotokConfig | None = None) -> SanitizeResult:
    """Sanitize a log or stack trace before it enters a prompt.

    Args:
        raw_text: Raw terminal output, traceback, or markdown log dump.
        config: Optional config supplying project path markers.

    Returns:
        A :class:`SanitizeResult` with cleaned text and removal statistics.
    """
    resolved_config = config or DEFAULT_CONFIG
    keep_markers = tuple(marker.lower() for marker in resolved_config.sanitizer.keep_path_markers)
    cleaned_text, ansi_removed = strip_ansi(raw_text)

    emitted_lines: list[str] = []
    frames_removed = 0
    duplicates_collapsed = 0
    blank_lines_removed = 0

    for segment in split_fenced_blocks(cleaned_text):
        is_code_block = segment.is_code
        block_lines = segment.text.splitlines()
        if is_code_block:
            emitted_lines.extend(line.rstrip() for line in block_lines)
            continue
        prepared_lines, block_frames_removed = _drop_internal_frames(block_lines, keep_markers)
        frames_removed += block_frames_removed
        deduped_lines, block_duplicates, block_blanks = _collapse_noise(prepared_lines)
        duplicates_collapsed += block_duplicates
        blank_lines_removed += block_blanks
        emitted_lines.extend(deduped_lines)

    sanitized_text = "\n".join(emitted_lines).strip("\n")
    return SanitizeResult(
        text=sanitized_text,
        ansi_removed=ansi_removed,
        frames_removed=frames_removed,
        duplicates_collapsed=duplicates_collapsed,
        blank_lines_removed=blank_lines_removed,
        report=compare_tokens(raw_text, sanitized_text),
    )


def _drop_internal_frames(
    block_lines: list[str], keep_markers: tuple[str, ...]
) -> tuple[list[str], int]:
    prepared_lines: list[str] = []
    pending_internal_frames = 0
    removed_frames = 0

    for raw_line in block_lines:
        stripped_line = raw_line.strip()
        if stripped_line and _is_internal_frame(stripped_line, keep_markers):
            pending_internal_frames += 1
            continue

        if pending_internal_frames:
            prepared_lines.append(
                f"  ... [{pending_internal_frames} internal library frames stripped]"
            )
            removed_frames += pending_internal_frames
            pending_internal_frames = 0
        prepared_lines.append(raw_line.rstrip())

    if pending_internal_frames:
        prepared_lines.append(
            f"  ... [{pending_internal_frames} internal library frames stripped]"
        )
        removed_frames += pending_internal_frames

    return prepared_lines, removed_frames


def _is_internal_frame(stripped_line: str, keep_markers: tuple[str, ...]) -> bool:
    lowered_line = stripped_line.lower()
    if not _looks_like_frame(lowered_line):
        return False
    if any(marker in lowered_line for marker in keep_markers):
        return False
    return any(marker in lowered_line for marker in _INTERNAL_MARKERS)


def _looks_like_frame(lowered_line: str) -> bool:
    if lowered_line.startswith(_FRAME_PREFIXES):
        return True
    return bool(_GO_FRAME.match(lowered_line))


def _collapse_noise(block_lines: list[str]) -> tuple[list[str], int, int]:
    """Fold consecutive duplicate lines and repeated blank lines."""
    output_lines: list[str] = []
    previous_content: str | None = None
    repeated_count = 0
    blank_run = 0
    duplicates_collapsed = 0
    blank_lines_removed = 0

    for line in block_lines:
        if not line.strip():
            blank_run += 1
            if blank_run > 1:
                blank_lines_removed += 1
                continue
            output_lines.append("")
            previous_content = None
            continue

        blank_run = 0
        content = line.strip()
        if content == previous_content:
            repeated_count += 1
            continue

        if repeated_count:
            output_lines.append(f"  ... [repeated {repeated_count}x]")
            duplicates_collapsed += repeated_count
            repeated_count = 0
        output_lines.append(line)
        previous_content = content

    if repeated_count:
        output_lines.append(f"  ... [repeated {repeated_count}x]")
        duplicates_collapsed += repeated_count

    return output_lines, duplicates_collapsed, blank_lines_removed
