import json
import subprocess
import sys
from pathlib import Path


def run_cli(
    *args: str, cwd: Path | None = None, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "nanotok", *args],
        cwd=str(cwd) if cwd else None,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_version() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert "nanotok 3.0.0" in (result.stdout + result.stderr)


def test_cli_estimate_stdin() -> None:
    result = run_cli("estimate", "-", input_text="hello world from nanotok")
    assert result.returncode == 0
    assert int(result.stdout.strip()) > 0


def test_cli_sanitize_file(tmp_path: Path) -> None:
    log_file = tmp_path / "err.log"
    log_file.write_text(
        "Error\n"
        "    at a (node_modules/x/index.js:1:1)\n"
        "    at b (src/app.ts:2:3)\n",
        encoding="utf-8",
    )
    result = run_cli("sanitize", str(log_file))
    assert result.returncode == 0
    assert "src/app.ts:2:3" in result.stdout
    assert "node_modules/x" not in result.stdout
    assert "nanotok sanitize" in result.stderr


def test_cli_compress_reduces_prose(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "Please note that you should make sure to restart the server in order to apply changes.\n",
        encoding="utf-8",
    )
    result = run_cli("compress", str(doc), "--tier", "L1")
    assert result.returncode == 0
    assert len(result.stdout) < len(doc.read_text(encoding="utf-8"))
    assert "nanotok compress" in result.stderr


def test_cli_pack_outputs_sections(tmp_path: Path) -> None:
    spec = tmp_path / "prd.md"
    spec.write_text(
        "Goal: build auth\nStack: Next.js, Prisma\nConstraints: validate input\n"
        "Acceptance: login works\nOut of scope: SSO\n",
        encoding="utf-8",
    )
    result = run_cli("pack", str(spec))
    assert result.returncode == 0
    assert "GOAL" in result.stdout or "STACK" in result.stdout


def test_cli_checkpoint_from_flags() -> None:
    result = run_cli(
        "checkpoint",
        "--stack",
        "Next.js + Prisma",
        "--done",
        "auth,schema",
        "--wip",
        "webhook @ api/webhooks.ts",
        "--next",
        "add tests",
    )
    assert result.returncode == 0
    assert "[NANOTOK SNAPSHOT]" in result.stdout
    assert "Stack:" in result.stdout


def test_cli_diff_outputs_patch(tmp_path: Path) -> None:
    old = tmp_path / "old.ts"
    new = tmp_path / "new.ts"
    old.write_text("export const a = 1;\nexport const b = 2;\n" * 30, encoding="utf-8")
    new.write_text(old.read_text(encoding="utf-8").replace("b = 2", "b = 3", 1), encoding="utf-8")
    result = run_cli("diff", str(old), str(new), "--path", "src/file.ts")
    assert result.returncode == 0
    assert "b = 3" in result.stdout
    assert "nanotok diff" in result.stderr


def test_cli_route_returns_json() -> None:
    result = run_cli("route", "Fix TypeError at src/app.ts:10", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["intent"] == "DEBUG"
    assert "contract" in payload
    assert "tier_decision" in payload
    assert "thresholds" in payload["tier_decision"]


def test_cli_tier_returns_detailed_escalation() -> None:
    result = run_cli("tier", "Fix TypeError at src/app.ts:10", "--attachments", "5")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "tier"
    assert payload["escalated"] is True
    assert payload["tier_decision"]["triggers"][0]["name"] == "attachment_count"


def test_cli_init_agent_skill_target(tmp_path: Path) -> None:
    result = run_cli("init", "--dir", str(tmp_path), "--target", "agent-skill")
    assert result.returncode == 0
    skill_path = tmp_path / ".agents/skills/nanotok/SKILL.md"
    assert skill_path.exists()
    assert "name: nanotok" in skill_path.read_text(encoding="utf-8")


def test_cli_bus_compile_and_decode() -> None:
    compiled = run_cli(
        "bus",
        "--type",
        "fix_bug",
        "--file",
        "src/auth.ts",
        "--line",
        "88",
        "--error",
        "Boom",
    )
    assert compiled.returncode == 0
    wire = compiled.stdout.strip()
    assert '"t":"fix_bug"' in wire
    decoded = run_cli("bus", "--decode", wire)
    assert decoded.returncode == 0
    payload = json.loads(decoded.stdout)
    assert payload["action"] == "fix_bug"
    assert payload["line"] == 88


def test_cli_bench_reports_savings(tmp_path: Path) -> None:
    base = tmp_path / "base.txt"
    nano = tmp_path / "nano.txt"
    base.write_text(
        "This is a very long and verbose explanation with many unnecessary words.",
        encoding="utf-8",
    )
    nano.write_text("Verbose explanation.", encoding="utf-8")
    result = run_cli("bench", str(base), str(nano))
    assert result.returncode == 0
    assert "Tokens Saved" in result.stdout
    assert "Density Gain" in result.stdout


def test_cli_init_and_config(tmp_path: Path) -> None:
    result = run_cli("init", "--dir", str(tmp_path), "--target", "all")
    assert result.returncode == 0
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "nanotok.config.json").exists()
    assert (tmp_path / ".agents/skills/nanotok/SKILL.md").exists()

    show = run_cli("--config", str(tmp_path / "nanotok.config.json"), "config", "show")
    assert show.returncode == 0
    cfg = json.loads(show.stdout)
    assert cfg["default_tier"] == "L1"

    validate = run_cli("--config", str(tmp_path / "nanotok.config.json"), "config", "validate")
    assert validate.returncode == 0
    assert "[OK]" in validate.stdout


def test_cli_invalid_input_returns_exit_2() -> None:
    result = run_cli("bus", "--decode", "{not-json")
    assert result.returncode == 2
    assert "nanotok:" in result.stderr
