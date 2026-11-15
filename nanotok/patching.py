"""LAYER 1 — zero-redundancy code patching.

Given old and new file contents, decide whether printing the whole file is
justified. The 50% rule from ``rancangan.md`` is enforced here and nowhere
else, so every surface (CLI, library, future MCP server) shares one policy.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import PurePosixPath

from nanotok.config import DEFAULT_CONFIG, NanotokConfig
from nanotok.models import CompressionReport, PatchFormat
from nanotok.tokens import compare_tokens

_HASH_COMMENT_SUFFIXES = frozenset(
    {".py", ".sh", ".bash", ".zsh", ".rb", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env", ".r"}
)
_SQL_COMMENT_SUFFIXES = frozenset({".sql"})
_ANCHOR_LINE_THRESHOLD = 40


@dataclass(frozen=True)
class PatchResult:
    """Patch text plus the measurements that justified its format."""

    path: str
    format: PatchFormat
    content: str
    change_ratio: float
    changed_lines: int
    total_lines: int
    hunk_count: int
    report: CompressionReport

    def to_mapping(self) -> dict[str, object]:
        return {
            "path": self.path,
            "format": self.format.value,
            "change_ratio": self.change_ratio,
            "changed_lines": self.changed_lines,
            "total_lines": self.total_lines,
            "hunk_count": self.hunk_count,
            "report": self.report.to_mapping(),
        }


def build_patch(
    old_text: str,
    new_text: str,
    path: str,
    *,
    config: NanotokConfig | None = None,
    patch_format: PatchFormat = PatchFormat.AUTO,
    context_lines: int = 3,
) -> PatchResult:
    """Emit the cheapest correct representation of an edit.

    Args:
        old_text: Current file content, empty string for a new file.
        new_text: Desired file content.
        path: Repository-relative path, used in patch headers.
        config: Optional config supplying the diff threshold.
        patch_format: Force an output format, or ``AUTO`` to apply the rule.
        context_lines: Context lines per hunk (must be >= 0).

    Returns:
        A :class:`PatchResult`. ``format`` is ``NOOP`` when nothing changed.
    """
    resolved_config = config or DEFAULT_CONFIG
    if context_lines < 0:
        raise ValueError(f"context_lines must be >= 0, got {context_lines}")

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    opcodes = _opcodes(old_lines, new_lines)

    if not old_lines and not new_lines:
        return _noop(path)

    changed_lines = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in opcodes if tag != "equal")
    if changed_lines == 0:
        return _noop(path, report=compare_tokens(old_text, ""))
    total_lines = max(len(old_lines), len(new_lines), 1)
    change_ratio = round(min(1.0, changed_lines / total_lines), 4)

    resolved_format = _resolve_format(
        patch_format, change_ratio, len(old_lines), resolved_config
    )
    group_count = len(list(_grouped_opcodes(old_lines, new_lines, context_lines)))

    if resolved_format is PatchFormat.FULL_FILE:
        return PatchResult(
            path=path,
            format=PatchFormat.FULL_FILE,
            content=_ensure_trailing_newline(new_text),
            change_ratio=change_ratio,
            changed_lines=changed_lines,
            total_lines=total_lines,
            hunk_count=group_count,
            report=compare_tokens(old_text, new_text),
        )

    if resolved_format is PatchFormat.SEARCH_REPLACE:
        search_patch = _format_search_replace(old_lines, new_lines, path, context_lines)
        if search_patch is not None:
            return PatchResult(
                path=path,
                format=PatchFormat.SEARCH_REPLACE,
                content=search_patch,
                change_ratio=change_ratio,
                changed_lines=changed_lines,
                total_lines=total_lines,
                hunk_count=group_count,
                report=compare_tokens(new_text, search_patch),
            )
        resolved_format = PatchFormat.UNIFIED_DIFF

    if resolved_format is PatchFormat.ANCHOR:
        anchor_patch = _format_anchor_patch(old_lines, new_lines, path, context_lines)
        return PatchResult(
            path=path,
            format=PatchFormat.ANCHOR,
            content=anchor_patch,
            change_ratio=change_ratio,
            changed_lines=changed_lines,
            total_lines=total_lines,
            hunk_count=group_count,
            report=compare_tokens(new_text, anchor_patch),
        )

    unified_patch = _format_unified_diff(old_lines, new_lines, path, context_lines)
    return PatchResult(
        path=path,
        format=PatchFormat.UNIFIED_DIFF,
        content=unified_patch,
        change_ratio=change_ratio,
        changed_lines=changed_lines,
        total_lines=total_lines,
        hunk_count=group_count,
        report=compare_tokens(new_text, unified_patch),
    )


def comment_prefix_for(path: str) -> str:
    """Return the line-comment prefix idiomatic for ``path``'s extension."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _HASH_COMMENT_SUFFIXES:
        return "#"
    if suffix in _SQL_COMMENT_SUFFIXES:
        return "--"
    return "//"


