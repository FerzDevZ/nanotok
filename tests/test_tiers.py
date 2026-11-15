from nanotok.models import CompressionTier
from nanotok.tiers import select_tier


def test_default_tier_retained_when_under_thresholds() -> None:
    decision = select_tier(CompressionTier.L1, token_count=1000, attachment_count=1)
    assert decision.effective is CompressionTier.L1
    assert decision.escalated is False


def test_escalates_on_large_token_count() -> None:
    decision = select_tier(CompressionTier.L1, token_count=20_000, attachment_count=1)
    assert decision.effective is CompressionTier.L2
    assert decision.escalated is True
    assert "token_count" in decision.reason


def test_escalates_on_many_attachments() -> None:
    decision = select_tier(CompressionTier.L1, token_count=100, attachment_count=5)
    assert decision.effective is CompressionTier.L2
    assert "attachments" in decision.reason


def test_escalation_clamps_at_l3() -> None:
    decision = select_tier(CompressionTier.L3, token_count=50_000, attachment_count=10)
    assert decision.effective is CompressionTier.L3
