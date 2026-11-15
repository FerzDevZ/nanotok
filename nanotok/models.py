"""Shared, dependency-free types used across all six compression layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from nanotok.errors import InputError


class CompressionTier(str, Enum):
    """Compression aggressiveness, ordered from terse to machine-only."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"

    def __str__(self) -> str:
        return self.value

    @property
    def rank(self) -> int:
        """Zero-based aggressiveness rank, used for one-step escalation."""
        return _TIER_ORDER.index(self)

    @classmethod
    def parse(cls, value: object) -> CompressionTier:
        """Parse a user/config label such as ``"l2"`` into a tier.

        Raises:
            InputError: If the label is not one of ``L1``, ``L2``, ``L3``.
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            label = value.strip().upper()
            for tier in cls:
                if tier.value == label:
                    return tier
        raise InputError(f"unknown compression tier {value!r}; expected L1, L2, or L3")

    def escalate(self) -> CompressionTier:
        """Return the next tier, clamped at :attr:`L3`."""
        return _TIER_ORDER[min(self.rank + 1, len(_TIER_ORDER) - 1)]


_TIER_ORDER: tuple[CompressionTier, ...] = (
    CompressionTier.L1,
    CompressionTier.L2,
    CompressionTier.L3,
)


class Intent(str, Enum):
    """Prompt intent detected by Layer 3."""

    CODE_GEN = "CODE_GEN"
    DEBUG = "DEBUG"
    COMPARE = "COMPARE"
    EXPLAIN = "EXPLAIN"
    CLI = "CLI"
    GENERAL = "GENERAL"

    def __str__(self) -> str:
        return self.value


class PatchFormat(str, Enum):
    """Output format selected by the Layer 1 diff engine."""

    AUTO = "auto"
    NOOP = "noop"
    FULL_FILE = "full"
    ANCHOR = "anchor"
    UNIFIED_DIFF = "unified"
    SEARCH_REPLACE = "search"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CompressionReport:
    """Token accounting for one compression pass."""

    original_tokens: int
    compressed_tokens: int

    @property
    def saved_tokens(self) -> int:
        return max(0, self.original_tokens - self.compressed_tokens)

    @property
    def saved_percent(self) -> float:
        if self.original_tokens <= 0:
            return 0.0
        return round(self.saved_tokens / self.original_tokens * 100, 2)

    @property
    def density_gain(self) -> float:
        if self.compressed_tokens <= 0:
            return 1.0
        return round(self.original_tokens / self.compressed_tokens, 2)

    def to_mapping(self) -> dict[str, int | float]:
        return {
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "saved_tokens": self.saved_tokens,
            "saved_percent": self.saved_percent,
            "density_gain": self.density_gain,
        }


@dataclass(frozen=True)
class TierTrigger:
    """One escalation trigger with measured value and configured threshold."""

    name: str
    value: int
    threshold: int
    from_tier: CompressionTier
    to_tier: CompressionTier


@dataclass(frozen=True)
class TierDecision:
    """Result of Layer 4 tier selection, including why escalation happened."""

    requested: CompressionTier | None
    effective: CompressionTier
    reason: str
    token_count: int = 0
    attachment_count: int = 0
    token_threshold: int = 0
    attachment_threshold: int = 0
    triggers: tuple[TierTrigger, ...] = ()

    @property
    def escalated(self) -> bool:
        return self.requested is not None and self.requested != self.effective

    @property
    def base_tier(self) -> CompressionTier:
        return self.requested or CompressionTier.L1

    def to_mapping(self) -> dict[str, object]:
        return {
            "requested": self.requested.value if self.requested else None,
            "base": self.base_tier.value,
            "effective": self.effective.value,
            "escalated": self.escalated or self.base_tier != self.effective,
            "reason": self.reason,
            "token_count": self.token_count,
            "attachment_count": self.attachment_count,
            "thresholds": {
                "auto_escalate_tokens": self.token_threshold,
                "auto_escalate_attachments": self.attachment_threshold,
            },
            "triggers": [
                {
                    "name": trigger.name,
                    "value": trigger.value,
                    "threshold": trigger.threshold,
                    "from_tier": trigger.from_tier.value,
                    "to_tier": trigger.to_tier.value,
                }
                for trigger in self.triggers
            ],
        }


AGENT_TASK_VERBS: frozenset[str] = frozenset(
    {"fix_bug", "add_feature", "refactor", "review", "test", "explain", "research", "plan"}
)


@dataclass(frozen=True)
class AgentTask:
    """Inter-agent task payload (Layer 5, minified JSON wire format)."""

    action: str
    file: str | None = None
    line: int | None = None
    error: str | None = None
    request: str | None = None
    context: str | None = None

    def __post_init__(self) -> None:
        if self.action not in AGENT_TASK_VERBS:
            allowed = ", ".join(sorted(AGENT_TASK_VERBS))
            raise InputError(f"unknown task verb {self.action!r}; allowed: {allowed}")
        if self.line is not None and self.line < 1:
            raise InputError(f"line must be >= 1, got {self.line}")


@dataclass(frozen=True)
class SessionState:
    """Project state captured for a <=90-token checkpoint snapshot."""

    stack: str
    done: tuple[str, ...] = ()
    wip: str = ""
    blocker: str = ""
    next_step: str = ""

    def as_lines(self) -> list[tuple[str, str]]:
        """Return ordered ``(label, value)`` pairs for rendering."""
        pairs: list[tuple[str, str]] = [("Stack", self.stack)]
        if self.done:
            pairs.append(("Done", ", ".join(self.done)))
        if self.wip:
            pairs.append(("WIP", self.wip))
        if self.blocker:
            pairs.append(("Blocker", self.blocker))
        if self.next_step:
            pairs.append(("Next", self.next_step))
        return pairs


@dataclass(frozen=True)
class DocumentSegment:
    """A protected or compressible slice of a mixed code/prose document."""

    text: str
    is_code: bool = field(default=False)
