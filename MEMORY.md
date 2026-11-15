# MEMORY — nanotok project invariants & post-mortems

## Learned invariants

- **[26-? · Toolchain]**: `pytest`/`mypy` binaries on PATH may be shadowed by user-site installs broken for system Python → **Invariant:** use project-local `.venv/bin/pytest` and `.venv/bin/mypy` for verification; install deps into venv.
- **[26-? · Packaging]**: Editable install warns if `README.md` missing during build and `project.license` table form is deprecated on newer setuptools → **Invariant:** keep `README.md` present and prefer `license = "MIT"` string.
- **[26-? · Telegrapher safety]**: Prose compression must never mutate fenced/inline code, identifiers, paths, URLs, or CLI flags → **Invariant:** protect spans first (sentinels), compress only prose segments, restore after; L3 must fall back instead of returning empty/ambiguous output.
- **[26-? · Patching policy]**: `<50%` edits must not emit full files; `>=50%` or new files must emit full content without echo prose → **Invariant:** centralize format decision in `build_patch` using opcode-based change ratio.
- **[26-? · CLI contract]**: Stats on stdout break pipes → **Invariant:** payload to stdout, diagnostics/stats to stderr, stable exit codes (0/2/3).
- **[26-? · Config]**: Silent fallback hides broken compression knobs → **Invariant:** unknown keys / wrong types raise `ConfigError`; defaults are explicit and serializable.
- **[26-11-15 · Installer]**: `pip install --user pipx` fails on Debian/Ubuntu with PEP 668 `externally-managed-environment` → **Invariant:** installers must never write to system Python; prefer pipx and fall back to an isolated venv (`~/.local/share/nanotok/venv`) with a launcher in `~/.local/bin`.
- **[26-11-15 · Packaging]**: `tool.setuptools.license-files` is deprecated in favor of `project.license-files` on setuptools>=77 → **Invariant:** keep SPDX `license = "MIT"` plus `license-files` under `[project]`, and verify with `twine check dist/*`.
