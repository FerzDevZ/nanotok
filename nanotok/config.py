"""Configuration loading, validation, and discovery.

The on-disk schema is intentionally a strict superset of ``rancangan.md`` §8.2:
every field has a default, so an empty ``nanotok.config.json`` is valid, but an
unknown key or a wrongly typed value is a hard error instead of a silent
fallback. Silent fallbacks are how a compression dial quietly stops working.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from nanotok.errors import ConfigError
from nanotok.models import CompressionTier

CONFIG_FILENAME = "nanotok.config.json"

DEFAULT_OPERATORS: dict[str, str] = {
    "causes": "->",
    "from": "<-",
    "returns": "=>",
    "and": "+",
    "conflict": "!=",
    "with": "w/",
    "without": "w/o",
    "because": "bc",
    "location": "@",
    "approx": "~",
}


@dataclass(frozen=True)
class InvariantSettings:
    """Hard guardrails that compression must never break."""

    preserve_code_identifiers: bool = True
    preserve_cli_flags: bool = True
    preserve_error_literals: bool = True
    warn_prefix_on_destructive: str = "[!WARN]"
    forbid_lazy_placeholders: bool = True


@dataclass(frozen=True)
class SanitizerSettings:
    """Layer 0 knobs."""

    keep_path_markers: tuple[str, ...] = (
        "/src/",
        "/app/",
        "/lib/",
        "/pages/",
        "file://",
    )
    max_repeat_marker: bool = True


@dataclass(frozen=True)
class NanotokConfig:
    """Validated runtime configuration for all six layers."""

    default_tier: CompressionTier = CompressionTier.L1
    auto_escalate_threshold_tokens: int = 16_000
    auto_escalate_attachment_count: int = 3
    diff_threshold_ratio: float = 0.5
    max_debug_prose_lines: int = 2
    max_checkpoint_tokens: int = 90
    pack_target_ratio: float = 0.30
    operators: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_OPERATORS))
    invariants: InvariantSettings = field(default_factory=InvariantSettings)
    sanitizer: SanitizerSettings = field(default_factory=SanitizerSettings)

    def to_mapping(self) -> dict[str, object]:
        """Render a JSON-serialisable view for ``nanotok config show``."""
        return {
            "skill": "nanotok",
            "version": "3.0.0",
            "default_tier": self.default_tier.value,
            "auto_escalate_threshold_tokens": self.auto_escalate_threshold_tokens,
            "auto_escalate_attachment_count": self.auto_escalate_attachment_count,
            "diff_threshold_ratio": self.diff_threshold_ratio,
            "max_debug_prose_lines": self.max_debug_prose_lines,
            "max_checkpoint_tokens": self.max_checkpoint_tokens,
            "pack_target_ratio": self.pack_target_ratio,
            "operators": dict(self.operators),
            "invariants": {
                "preserve_code_identifiers": self.invariants.preserve_code_identifiers,
                "preserve_cli_flags": self.invariants.preserve_cli_flags,
                "preserve_error_literals": self.invariants.preserve_error_literals,
                "warn_prefix_on_destructive": self.invariants.warn_prefix_on_destructive,
                "forbid_lazy_placeholders": self.invariants.forbid_lazy_placeholders,
            },
            "sanitizer": {
                "keep_path_markers": list(self.sanitizer.keep_path_markers),
                "max_repeat_marker": self.sanitizer.max_repeat_marker,
            },
        }


DEFAULT_CONFIG = NanotokConfig()

_TOP_LEVEL_KEYS = frozenset(DEFAULT_CONFIG.to_mapping())
_OPERATOR_KEYS = frozenset(DEFAULT_OPERATORS)
_INVARIANT_KEYS = frozenset(
    {
        "preserve_code_identifiers",
        "preserve_cli_flags",
        "preserve_error_literals",
        "warn_prefix_on_destructive",
        "forbid_lazy_placeholders",
    }
)
_SANITIZER_KEYS = frozenset({"keep_path_markers", "max_repeat_marker"})


def load_config(path: Path | None) -> NanotokConfig:
    """Load and validate a config file, or return defaults when ``path`` is None.

    Raises:
        ConfigError: For unreadable files, invalid JSON, or schema violations.
    """
    if path is None:
        return DEFAULT_CONFIG
    try:
        raw_payload = path.read_text(encoding="utf-8")
    except OSError as read_error:
        raise ConfigError(f"cannot read config {path}: {read_error}") from read_error
    try:
        parsed = json.loads(raw_payload)
    except json.JSONDecodeError as decode_error:
        raise ConfigError(f"invalid JSON in {path}: {decode_error}") from decode_error
    if not isinstance(parsed, dict):
        raise ConfigError(f"{path} must contain a JSON object, got {type(parsed).__name__}")
    return config_from_mapping(parsed)


def config_from_mapping(payload: Mapping[str, object]) -> NanotokConfig:
    """Validate a decoded mapping and build a config instance.

    Raises:
        ConfigError: When a key is unknown or a value has the wrong type/range.
    """
    unknown_keys = set(payload) - _TOP_LEVEL_KEYS
    if unknown_keys:
        allowed = ", ".join(sorted(_TOP_LEVEL_KEYS))
        raise ConfigError(
            f"unknown config key(s): {', '.join(sorted(unknown_keys))}; allowed: {allowed}"
        )

    default_mapping = DEFAULT_CONFIG.to_mapping()
    tier_label = payload.get("default_tier", default_mapping["default_tier"])
    if not isinstance(tier_label, str):
        raise ConfigError("default_tier must be a string: L1, L2, or L3")
    default_tier = CompressionTier.parse(tier_label)

    threshold_tokens = _positive_int(
        payload, "auto_escalate_threshold_tokens", DEFAULT_CONFIG.auto_escalate_threshold_tokens
    )
    threshold_attachments = _positive_int(
        payload,
        "auto_escalate_attachment_count",
        DEFAULT_CONFIG.auto_escalate_attachment_count,
    )
    max_debug_lines = _positive_int(
        payload, "max_debug_prose_lines", DEFAULT_CONFIG.max_debug_prose_lines
    )
    max_checkpoint = _positive_int(
        payload, "max_checkpoint_tokens", DEFAULT_CONFIG.max_checkpoint_tokens
    )
    diff_ratio = _ratio(payload, "diff_threshold_ratio", DEFAULT_CONFIG.diff_threshold_ratio)
    pack_ratio = _ratio(payload, "pack_target_ratio", DEFAULT_CONFIG.pack_target_ratio)

    operators = _operators(payload.get("operators"))
    invariants = _invariants(payload.get("invariants"))
    sanitizer = _sanitizer(payload.get("sanitizer"))

    return NanotokConfig(
        default_tier=default_tier,
        auto_escalate_threshold_tokens=threshold_tokens,
        auto_escalate_attachment_count=threshold_attachments,
        diff_threshold_ratio=diff_ratio,
        max_debug_prose_lines=max_debug_lines,
        max_checkpoint_tokens=max_checkpoint,
        pack_target_ratio=pack_ratio,
        operators=operators,
        invariants=invariants,
        sanitizer=sanitizer,
    )


def discover_config(start_dir: Path) -> Path | None:
    """Walk upward from ``start_dir`` looking for ``nanotok.config.json``."""
    current = start_dir.resolve()
    for _ in range(64):
        candidate = current / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent
    return None


def _positive_int(payload: Mapping[str, object], key: str, fallback: int) -> int:
    value = payload.get(key, fallback)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer, got {type(value).__name__}")
    if value < 1:
        raise ConfigError(f"{key} must be >= 1, got {value}")
    return value


def _ratio(payload: Mapping[str, object], key: str, fallback: float) -> float:
    value = payload.get(key, fallback)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number, got {type(value).__name__}")
    ratio = float(value)
    if not 0.0 < ratio <= 1.0:
        raise ConfigError(f"{key} must be in (0, 1], got {ratio}")
    return ratio


def _operators(raw_value: object) -> Mapping[str, str]:
    if raw_value is None:
        return dict(DEFAULT_OPERATORS)
    if not isinstance(raw_value, dict):
        raise ConfigError("operators must be an object mapping names to symbols")
    unknown = set(raw_value) - _OPERATOR_KEYS
    if unknown:
        raise ConfigError(
            f"unknown operator key(s): {', '.join(sorted(unknown))}; "
            f"allowed: {', '.join(sorted(_OPERATOR_KEYS))}"
        )
    resolved = dict(DEFAULT_OPERATORS)
    for operator_name, symbol in raw_value.items():
        if not isinstance(operator_name, str) or not isinstance(symbol, str):
            raise ConfigError("operators entries must be string -> string")
        if not symbol.strip():
            raise ConfigError(f"operator {operator_name!r} cannot be empty")
        resolved[operator_name] = symbol
    return resolved


def _invariants(raw_value: object) -> InvariantSettings:
    if raw_value is None:
        return InvariantSettings()
    if not isinstance(raw_value, dict):
        raise ConfigError("invariants must be an object")
    unknown = set(raw_value) - _INVARIANT_KEYS
    if unknown:
        raise ConfigError(
            f"unknown invariant key(s): {', '.join(sorted(unknown))}; "
            f"allowed: {', '.join(sorted(_INVARIANT_KEYS))}"
        )
    defaults = InvariantSettings()
    boolean_fields = {
        "preserve_code_identifiers": defaults.preserve_code_identifiers,
        "preserve_cli_flags": defaults.preserve_cli_flags,
        "preserve_error_literals": defaults.preserve_error_literals,
        "forbid_lazy_placeholders": defaults.forbid_lazy_placeholders,
    }
    resolved: dict[str, bool] = {}
    for field_name, default_value in boolean_fields.items():
        candidate = raw_value.get(field_name, default_value)
        if not isinstance(candidate, bool):
            raise ConfigError(f"invariants.{field_name} must be a boolean")
        resolved[field_name] = candidate
    warn_prefix = raw_value.get(
        "warn_prefix_on_destructive", defaults.warn_prefix_on_destructive
    )
    if not isinstance(warn_prefix, str) or not warn_prefix.strip():
        raise ConfigError("invariants.warn_prefix_on_destructive must be a non-empty string")
    return InvariantSettings(
        preserve_code_identifiers=resolved["preserve_code_identifiers"],
        preserve_cli_flags=resolved["preserve_cli_flags"],
        preserve_error_literals=resolved["preserve_error_literals"],
        warn_prefix_on_destructive=warn_prefix,
        forbid_lazy_placeholders=resolved["forbid_lazy_placeholders"],
    )


def _sanitizer(raw_value: object) -> SanitizerSettings:
    if raw_value is None:
        return SanitizerSettings()
    if not isinstance(raw_value, dict):
        raise ConfigError("sanitizer must be an object")
    unknown = set(raw_value) - _SANITIZER_KEYS
    if unknown:
        raise ConfigError(
            f"unknown sanitizer key(s): {', '.join(sorted(unknown))}; "
            f"allowed: {', '.join(sorted(_SANITIZER_KEYS))}"
        )
    defaults = SanitizerSettings()
    markers_value = raw_value.get("keep_path_markers", list(defaults.keep_path_markers))
    if not isinstance(markers_value, list) or not all(
        isinstance(marker, str) and marker for marker in markers_value
    ):
        raise ConfigError("sanitizer.keep_path_markers must be a list of non-empty strings")
    repeat_marker = raw_value.get("max_repeat_marker", defaults.max_repeat_marker)
    if not isinstance(repeat_marker, bool):
        raise ConfigError("sanitizer.max_repeat_marker must be a boolean")
    return SanitizerSettings(
        keep_path_markers=tuple(markers_value),
        max_repeat_marker=repeat_marker,
    )
