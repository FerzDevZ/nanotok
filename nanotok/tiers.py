"""LAYER 4 — adaptive compression tier selection and auto-escalation."""

from __future__ import annotations

from nanotok.config import DEFAULT_CONFIG, NanotokConfig
from nanotok.models import CompressionTier, TierDecision, TierTrigger


def select_tier(
    requested: CompressionTier | None,
    *,
    token_count: int = 0,
    attachment_count: int = 0,
    config: NanotokConfig | None = None,
) -> TierDecision:
    """Choose the effective tier, escalating once when context is large.

    Escalation is monotonic and capped at :attr:`CompressionTier.L3`. It never
    *reduces* aggressiveness, because a 40k-token prompt arriving at L1 is
    already over budget.
    """
    resolved_config = config or DEFAULT_CONFIG
    base_tier = requested or resolved_config.default_tier
    reasons: list[str] = []
    triggers: list[TierTrigger] = []

    effective_tier = base_tier
    if token_count > resolved_config.auto_escalate_threshold_tokens:
        escalated_tier = effective_tier.escalate()
        triggers.append(
            TierTrigger(
                name="token_count",
                value=token_count,
                threshold=resolved_config.auto_escalate_threshold_tokens,
                from_tier=effective_tier,
                to_tier=escalated_tier,
            )
        )
        effective_tier = escalated_tier
        reasons.append(
            f"token_count {token_count} > {resolved_config.auto_escalate_threshold_tokens}"
        )
    if attachment_count > resolved_config.auto_escalate_attachment_count:
        escalated_tier = effective_tier.escalate()
        triggers.append(
            TierTrigger(
                name="attachment_count",
                value=attachment_count,
                threshold=resolved_config.auto_escalate_attachment_count,
                from_tier=effective_tier,
                to_tier=escalated_tier,
            )
        )
        effective_tier = escalated_tier
        reasons.append(
            f"attachments {attachment_count} > {resolved_config.auto_escalate_attachment_count}"
        )

    if not reasons:
        return TierDecision(
            requested=requested,
            effective=base_tier,
            reason="requested tier retained",
            token_count=token_count,
            attachment_count=attachment_count,
            token_threshold=resolved_config.auto_escalate_threshold_tokens,
            attachment_threshold=resolved_config.auto_escalate_attachment_count,
            triggers=(),
        )

    return TierDecision(
        requested=requested,
        effective=effective_tier,
        reason="auto-escalation: " + "; ".join(reasons),
        token_count=token_count,
        attachment_count=attachment_count,
        token_threshold=resolved_config.auto_escalate_threshold_tokens,
        attachment_threshold=resolved_config.auto_escalate_attachment_count,
        triggers=tuple(triggers),
    )
