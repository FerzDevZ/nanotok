# nanotok v3.0

**Ultra-high-density token compression engine & CLI toolkit** for agentic coding workflows.

`nanotok` reduces prompt, log, and specification overhead before it reaches an LLM (and compresses coordination artifacts between steps/agents) while preserving technical meaning. It is **deterministic, local/offline, and zero-runtime-dependency** (Python standard library only).

- **Design spec:** [`rancangan.md`](rancangan.md)
- **Implementation plan & contracts:** [`PLAN.md`](PLAN.md)
- **Local AgentSkills integration:** [`.agents/skills/nanotok/SKILL.md`](.agents/skills/nanotok/SKILL.md)

> **Design targets (from spec):** 70–92% output-token reduction and 45–68% context-window bloat reduction in high-noise scenarios, with a zero-syntax-loss goal for protected technical spans. **Realized savings depend on input noise/redundancy density** (see [Benchmarks](#benchmarks-measured)).

---

## Table of contents

- [Concept: information density over noise](#concept-information-density-over-noise)
- [Architecture: 6-layer pipeline](#architecture-6-layer-pipeline)
- [Key guarantees and invariants](#key-guarantees-and-invariants)
- [Requirements and installation](#requirements-and-installation)
- [Quick start](#quick-start)
- [CLI reference](#cli-reference)
- [I/O contract and exit codes](#io-contract-and-exit-codes)
- [Intent routing and adaptive tiers](#intent-routing-and-adaptive-tiers)
- [Init targets and AgentSkills / IDE integration](#init-targets-and-agentskills--ide-integration)
- [Configuration reference](#configuration-reference)
- [Python API](#python-api)
- [CI and pre-prompt hook workflows](#ci-and-pre-prompt-hook-workflows)
- [Benchmarks (measured)](#benchmarks-measured)
- [Development and verification](#development-and-verification)
- [Project structure](#project-structure)
- [Limitations and design notes](#limitations-and-design-notes)
- [License](#license)

---

## Concept: information density over noise

LLM interactions carry two components:

- **Semantic/technical signal ($H_s$):** logic, constraints, identifiers, paths, flags, error literals, APIs, state — information required for correct execution.
- **Syntactic/conversational overhead ($O_c$):** pleasantries, filler, repetition, verbose phrasing, and irrelevant log frames.

`nanotok` increases the **information density ratio** by removing or compacting $O_c$ and by choosing compact representations (diffs, telegraphic prose, symbolic operators, dense specs/snapshots) **without mutating protected technical signal**.

Core idea: **compress representation and overhead, not meaning**.

---

## Architecture: 6-layer pipeline

```text
[USER PROMPT / LOG / SPEC]
        │
        ▼
L0  Pre-Flight Sanitizer        → strip ANSI/internal frames, collapse duplicates
        ▼
L1  Diff-First Patching         → <50% edits as patch/anchor; >=50% or new file as full
        ▼
L2  Telegraphic Compression     → protect spans, remove filler/stopwords, apply operators (L1/L2/L3)
        ▼
L3  Intent-Routed Contract      → classify intent and lock output shape (debug/code/compare/…)
        ▼
L4  Adaptive Tier Selection     → L1/L2/L3 + auto-escalation with structured triggers
        ▼
L5  Session & Agent Compactor   → pack spec, checkpoint snapshot, minified agent-bus JSON
```

| Layer | Module | Purpose | Primary surfaces |
|---|---|---|---|
| **L0** Pre-Flight Sanitizer | `nanotok/sanitize.py` | Remove ANSI escapes; filter internal stack frames (`node_modules/`, `site-packages/`, runtime/build internals) while preserving project frames (`/src/`, `/app/`, `/lib/`, `/pages/`, …); collapse consecutive duplicates and blank runs; preserve fenced code semantics | `sanitize` |
| **L1** Diff-First Patching | `nanotok/patching.py` | Enforce diff-first policy: `<50%` change → patch (`anchor`/`unified`/`search-replace`), `>=50%` or new file → full content (zero echo). Opcode-based change ratio | `diff` |
| **L2** Telegraphic Compression | `nanotok/telegraph.py` | Protect technical spans (sentinelize), then compress prose: L1 (terse), L2 (+ stopword removal & symbolic operators), L3 (raw/machine-leaning) with safe fallback; fenced/inline code, identifiers, paths, URLs, flags, literals preserved | `compress` |
| **L3** Intent Routing | `nanotok/intent.py` | Deterministic intent classification (`DEBUG`, `CODE_GEN`, `CLI`, `COMPARE`, `EXPLAIN`, `GENERAL`) and output contract selection (e.g. debug → 2-line `Cause/Fix`) | `route`, `tier` |
| **L4** Adaptive Tiers | `nanotok/tiers.py` | Effective tier resolution (L1/L2/L3), monotonic auto-escalation (clamped at L3) on token/attachment thresholds, structured triggers | `route`, `tier`, compression defaults |
| **L5** Session & Agent Bus | `nanotok/session.py` | Dense spec packing, budgeted session checkpoint (`Stack/Done/WIP/Blocker/Next`), minified validated inter-agent task JSON | `pack`, `checkpoint`, `bus` |

**Symbolic operators (telegraphic mode):** `->` (causes), `<-` (from), `=>` (returns), `+` (and), `!=` (conflict/not), `w/` (with), `w/o` (without), `bc` (because), `@` (location), `~` (approx).

---

## Key guarantees and invariants

- **Protected technical signal:** fenced/inline code, identifiers, paths, URLs, CLI flags, and error/string literals are not rewritten by prose compression.
- **Diff-first / zero-echo policy (L1):** small edits are emitted as patches; full-file emission is reserved for large rewrites/new files (no “here is what changed” prose from the patch generator).
- **Safe compression fallback:** aggressive tiers must not return empty/meaningless output for meaningful input.
- **No LLM dependency:** compression, routing, tiering, packing, and patch generation are deterministic and local.
- **Patch generation ≠ patch application:** `nanotok diff` produces a patch artifact; it does not modify target files.
- **Fail-loud configuration:** unknown keys or invalid types raise `ConfigError` (no silent fallback that hides broken knobs).
- **Stable CLI contract:** machine payload on `stdout`, diagnostics/stats on `stderr`, exit codes `0` (ok), `2` (input/protocol), `3` (config/I/O).

> When following nanotok protocol in agents, destructive/breaking operations should be prefixed with `[!WARN]` and lazy placeholders (`// TODO: implement`) avoided for new code.

---

## Requirements and installation

- **Python:** ≥ 3.10 (tested with 3.14 in this environment)
- **Runtime dependencies:** none (stdlib only)
- **Dev/verification tools:** `pytest`, `mypy`, `ruff`, `build`, `twine`

Once installed, usage is simply **`nanotok`** — no wrapper script, no config file required (defaults are validated and auto-applied).

### Easiest: one-liner installer (installs `nanotok` onto your PATH)

```bash
curl -fsSL https://raw.githubusercontent.com/FerzDevZ/nanotok/main/scripts/install.sh | bash
nanotok --version
```

The installer uses **pipx** when available; otherwise it creates an isolated venv at `~/.local/share/nanotok/venv` and exposes a launcher at `~/.local/bin/nanotok`. It never touches the system Python (safe on PEP 668 “externally managed” distros) and can be re-run safely:

```bash
bash scripts/install.sh            # install (or reuse existing install)
bash scripts/install.sh --upgrade  # force reinstall/upgrade from git
```

If `nanotok` is not found immediately afterwards, open a new terminal (or `export PATH="$HOME/.local/bin:$PATH"`) and re-check `nanotok --version`.

### Recommended: `pipx` from Git (isolated, global command)

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath          # then open a new terminal
pipx install git+https://github.com/FerzDevZ/nanotok.git

nanotok --version
# nanotok 3.0.0
```

This is the most reliable way to get a plain `nanotok` command on every terminal without polluting a project venv.

### From PyPI (once released)

```bash
pipx install nanotok
# or: pip install nanotok
```

Releases are published automatically by the workflow in [`.github/workflows/publish.yml`](.github/workflows/publish.yml) on `v*` tags via PyPI Trusted Publishing.

### Editable install for development (this repo)

```bash
cd /home/firman/nanotok
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

nanotok --version
# nanotok 3.0.0
```

### Run without installing the console script

```bash
python3 -m nanotok --help
# from a source checkout without install:
PYTHONPATH=. python3 -m nanotok --help
```

---

## Quick start

```bash
# 1) Deploy rules/config/AgentSkills skill into a project
nanotok init --target all --dir .

# 2) Sanitize a noisy build log before pasting to an agent
npm run build 2>&1 | nanotok sanitize -

# 3) Compress or pack verbose specs
nanotok compress prd.md --tier L2
nanotok pack prd.md > prd.dense.md

# 4) Generate a minimal patch (diff-first)
nanotok diff old.ts new.ts --path src/auth.ts --format auto

# 5) Route intent/tier with detailed escalation reasons (JSON)
nanotok route "Fix TypeError @ src/app.ts:10" --json
nanotok tier "Refactor auth middleware" --attachments 5

# 6) Session checkpoint and inter-agent bus
nanotok checkpoint --stack "Next.js 15 + Prisma" --wip "webhook @ api/stripe.ts" --next "add tests"
nanotok bus --type fix_bug --file src/auth.ts --line 88 --error "TokenExpiredError" --request "Add refresh rotation"
```

---

## CLI reference

Global options:

```text
nanotok [--config PATH_TO_nanotok.config.json] <command> ...
nanotok --version
```

### `sanitize` — Layer 0 (log/trace cleanup)

```bash
nanotok sanitize [FILE|-]
```
- Strips ANSI, collapses internal frames/duplicates, preserves project frames and fenced code.
- Stats printed to `stderr` (tokens, frames removed, duplicates collapsed, ANSI removed).

### `compress` — Layer 2 (telegraphic prose compression)

```bash
nanotok compress [FILE|-] [--tier L1|L2|L3]
```
- Compresses prose segments; **fenced code blocks are preserved**.
- Tier defaults to config `default_tier` (L1) if omitted.

### `estimate` — token estimate

```bash
nanotok estimate [FILE|-]
```
- Prints deterministic heuristic token estimate to `stdout`.

### `pack` — Layer 5 (dense spec/PRD)

```bash
nanotok pack [FILE|-] [--tier L1|L2|L3]
```
- Emits structured dense brief (`GOAL/STACK/CONSTRAINTS/ACCEPTANCE/OUT-OF-SCOPE` as available).
- Default tier for packing is L2 when not specified.

### `checkpoint` — Layer 5 (session snapshot)

```bash
nanotok checkpoint --state state.json
nanotok checkpoint --stack STACK [--done "a,b"] [--wip WIP] [--blocker BLOCKER] [--next NEXT]
```
- Emits `[NANOTOK SNAPSHOT]` block, budgeted to configured max tokens (default 90).

### `diff` — Layer 1 (minimal patch)

```bash
nanotok diff OLD NEW --path TARGET_PATH [--format auto|full|anchor|unified|search] [--context N]
```
- `OLD` may be `-` (stdin); `NEW` is a file path; `--path` sets the display path in patch headers.
- `--format auto` (default) applies policy: `>=50%`/new file → full, small edits → anchor/unified based on size.

### `route` — Layer 3+4 (intent + tier + rich contract, JSON)

```bash
nanotok route "PROMPT" [--json] [--attachments N] [--tier L1|L2|L3]
```
- Returns JSON: `intent`, `tier`, `escalated`, `escalation_reason`, `token_estimate`, `attachment_count`, `contract`, and nested `tier_decision` (thresholds, triggers).

### `tier` — Layer 3+4 (detailed escalation resolution, JSON)

```bash
nanotok tier [PROMPT] [--file FILE|-] [--attachments N] [--tier L1|L2|L3]
```
- Same routing engine with explicit `mode: "tier"` payload focused on tier/intent/escalation details.

### `bus` — Layer 5 (inter-agent task envelope)

```bash
# compile
nanotok bus --type fix_bug --file src/auth.ts --line 88 --error "TokenExpiredError" --request "..."

# decode
nanotok bus --decode '{"t":"fix_bug","f":"src/auth.ts","ln":88}'
```
- Minified wire keys: `t` (action), `f` (file), `ln` (line), `err` (error), `req` (request), `c` (context).
- Unknown actions/keys/invalid fields are rejected.

### `bench` — token savings comparison

```bash
nanotok bench BASELINE_FILE NANOTOK_FILE
```
- Prints baseline/nanotok token counts, tokens saved, percent, and density gain.

### `init` — deploy rules/config/skills

```bash
nanotok init [--target claude|cursor|windsurf|skill|agent-skill|config|all] [--dir DIR] [--force]
```
- See [Init targets and AgentSkills / IDE integration](#init-targets-and-agentskills--ide-integration).

### `config` — inspect or validate

```bash
nanotok config show
nanotok config validate
nanotok --config ./nanotok.config.json config validate
```

---

## I/O contract and exit codes

| Stream / code | Meaning |
|---|---|
| `stdout` | Primary machine payload (sanitized/compressed/packed text, patch, JSON, bench report) |
| `stderr` | Diagnostics and per-command stats (e.g. `[nanotok sanitize] ...`, `[nanotok pack ...]`) |
| Exit `0` | Success |
| Exit `2` | Invalid input / argument / protocol violation (`InputError`, template target errors) |
| Exit `3` | Configuration or I/O failure (`ConfigError`, OS/file errors) |

This separation keeps pipelines safe (e.g. `... | nanotok sanitize - | pbcopy`).

---

## Intent routing and adaptive tiers

### Intents and output contracts

| Intent | Typical trigger | Contract (summary) |
|---|---|---|
| `DEBUG` | tracebacks, error/exception/failure signals | Exactly 2 lines: `Cause: ...` and `Fix: ...` |
| `CODE_GEN` | refactor/implement/add/fix/create/update… | Code/patch/command only; diff-first for `<50%` edits |
| `CLI` | shell command-like prompts | Single command/one-liner, no prose |
| `COMPARE` | compare/vs/trade-off | Compact decision matrix + `Pick: ... bc ...` |
| `EXPLAIN` | explain/why/how/what (when not dominated by debug) | ≤ 3 short bullets, no paragraphs |
| `GENERAL` | fallback | Terse technical response |

Tier suffix in contract: **L1** terse technical, **L2** telegraphic (keywords/operators), **L3** raw machine (code/JSON/CLI only, comments ≤ 4 words).

### Auto-escalation (Layer 4)

- Base tier: requested tier or config `default_tier`.
- Escalate **+1 step** when `token_count > auto_escalate_threshold_tokens` (default 16000).
- Escalate **+1 step** when `attachment_count > auto_escalate_attachment_count` (default 3).
- **Monotonic, clamped at L3**. Each trigger is recorded with measured value, threshold, and transition.

### Example: rich tier decision (measured)

```json
{
  "mode": "tier",
  "intent": "DEBUG",
  "tier": "L2",
  "escalated": true,
  "escalation_reason": "auto-escalation: attachments 5 > 3",
  "token_estimate": 24,
  "attachment_count": 5,
  "tier_decision": {
    "requested": "L1",
    "base": "L1",
    "effective": "L2",
    "escalated": true,
    "reason": "auto-escalation: attachments 5 > 3",
    "token_count": 24,
    "attachment_count": 5,
    "thresholds": { "auto_escalate_tokens": 16000, "auto_escalate_attachments": 3 },
    "triggers": [
      { "name": "attachment_count", "value": 5, "threshold": 3, "from_tier": "L1", "to_tier": "L2" }
    ]
  },
  "contract": "Output exactly 2 lines: `Cause: <<=12 words>` and `Fix: <action/patch>`. [L2] telegraphic: keywords + operators + code."
}
```

---

## Init targets and AgentSkills / IDE integration

`nanotok init` deploys embedded templates/config into a target directory (no package-data dependency).

| Target | Writes | Use case |
|---|---|---|
| `claude` | `CLAUDE.md` | Claude Code project instructions |
| `cursor` | `.cursorrules` | Cursor rules |
| `windsurf` | `.windsurfrules` | Windsurf rules |
| `skill` | `SKILL.md` | Flat skill/instruction file |
| `agent-skill` | `.agents/skills/nanotok/SKILL.md` | **Local AgentSkills-compatible skill** (YAML frontmatter) |
| `config` | `nanotok.config.json` | Project config |
| `all` | All of the above | Full project bootstrap |

Examples:

```bash
nanotok init --target all --dir .
nanotok init --target agent-skill --dir .
nanotok init --target config --dir . --force
```

The repository includes the local skill at `.agents/skills/nanotok/SKILL.md` so AgentSkills-aware tooling in this workspace can load it directly.

---

## Configuration reference

Default effective configuration (`nanotok config show`):

```json
{
  "skill": "nanotok",
  "version": "3.0.0",
  "default_tier": "L1",
  "auto_escalate_threshold_tokens": 16000,
  "auto_escalate_attachment_count": 3,
  "diff_threshold_ratio": 0.5,
  "max_debug_prose_lines": 2,
  "max_checkpoint_tokens": 90,
  "pack_target_ratio": 0.3,
  "operators": {
    "causes": "->",
    "from": "<-",
    "returns": "=>",
    "and": "+",
    "conflict": "!=",
    "with": "w/",
    "without": "w/o",
    "because": "bc",
    "location": "@",
    "approx": "~"
  },
  "invariants": {
    "preserve_code_identifiers": true,
    "preserve_cli_flags": true,
    "preserve_error_literals": true,
    "warn_prefix_on_destructive": "[!WARN]",
    "forbid_lazy_placeholders": true
  },
  "sanitizer": {
    "keep_path_markers": ["/src/", "/app/", "/lib/", "/pages/", "file://"],
    "max_repeat_marker": true
  }
}
```

**Behavior:**
- Config file name: `nanotok.config.json` (auto-discovered upward from cwd, or `--config PATH`).
- Unknown keys or invalid value types/ranges are rejected with `ConfigError`.
- Empty/missing config falls back to validated defaults.

---

## Python API

```python
from nanotok import (
    # config
    DEFAULT_CONFIG, NanotokConfig, discover_config, load_config,
    # models
    AgentTask, CompressionTier, Intent, PatchFormat, SessionState,
    # layers / utilities
    sanitize_log, compress_document, compress_prose, build_patch,
    classify_intent, output_contract, route_prompt, select_tier,
    pack_spec, build_checkpoint, compile_agent_task, parse_agent_task,
    compare_tokens, estimate_tokens,
)

clean = sanitize_log(raw_traceback).text
dense = compress_document(verbose_markdown, tier=CompressionTier.L2).text
packed = pack_spec(prd_text, tier=CompressionTier.L2).text
patch = build_patch(old_src, new_src, "src/file.ts").content
routing = route_prompt("Fix TypeError @ app.ts:10", attachment_count=5).to_mapping()
task = compile_agent_task(AgentTask(action="fix_bug", file="src/auth.ts", line=88))
```

Public package version: `nanotok.__version__ == "3.0.0"`.

---

## CI and pre-prompt hook workflows

### GitHub Actions: validate config and smoke-benchmark corpus

```yaml
# .github/workflows/nanotok.yml
name: nanotok
on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -e .
      - name: Validate config
        run: nanotok config validate
      - name: Sanitize benchmark log and measure
        run: |
          nanotok sanitize fixtures/benchmark/noisy-build.log > /tmp/sanitized.log
          nanotok bench fixtures/benchmark/noisy-build.log /tmp/sanitized.log
      - name: Pack benchmark PRD and measure
        run: |
          nanotok pack fixtures/benchmark/verbose-prd.md > /tmp/prd.pack.md
          nanotok bench fixtures/benchmark/verbose-prd.md /tmp/prd.pack.md
```

### Pre-prompt hook: sanitize noisy command output

```bash
#!/usr/bin/env bash
# hooks/pre-prompt-sanitize.sh
# Usage: npm run build 2>&1 | hooks/pre-prompt-sanitize.sh
set -euo pipefail
python -m nanotok sanitize -
```

### Pre-prompt hook: pack verbose spec to dense brief

```bash
#!/usr/bin/env bash
# hooks/pre-prompt-pack.sh
# Usage: hooks/pre-prompt-pack.sh prd.md
set -euo pipefail
python -m nanotok pack "${1:--}" --tier L2
```

### Session handoff helper (checkpoint)

```bash
nanotok checkpoint \
  --stack "$(jq -r '.name // "app"' package.json 2>/dev/null || echo app)" \
  --wip "$(git branch --show-current 2>/dev/null || echo wip)" \
  --next "continue from current blocker"
```

---

## Benchmarks (measured)

Benchmarks were run with `nanotok bench` on the representative corpus in `fixtures/benchmark/`:

- `fixtures/benchmark/noisy-build.log` — build output with ANSI, duplicate warnings, mixed project and `node_modules`/runtime frames
- `fixtures/benchmark/verbose-prd.md` — verbose multi-section PRD/spec
- Derived outputs: `noisy-build.sanitized.log`, `verbose-prd.l2.md`, `verbose-prd.pack.md`

| Case | Baseline | nanotok | Saved | Density gain |
|---|---:|---:|---:|---:|
| `sanitize` noisy build log (ANSI/internal frames/duplicates) | 829 tokens | 554 tokens | **33.17%** (275) | 1.50x |
| `compress --tier L2` verbose PRD prose | 956 tokens | 805 tokens | **15.79%** (151) | 1.19x |
| `pack` verbose PRD → dense spec brief | 956 tokens | 458 tokens | **52.09%** (498) | 2.09x |

**Interpretation:**
- **Higher savings** occur on noisy/redundant inputs (dependency-heavy traces, repeated logs, verbose specs).
- **Lower savings** are expected on already-dense technical prose to avoid meaning loss (protected spans, conservative compression).
- Token counts use nanotok’s **deterministic heuristic estimator** (no external tokenizer dependency, ~±15% vs BPE meters) for planning/comparison, **not billing**.

Reproduce:

```bash
nanotok sanitize fixtures/benchmark/noisy-build.log > /tmp/s.log
nanotok bench fixtures/benchmark/noisy-build.log /tmp/s.log

nanotok compress fixtures/benchmark/verbose-prd.md --tier L2 > /tmp/p.l2.md
nanotok bench fixtures/benchmark/verbose-prd.md /tmp/p.l2.md

nanotok pack fixtures/benchmark/verbose-prd.md > /tmp/p.pack.md
nanotok bench fixtures/benchmark/verbose-prd.md /tmp/p.pack.md
```

---

## Development and verification

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Quality gates (executed in this repo)

```bash
ruff check nanotok tests
mypy --strict nanotok
pytest -q
python -m nanotok --help
```

**Current status:** `ruff` passes, `mypy --strict` passes (15 source files), `pytest` passes (66 tests).

### Build and validate a release locally

```bash
python -m build                 # writes dist/nanotok-3.0.0.tar.gz + .whl
twine check dist/*
```

### Release process (maintainers)

1. Bump `version` in `pyproject.toml` and add release notes.
2. Commit, then tag and push the tag:
   ```bash
   git tag v3.0.0
   git push origin v3.0.0
   ```
3. The `Publish to PyPI` workflow builds sdist/wheel and publishes via **PyPI Trusted Publishing** (OIDC, no API token stored in the repo). Configure the `pypi` environment and trusted publisher once in the PyPI project settings.

---

## Project structure

```text
.
├── nanotok/                        # Core engine package
│   ├── __init__.py                 # Public API and __version__
│   ├── __main__.py                 # python -m nanotok
│   ├── cli.py                      # argparse CLI, handlers, exit-code contract
│   ├── config.py                   # Config schema, validation, discovery
│   ├── errors.py                   # NanotokError/ConfigError/InputError/TemplateError
│   ├── intent.py                   # L3 intent classification + routing contracts
│   ├── models.py                   # Core types (tiers, intents, reports, decisions)
│   ├── patching.py                 # L1 diff-first patch generation
│   ├── sanitize.py                 # L0 log/trace sanitization
│   ├── session.py                  # L5 pack, checkpoint, agent-bus
│   ├── telegraph.py                # L2 telegraphic compression + span protection
│   ├── templates.py                # Embedded deployable rule/config/skill templates
│   ├── textspans.py                # Fenced-block splitting and span protection
│   ├── tiers.py                    # L4 tier selection and escalation triggers
│   └── tokens.py                   # Deterministic token estimator and reports
├── .agents/skills/nanotok/SKILL.md # Local AgentSkills integration (nanotok protocol)
├── .github/workflows/publish.yml   # Build + publish to PyPI on v* tags (Trusted Publishing)
├── scripts/install.sh              # One-liner installer (pipx, PATH setup, --upgrade)
├── fixtures/benchmark/             # Representative benchmark corpus and sample outputs
├── tests/                          # Pytest suite (layers, config/templates, CLI e2e)
├── PLAN.md                         # Detailed build plan and module contracts
├── rancangan.md                    # Source design specification (v3.0)
├── README.md                       # This document
├── LICENSE                         # MIT license text
├── MEMORY.md                       # Project invariants / learned notes
└── pyproject.toml                  # Packaging, tool config (ruff/mypy/pytest)
```

---

## Limitations and design notes

- **Heuristic tokenization:** no BPE tokenizer dependency by design; estimates are approximate and intended for relative comparison.
- **Compression is lossy by intent for prose/coordination:** clarity-reducing overhead may be removed; protected technical spans and code are preserved.
- **No automatic patch application:** review/apply generated patches with your normal workflow.
- **No LLM calls / no semantic rewriting:** nanotok structures and compresses; it does not “understand” or invent missing requirements.
- **Benchmark variability:** results depend strongly on input characteristics (noise, duplication, verbosity, code density).

---

## License

MIT — see [`LICENSE`](LICENSE).
