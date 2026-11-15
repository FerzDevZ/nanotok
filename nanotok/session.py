"""LAYER 5 — spec packing, session checkpoints, and inter-agent bus.

These helpers compress *coordination*, not source code. A packed spec turns a
verbose PRD into a dense machine-readable brief; a checkpoint turns a long
session into a <=90-token state snapshot; an agent task turns a free-form
request into a minified JSON envelope with fixed keys.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from nanotok.config import DEFAULT_CONFIG, NanotokConfig
from nanotok.errors import InputError
from nanotok.models import AgentTask, CompressionReport, CompressionTier, SessionState
from nanotok.telegraph import compress_prose
from nanotok.tokens import compare_tokens, estimate_tokens

_SECTION_ALIASES = {
    "goal": ("goal", "objective", "tujuan", "problem", "summary"),
    "stack": ("stack", "tech", "technology", "tools", "dependencies"),
    "constraints": ("constraint", "constraints", "rules", "must", "batasan", "invariants"),
    "acceptance": ("acceptance", "criteria", "done when", "success", "expected"),
    "out_of_scope": ("out of scope", "exclude", "non-goal", "out-of-scope"),
}
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

_WIRE_TO_FIELD = {
    "t": "action",
    "f": "file",
    "ln": "line",
    "err": "error",
    "req": "request",
    "c": "context",
}
_FIELD_TO_WIRE = {value: key for key, value in _WIRE_TO_FIELD.items()}


@dataclass(frozen=True)
class PackedSpec:
    """Dense specification produced by ``pack_spec``."""

    text: str
    sections: tuple[str, ...]
    report: CompressionReport

    def to_mapping(self) -> dict[str, object]:
        return {
            "sections": list(self.sections),
            "report": self.report.to_mapping(),
        }


@dataclass(frozen=True)
class CheckpointResult:
    """Session snapshot text and token accounting."""

    text: str
    token_estimate: int
    truncated: bool

    def to_mapping(self) -> dict[str, object]:
        return {
            "text": self.text,
            "token_estimate": self.token_estimate,
            "truncated": self.truncated,
        }


def pack_spec(
    verbose_text: str,
    *,
    tier: CompressionTier = CompressionTier.L2,
    config: NanotokConfig | None = None,
) -> PackedSpec:
    """Compress a verbose spec/PRD into a dense structured brief.

    Sections are extracted heuristically by heading/label aliases. Items inside
    lower-priority sections are dropped until the token target is met, so the
    result may be lossy by design — the target ratio is a hard budget.
    """
    resolved_config = config or DEFAULT_CONFIG
    sections = _extract_sections(verbose_text)
    target_tokens = max(1, round(estimate_tokens(verbose_text) * resolved_config.pack_target_ratio))

    packed_text = _render_packed_sections(sections, tier, resolved_config)
    if estimate_tokens(packed_text) > target_tokens:
        sections = _shrink_sections(sections)
        packed_text = _render_packed_sections(sections, tier, resolved_config)

    included = tuple(name for name, values in sections.items() if values)
    return PackedSpec(
        text=packed_text,
        sections=included,
        report=compare_tokens(verbose_text, packed_text),
    )


def build_checkpoint(
    state: SessionState,
    *,
    config: NanotokConfig | None = None,
) -> CheckpointResult:
    """Render a <=N-token session snapshot, truncating values if required."""
    resolved_config = config or DEFAULT_CONFIG
    max_tokens = resolved_config.max_checkpoint_tokens

    pairs = state.as_lines()
    if not pairs:
        raise InputError("checkpoint requires at least a non-empty stack value")

    rendered = _render_checkpoint(pairs)
    truncated = False
    shrink_order = ["Done", "Next", "WIP", "Blocker", "Stack"]
    while estimate_tokens(rendered) > max_tokens and shrink_order:
        label_to_shrink = shrink_order.pop(0)
        pairs = _truncate_label(pairs, label_to_shrink)
        rendered = _render_checkpoint(pairs)
        truncated = True

    # Last resort: hard-trim the longest value while preserving all labels.
    while estimate_tokens(rendered) > max_tokens:
        pairs = _hard_trim_longest(pairs)
        rendered = _render_checkpoint(pairs)
        truncated = True
        if all(len(value) <= 3 for _, value in pairs):
            break

    return CheckpointResult(
        text=rendered,
        token_estimate=estimate_tokens(rendered),
        truncated=truncated,
    )


def compile_agent_task(task: AgentTask) -> str:
    """Serialize a task to minified inter-agent JSON (Layer 5 bus)."""
    payload: dict[str, object] = {_FIELD_TO_WIRE["action"]: task.action}
    for field_name, wire_key in _FIELD_TO_WIRE.items():
        if field_name == "action":
            continue
        value = getattr(task, field_name)
        if value is not None:
            payload[wire_key] = value
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def parse_agent_task(wire: str) -> AgentTask:
    """Parse and validate a minified task envelope.

    Raises:
        InputError: For invalid JSON, unknown keys, or invalid task fields.
    """
    try:
        decoded = json.loads(wire)
    except json.JSONDecodeError as decode_error:
        raise InputError(f"agent-bus payload is not valid JSON: {decode_error}") from decode_error
    if not isinstance(decoded, dict):
        raise InputError("agent-bus payload must be a JSON object")

    unknown_keys = set(decoded) - set(_WIRE_TO_FIELD)
    if unknown_keys:
        allowed = ", ".join(sorted(_WIRE_TO_FIELD))
        raise InputError(
            f"unknown agent-bus key(s): {', '.join(sorted(unknown_keys))}; allowed: {allowed}"
        )

    action = decoded.get("t")
    if not isinstance(action, str) or not action:
        raise InputError("agent-bus field 't' (action) is required and must be a non-empty string")

    line_value = decoded.get("ln")
    if line_value is not None and (isinstance(line_value, bool) or not isinstance(line_value, int)):
        raise InputError("agent-bus field 'ln' (line) must be an integer")

    return AgentTask(
        action=action,
        file=_optional_str(decoded, "f", "file"),
        line=line_value,
        error=_optional_str(decoded, "err", "error"),
        request=_optional_str(decoded, "req", "request"),
        context=_optional_str(decoded, "c", "context"),
    )


def session_state_from_mapping(payload: Mapping[str, object]) -> SessionState:
    """Build :class:`SessionState` from a JSON object (CLI convenience)."""
    stack_value = payload.get("stack")
    if not isinstance(stack_value, str) or not stack_value.strip():
        raise InputError("checkpoint state requires a non-empty string field 'stack'")

    done_value = payload.get("done", ())
    if isinstance(done_value, str):
        done_items = tuple(item.strip() for item in done_value.split(",") if item.strip())
    elif isinstance(done_value, list) and all(isinstance(item, str) for item in done_value):
        done_items = tuple(item.strip() for item in done_value if item.strip())
    else:
        raise InputError("checkpoint 'done' must be a string or list of strings")

    return SessionState(
        stack=stack_value.strip(),
        done=done_items,
        wip=_mapping_str(payload, "wip"),
        blocker=_mapping_str(payload, "blocker"),
        next_step=_mapping_str(payload, "next"),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_sections(text: str) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {name: [] for name in _SECTION_ALIASES}
    current_section = "goal"

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        heading = _detect_section(stripped)
        if heading is not None:
            current_section = heading
            remainder = _strip_section_label(stripped)
            if remainder:
                buckets[current_section].append(remainder)
            continue
        content = _BULLET_PREFIX.sub("", stripped).strip()
        if content:
            buckets[current_section].append(content)

    # If nothing was recognised, treat the whole text as goal material.
    if not any(buckets.values()):
        buckets["goal"] = [line.strip() for line in text.splitlines() if line.strip()]
    return buckets


def _detect_section(line: str) -> str | None:
    normalized = re.sub(r"^#+\s*", "", line).strip().lower().rstrip(":")
    for section_name, aliases in _SECTION_ALIASES.items():
        if any(normalized == alias or normalized.startswith(f"{alias}:") for alias in aliases):
            return section_name
    return None


def _strip_section_label(line: str) -> str:
    if ":" not in line:
        return ""
    return line.split(":", 1)[1].strip()


def _render_packed_sections(
    sections: dict[str, list[str]],
    tier: CompressionTier,
    config: NanotokConfig,
) -> str:
    titles = {
        "goal": "GOAL",
        "stack": "STACK",
        "constraints": "CONSTRAINTS",
        "acceptance": "ACCEPTANCE",
        "out_of_scope": "OUT-OF-SCOPE",
    }
    rendered_parts: list[str] = []
    for section_name, items in sections.items():
        if not items:
            continue
        compressed_items = [
            compress_prose(item, tier=tier, config=config) for item in items
        ]
        compressed_items = [item for item in compressed_items if item]
        if not compressed_items:
            continue
        joined = "; ".join(compressed_items)
        rendered_parts.append(f"{titles[section_name]}: {joined}")
    return "\n".join(rendered_parts) if rendered_parts else compress_prose(
        " ".join(item for items in sections.values() for item in items), tier=tier, config=config
    )


def _shrink_sections(sections: dict[str, list[str]]) -> dict[str, list[str]]:
    """Drop lowest-priority content first to satisfy the pack ratio."""
    shrunk = {name: list(values) for name, values in sections.items()}
    drop_order = ("out_of_scope", "acceptance", "constraints", "stack", "goal")
    for section_name in drop_order:
        if len(shrunk[section_name]) > 1:
            shrunk[section_name] = shrunk[section_name][: max(1, len(shrunk[section_name]) // 2)]
    return shrunk


def _render_checkpoint(pairs: list[tuple[str, str]]) -> str:
    body = "\n".join(f"{label}: {value}" for label, value in pairs if value)
    return f"[NANOTOK SNAPSHOT]\n{body}"


def _truncate_label(pairs: list[tuple[str, str]], label: str) -> list[tuple[str, str]]:
    updated: list[tuple[str, str]] = []
    for pair_label, pair_value in pairs:
        if pair_label != label or not pair_value:
            updated.append((pair_label, pair_value))
            continue
        words = pair_value.split()
        trimmed = " ".join(words[: max(2, len(words) // 2)])
        updated.append((pair_label, trimmed))
    return updated


def _hard_trim_longest(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not pairs:
        return pairs
    longest_index = max(range(len(pairs)), key=lambda index: len(pairs[index][1]))
    label, value = pairs[longest_index]
    trimmed_value = value[: max(3, len(value) - 6)].rstrip() + "..."
    updated = list(pairs)
    updated[longest_index] = (label, trimmed_value)
    return updated


def _optional_str(decoded: Mapping[str, object], key: str, label: str) -> str | None:
    value = decoded.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"agent-bus field '{key}' ({label}) must be a string")
    stripped = value.strip()
    return stripped or None


def _mapping_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InputError(f"checkpoint '{key}' must be a string")
    return value.strip()
