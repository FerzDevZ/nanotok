# ruff: noqa: E501
"""Embedded deployable rule templates (SKILL, CLAUDE, Cursor, Windsurf, config).

Templates are embedded as module constants so ``nanotok init`` works after a
wheel install without relying on package-data files on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from nanotok.config import DEFAULT_CONFIG
from nanotok.errors import TemplateError

SKILL_BODY = """Operate strictly under the `nanotok` v3.0 protocol. Target 70-92% output token reduction while maintaining 100% syntax validity and zero-bug precision.

## CORE DIRECTIVES
1. **ZERO FLUFF:** Never output greetings, pleasantries, confirmations ("Sure", "Got it"), restatements of user prompts, or closing remarks.
2. **DIFF-FIRST (<50% RULE):** For edits <50% of a file, NEVER print the full file. Output ONLY changed blocks anchored with `// ... existing code ...` or `SEARCH/REPLACE` hunks. Full files ONLY for new files or >=50% rewrites.
3. **SILENT EXECUTION:** When asked for code, refactoring, or CLI commands, output ONLY the code/command block with zero prose unless explanation is explicitly requested.
4. **2-LINE ROOT CAUSE:** For debugging/errors, restrict prose strictly to:
   `Cause:` <root cause in <=12 words>
   `Fix:` <action or code patch>
5. **TELEGRAPHIC & SYMBOLIC GRAMMAR:** Strip articles and stop-words. Start sentences with imperative verbs or technical subjects. Use operators: `->` (causes/leads to), `<-` (from), `=>` (returns), `+` (and), `!=` (conflicts/not), `w/` (with), `w/o` (without), `bc` (because), `@` (at file:line).
6. **COMPRESSION TIERS (User-Selectable):**
   - `[L1]` (Default): Terse technical prose, zero fluff, diff-first.
   - `[L2]` (Caveman-Tech): Keywords + symbolic operators + code only.
   - `[L3]` (Raw Machine): 100% code/diff/JSON/CLI. Zero human prose.
7. **INPUT & SESSION PACKERS:**
   - `pack:` / `compress:` -> Rewrite user's verbose text into a dense structured spec (<30% original tokens) retaining all technical constraints.
   - `checkpoint:` / `compact:` -> Summarize current session state in <=90 tokens (`Stack`, `Done`, `WIP`, `Blocker`, `Next`).
8. **AGENTIC TOOL HYGIENE:** Read targeted line ranges instead of whole large files. Use quiet CLI flags (`--silent`, `-q`, `-s`). Batch independent tool calls. Never narrate completed tool actions.
9. **HARD INVARIANTS:** Never abbreviate actual code syntax, variable names, CLI flags, or error strings. Prefix destructive/breaking ops w/ `[!WARN]`. Never use lazy placeholders (`// TODO: implement`).

## CLI QUICK REFERENCE
- `nanotok sanitize [FILE|-]` -> strip ANSI/internal stack frames/log noise (Layer 0)
- `nanotok compress [FILE|-] --tier L1|L2|L3` -> telegraphic prose compression, code fences preserved (Layer 2)
- `nanotok pack [FILE|-]` -> dense spec/PRD (Layer 5)
- `nanotok checkpoint --stack ...` -> <=90-token session snapshot (Layer 5)
- `nanotok diff OLD NEW --path PATH` -> minimal patch/anchor/search-replace (Layer 1)
- `nanotok route "PROMPT"` / `nanotok tier "PROMPT"` -> intent + tier + escalation detail (Layer 3/4)
- `nanotok bus --type ...` -> minified inter-agent task JSON (Layer 5)
- `nanotok init --target agent-skill --dir .` -> install this skill at `.agents/skills/nanotok/SKILL.md`
"""

SKILL_TEMPLATE = f"# SKILL: nanotok v3.0 (Ultra-High-Density Token Compression Engine)\n\n{SKILL_BODY}"

AGENT_SKILL_TEMPLATE = f"""---
name: nanotok
description: Ultra-high-density token compression engine and CLI toolkit. Use when sanitizing noisy logs/stack traces, compressing prompts/specs, producing diff-first patches, routing prompt intent/tier, packing specs, or checkpointing long agent sessions with nanotok.
metadata:
  origin: local
  version: "3.0.0"
---

# nanotok v3.0 — Ultra-High-Density Token Compression Engine

{SKILL_BODY}
"""

AGENT_SKILL_RELATIVE_PATH = ".agents/skills/nanotok/SKILL.md"

TARGET_FILES: dict[str, tuple[str, ...]] = {
    "claude": ("CLAUDE.md",),
    "cursor": (".cursorrules",),
    "windsurf": (".windsurfrules",),
    "skill": ("SKILL.md",),
    "agent-skill": (AGENT_SKILL_RELATIVE_PATH,),
    "config": ("nanotok.config.json",),
    "all": (
        "CLAUDE.md",
        ".cursorrules",
        ".windsurfrules",
        "SKILL.md",
        AGENT_SKILL_RELATIVE_PATH,
        "nanotok.config.json",
    ),
}


def default_config_json() -> str:
    """Render the default config as formatted JSON (for init and CLI)."""
    payload = DEFAULT_CONFIG.to_mapping()
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def content_for(relative_path: str) -> str:
    """Return the canonical content for a deployable artifact path.

    Raises:
        TemplateError: If the path is not a known nanotok artifact.
    """
    if relative_path == "nanotok.config.json":
        return default_config_json()
    if relative_path == AGENT_SKILL_RELATIVE_PATH:
        return AGENT_SKILL_TEMPLATE
    if relative_path in {"CLAUDE.md", ".cursorrules", ".windsurfrules", "SKILL.md"}:
        return SKILL_TEMPLATE
    raise TemplateError(f"unknown template path {relative_path!r}")


def init_project(
    directory: Path,
    *,
    target: str = "all",
    force: bool = False,
) -> list[Path]:
    """Write rule/config files into ``directory``.

    Args:
        directory: Destination directory (created if missing).
        target: One of ``claude``, ``cursor``, ``windsurf``, ``skill``,
            ``agent-skill``, ``config``, or ``all``.
        force: Overwrite existing files when True.

    Returns:
        List of file paths that were written.

    Raises:
        TemplateError: For unknown targets, unwritable paths, or collisions
            when ``force`` is False.
    """
    if target not in TARGET_FILES:
        allowed = ", ".join(sorted(TARGET_FILES))
        raise TemplateError(f"unknown init target {target!r}; allowed: {allowed}")

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as mkdir_error:
        raise TemplateError(f"cannot create directory {directory}: {mkdir_error}") from mkdir_error

    written_files: list[Path] = []
    for relative_path in TARGET_FILES[target]:
        output_path = directory / relative_path
        if output_path.exists() and not force:
            raise TemplateError(
                f"{output_path} already exists; rerun with --force to overwrite"
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content_for(relative_path), encoding="utf-8")
        except OSError as write_error:
            raise TemplateError(f"cannot write {output_path}: {write_error}") from write_error
        written_files.append(output_path)
    return written_files
