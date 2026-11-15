---
name: nanotok
description: Ultra-high-density token compression engine and CLI toolkit. Use when sanitizing noisy logs/stack traces, compressing prompts/specs, producing diff-first patches, routing prompt intent/tier, packing specs, or checkpointing long agent sessions with nanotok.
metadata:
  origin: local
  version: "3.0.0"
---

# nanotok v3.0 — Ultra-High-Density Token Compression Engine

Operate strictly under the `nanotok` v3.0 protocol. Target 70-92% output token reduction while maintaining 100% syntax validity and zero-bug precision.

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
