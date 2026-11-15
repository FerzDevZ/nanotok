import json

import pytest

from nanotok.errors import InputError
from nanotok.models import AgentTask, CompressionTier, SessionState
from nanotok.session import (
    build_checkpoint,
    compile_agent_task,
    pack_spec,
    parse_agent_task,
    session_state_from_mapping,
)


def test_pack_spec_reduces_verbose_text() -> None:
    verbose = (
        "Goal: We need to build a login page for the application.\n"
        "Stack: Next.js 15, TypeScript, Prisma, PostgreSQL.\n"
        "Constraints: Must use server actions and must validate input with zod.\n"
        "Acceptance: User can login, invalid credentials show error, session persists.\n"
        "Out of scope: Social login and password reset.\n"
    )
    packed = pack_spec(verbose, tier=CompressionTier.L2)
    assert packed.text
    assert packed.report.original_tokens > 0
    assert "GOAL" in packed.text or "goal" in packed.text.lower()
    assert packed.report.compressed_tokens <= packed.report.original_tokens


def test_checkpoint_respects_token_budget() -> None:
    state = SessionState(
        stack="Next.js 15 (App Router) + Drizzle ORM + Neon Postgres + Zod",
        done=("Auth (Lucia)", "schema.ts", "POST /api/orders"),
        wip="Webhook handler @ app/api/webhooks/stripe/route.ts",
        blocker="Raw body signature verification failing -> need req.text()",
        next_step="Fix raw body parse -> run stripe listen test",
    )
    checkpoint = build_checkpoint(state)
    assert "[NANOTOK SNAPSHOT]" in checkpoint.text
    assert checkpoint.token_estimate <= 120  # small headroom over estimator variance
    assert "Stack:" in checkpoint.text


def test_agent_bus_roundtrip() -> None:
    task = AgentTask(
        action="fix_bug",
        file="src/auth.ts",
        line=88,
        error="TokenExpiredError",
        request="Add refresh rotation w/ 7d TTL",
    )
    wire = compile_agent_task(task)
    decoded = json.loads(wire)
    assert decoded["t"] == "fix_bug"
    assert decoded["f"] == "src/auth.ts"
    parsed = parse_agent_task(wire)
    assert parsed == task


def test_agent_bus_rejects_unknown_key() -> None:
    with pytest.raises(InputError):
        parse_agent_task('{"t":"fix_bug","x":"nope"}')


def test_agent_bus_rejects_unknown_action() -> None:
    with pytest.raises(InputError):
        parse_agent_task('{"t":"launch_rocket"}')


def test_session_state_from_mapping_accepts_string_done() -> None:
    state = session_state_from_mapping({"stack": "Node + TS", "done": "a, b", "next": "c"})
    assert state.stack == "Node + TS"
    assert state.done == ("a", "b")
    assert state.next_step == "c"
