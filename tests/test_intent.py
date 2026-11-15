from nanotok.intent import classify_intent, output_contract, route_prompt
from nanotok.models import CompressionTier, Intent


def test_classifies_debug_from_traceback() -> None:
    prompt = "Traceback (most recent call last):\n  File 'app.py', line 2\nTypeError: boom"
    assert classify_intent(prompt) is Intent.DEBUG


def test_classifies_compare() -> None:
    assert classify_intent("SQLite vs Postgres for background jobs, which one?") is Intent.COMPARE


def test_classifies_explain() -> None:
    assert classify_intent("Explain how database connection pooling works") is Intent.EXPLAIN


def test_classifies_cli_command() -> None:
    assert classify_intent("npm run build --silent") is Intent.CLI


def test_classifies_code_generation() -> None:
    prompt = "Refactor the auth middleware to use jwt verification"
    assert classify_intent(prompt) is Intent.CODE_GEN


def test_route_prompt_includes_contract_and_tier() -> None:
    routed = route_prompt("Fix TypeError at src/app.ts:10", tier_request=CompressionTier.L1)
    assert routed.intent is Intent.DEBUG
    assert routed.tier in {CompressionTier.L1, CompressionTier.L2, CompressionTier.L3}
    assert "Cause" in routed.contract or "2 lines" in routed.contract
    payload = routed.to_mapping()
    assert "tier_decision" in payload
    assert payload["tier_decision"]["thresholds"]["auto_escalate_tokens"] > 0
    assert "triggers" in payload["tier_decision"]


def test_output_contract_mentions_tier() -> None:
    contract = output_contract(Intent.CODE_GEN, CompressionTier.L3)
    assert "L3" in contract
    assert "raw" in contract.lower()