def _resolve_format(
    requested: PatchFormat,
    change_ratio: float,
    old_line_count: int,
    config: NanotokConfig,
) -> PatchFormat:
    if requested is PatchFormat.FULL_FILE:
        return PatchFormat.FULL_FILE
    if change_ratio >= config.diff_threshold_ratio or old_line_count == 0:
        return PatchFormat.FULL_FILE
    if requested is PatchFormat.AUTO:
        if old_line_count > _ANCHOR_LINE_THRESHOLD:
            return PatchFormat.ANCHOR
        return PatchFormat.UNIFIED_DIFF
    return requested


def _opcodes(
    old_lines: list[str], new_lines: list[str]
) -> list[tuple[str, int, int, int, int]]:
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    return [(tag, i1, i2, j1, j2) for tag, i1, i2, j1, j2 in matcher.get_opcodes()]


def _grouped_opcodes(
    old_lines: list[str], new_lines: list[str], context_lines: int
) -> list[list[tuple[str, int, int, int, int]]]:
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    return [list(group) for group in matcher.get_grouped_opcodes(context_lines)]


def _format_range(start: int, stop: int) -> str:
    beginning = start + 1
    length = stop - start
    if length == 1:
        return f"{beginning}"
    if length == 0:
        beginning -= 1
    return f"{beginning},{length}"


def _format_unified_diff(
    old_lines: list[str], new_lines: list[str], path: str, context_lines: int
) -> str:
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context_lines,
            lineterm="",
        )
    )
    return "\n".join(diff_lines)


def _format_anchor_patch(
    old_lines: list[str], new_lines: list[str], path: str, context_lines: int
) -> str:
    comment_prefix = comment_prefix_for(path)
    grouped = _grouped_opcodes(old_lines, new_lines, context_lines)
    output_parts: list[str] = [f"{comment_prefix} filepath: {path}"]

    for group_index, group in enumerate(grouped):
        if group_index > 0:
            output_parts.append(f"{comment_prefix} ... existing code ...")
        first_opcode = group[0]
        last_opcode = group[-1]
        header = (
            f"@@ -{_format_range(first_opcode[1], last_opcode[2])} "
            f"+{_format_range(first_opcode[3], last_opcode[4])} @@"
        )
        output_parts.append(header)
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                output_parts.extend(f" {line}" for line in old_lines[i1:i2])
                continue
            output_parts.extend(f"-{line}" for line in old_lines[i1:i2])
            output_parts.extend(f"+{line}" for line in new_lines[j1:j2])

    return "\n".join(output_parts)


def _format_search_replace(
    old_lines: list[str], new_lines: list[str], path: str, context_lines: int
) -> str | None:
    """Render search/replace blocks, or None when a block lacks a search anchor."""
    grouped = _grouped_opcodes(old_lines, new_lines, context_lines)
    output_blocks: list[str] = []

    for group in grouped:
        search_lines: list[str] = []
        replace_lines: list[str] = []
        for _tag, i1, i2, j1, j2 in group:
            search_lines.extend(old_lines[i1:i2])
            replace_lines.extend(new_lines[j1:j2])
        if not search_lines:
            return None
        output_blocks.append(
            "FILE: {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE".format(
                path=path,
                search="\n".join(search_lines),
                replace="\n".join(replace_lines),
            )
        )

    return "\n\n".join(output_blocks)


def _ensure_trailing_newline(text: str) -> str:
    if not text:
        return text
    return text if text.endswith("\n") else f"{text}\n"


def _noop(path: str, report: CompressionReport | None = None) -> PatchResult:
    return PatchResult(
        path=path,
        format=PatchFormat.NOOP,
        content="",
        change_ratio=0.0,
        changed_lines=0,
        total_lines=0,
        hunk_count=0,
        report=report or CompressionReport(0, 0),
    )
