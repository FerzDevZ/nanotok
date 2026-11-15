import json
from pathlib import Path

import pytest

from nanotok.errors import TemplateError
from nanotok.templates import content_for, init_project


def test_init_all_writes_expected_files(tmp_path: Path) -> None:
    written = init_project(tmp_path, target="all")
    relative = sorted(str(path.relative_to(tmp_path)) for path in written)
    assert relative == [
        ".agents/skills/nanotok/SKILL.md",
        ".cursorrules",
        ".windsurfrules",
        "CLAUDE.md",
        "SKILL.md",
        "nanotok.config.json",
    ]
    for path in written:
        assert path.exists()
        assert path.read_text(encoding="utf-8").strip()


def test_init_target_filter(tmp_path: Path) -> None:
    written = init_project(tmp_path, target="claude")
    assert [path.name for path in written] == ["CLAUDE.md"]


def test_init_refuses_overwrite_without_force(tmp_path: Path) -> None:
    init_project(tmp_path, target="claude")
    with pytest.raises(TemplateError, match="--force"):
        init_project(tmp_path, target="claude")


def test_init_overwrites_with_force(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text("old", encoding="utf-8")
    init_project(tmp_path, target="claude", force=True)
    assert "nanotok v3.0" in path.read_text(encoding="utf-8")


def test_init_agent_skill_target(tmp_path: Path) -> None:
    written = init_project(tmp_path, target="agent-skill")
    assert [str(path.relative_to(tmp_path)) for path in written] == [
        ".agents/skills/nanotok/SKILL.md"
    ]
    content = (tmp_path / ".agents/skills/nanotok/SKILL.md").read_text(encoding="utf-8")
    assert content.startswith("---\nname: nanotok")
    assert "nanotok init --target agent-skill --dir ." in content


def test_config_template_is_valid_json() -> None:
    payload = json.loads(content_for("nanotok.config.json"))
    assert payload["skill"] == "nanotok"
    assert payload["version"] == "3.0.0"
    assert payload["default_tier"] == "L1"


def test_unknown_template_raises() -> None:
    with pytest.raises(TemplateError):
        content_for("NOPE.md")
