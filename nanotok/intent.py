"""LAYER 3 — intent detection and output contracts.

The router answers two questions: "what shape should the reply take?" and "which
compression tier is appropriate?". Classification is deterministic and ordered so
that dangerous/urgent intents (DEBUG) win over ambiguous ones (COMPARE or
GENERAL). The router never calls an LLM; it produces instructions that an LLM
or CLI agent must follow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nanotok.config import DEFAULT_CONFIG, NanotokConfig
from nanotok.models import CompressionTier, Intent
from nanotok.tiers import select_tier
from nanotok.tokens import estimate_tokens

_TRACEBACK_MARKERS = (
    "traceback (most recent call last)",
    "exception:",
    "error:",
    "syntaxerror",
    "typeerror",
    "referenceerror",
    "segmentation fault",
    "panic:",
    "fatal:",
    "unhandledpromiserejection",
)
_DEBUG_KEYWORDS = re.compile(
    r"\b(error|exception|traceback|failed|failure|crash|broken|bug|gagal|kenapa|why\s+is)\b",
    re.IGNORECASE,
)
_COMPARE_KEYWORDS = re.compile(
    r"\b(compare|versus|vs\.?|trade[- ]?off|should i|lebih baik|pilih mana|mana yang)\b",
    re.IGNORECASE,
)
_EXPLAIN_KEYWORDS = re.compile(
    r"\b(explain|jelaskan|why|kenapa|how does|bagaimana cara|what is|apa itu)\b",
    re.IGNORECASE,
)
_CODE_KEYWORDS = re.compile(
    r"\b(refactor|implement|add|create|write|fix|patch|rename|remove|update|ubah|buat|tambah|hapus)\b",
    re.IGNORECASE,
)
_CLI_PREFIXES = (
    "npm ",
    "pnpm ",
    "yarn ",
    "pip ",
    "python ",
    "node ",
    "go ",
    "cargo ",
    "git ",
    "docker ",
    "kubectl ",
    "make ",
    "pytest",
    "mypy",
    "ruff",
    "curl ",
)


@dataclass(frozen=True)
class RoutedPrompt:
    """Prompt plus the inferred intent, tier, and LLM-facing contract."""

    prompt: str
    intent: Intent
    tier: CompressionTier
    contract: str
    escalated: bool
    escalation_reason: str
    token_estimate: int
    attachment_count: int = 0
    tier_decision: dict[str, object] | None = None

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "intent": self.intent.value,
            "tier": self.tier.value,
            "escalated": self.escalated,
            "escalation_reason": self.escalation_reason,
            "token_estimate": self.token_estimate,
            "attachment_count": self.attachment_count,
            "contract": self.contract,
        }
        if self.tier_decision is not None:
            payload["tier_decision"] = self.tier_decision
        return payload


def classify_intent(prompt: str) -> Intent:
    """Return the dominant :class:`Intent` for a user prompt.

    Debug wins because a fix contract (cause/fix, <=2 lines) is more valuable
    than accidentally explaining a stack trace in prose.
    """
    lowered_prompt = prompt.strip().lower()
    if not lowered_prompt:
        return Intent.GENERAL

    if _is_debug(lowered_prompt):
        return Intent.DEBUG
    if _COMPARE_KEYWORDS.search(lowered_prompt):
        return Intent.COMPARE
    if _EXPLAIN_KEYWORDS.search(lowered_prompt):
        return Intent.EXPLAIN
    if _looks_like_cli(lowered_prompt):
        return Intent.CLI
    if _CODE_KEYWORDS.search(lowered_prompt):
        return Intent.CODE_GEN
    return Intent.GENERAL


def output_contract(intent: Intent, tier: CompressionTier) -> str:
    """Describe the required output shape for ``intent`` at ``tier``."""
    contracts = {
        Intent.CODE_GEN: (
            "Output only code/patch/command block. 0 prose above/below. "
            "<50% change -> diff/anchor; >=50% or new file -> full file."
        ),
        Intent.CLI: "Output one shell command or one-liner (`cmd1 && cmd2`). 0 prose.",
        Intent.DEBUG: "Output exactly 2 lines: `Cause: <<=12 words>` and `Fix: <action/patch>`.",
        Intent.COMPARE: "Output compact decision matrix + `Pick: ... bc ...` (max 4 lines).",
        Intent.EXPLAIN: "Output <=3 bullets, each <=15 words. No paragraphs.",
        Intent.GENERAL: "Terse technical response. No greetings, no confirmations, no restatement.",
    }
    base_contract = contracts[intent]
    if tier is CompressionTier.L3:
        return f"{base_contract} [L3] raw machine: code/JSON/CLI only, comments <=4 words."
    if tier is CompressionTier.L2:
        return f"{base_contract} [L2] telegraphic: keywords + operators + code."
    return f"{base_contract} [L1] terse technical."


def route_prompt(
    prompt: str,
    *,
    tier_request: CompressionTier | None = None,
    attachment_count: int = 0,
    config: NanotokConfig | None = None,
) -> RoutedPrompt:
    """Classify, select tier, and emit the output contract for a prompt."""
    resolved_config = config or DEFAULT_CONFIG
    token_estimate = estimate_tokens(prompt)
    intent = classify_intent(prompt)
    tier_decision = select_tier(
        tier_request or resolved_config.default_tier,
        token_count=token_estimate,
        attachment_count=attachment_count,
        config=resolved_config,
    )
    escalated = tier_decision.escalated or tier_decision.base_tier != tier_decision.effective
    return RoutedPrompt(
        prompt=prompt,
        intent=intent,
        tier=tier_decision.effective,
        contract=output_contract(intent, tier_decision.effective),
        escalated=escalated,
        escalation_reason=tier_decision.reason,
        token_estimate=token_estimate,
        attachment_count=attachment_count,
        tier_decision=tier_decision.to_mapping(),
    )


def _is_debug(lowered_prompt: str) -> bool:
    if any(marker in lowered_prompt for marker in _TRACEBACK_MARKERS):
        return True
    if "File \"" in lowered_prompt or ("line " in lowered_prompt and "error" in lowered_prompt):
        return True
    return bool(_DEBUG_KEYWORDS.search(lowered_prompt))


def _looks_like_cli(lowered_prompt: str) -> bool:
    first_line = lowered_prompt.splitlines()[0].strip()
    return any(first_line.startswith(prefix) for prefix in _CLI_PREFIXES)
