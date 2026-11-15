from nanotok.models import PatchFormat
from nanotok.patching import build_patch, comment_prefix_for


def test_new_file_emits_full_file() -> None:
    result = build_patch("", "export const value = 1;\n", "src/value.ts")
    assert result.format is PatchFormat.FULL_FILE
    assert "export const value = 1;" in result.content
    assert "existing code" not in result.content


def test_small_edit_emits_patch_not_full_file() -> None:
    old = "\n".join(
        [
            "import { db } from './db';",
            "",
            "export async function getUser(id: string) {",
            "  const user = await db.user.find(id);",
            "  if (!user) throw new Error('missing');",
            "  return user;",
            "}",
            "",
            "export function formatUser(user: { name: string }) {",
            "  return user.name.trim();",
            "}",
            "",
            "export function isActive(flag: boolean) {",
            "  return flag;",
            "}",
            "",
            "export const pageSize = 20;",
            "export const timeoutMs = 5000;",
            "export const retries = 3;",
            "export const region = 'ap-southeast';",
            "export const mode = 'strict';",
            "export const featureX = true;",
            "export const featureY = false;",
            "export const featureZ = true;",
            "export const version = '1';",
            "export const build = 'dev';",
            "export const owner = 'core';",
            "export const env = 'test';",
            "export const channel = 'web';",
            "export const locale = 'id';",
            "export const tier = 'L1';",
            "export const enabled = true;",
            "export const stable = true;",
            "export const experimental = false;",
            "export const debug = false;",
            "export const sample = 1;",
            "export const maxItems = 10;",
            "export const minItems = 1;",
            "export const step = 1;",
            "export const factor = 2;",
            "export const base = 0;",
            "export const offset = 1;",
            "export const limit = 100;",
        ]
    )
    new = old.replace("throw new Error('missing')", "return null")
    result = build_patch(old, new, "src/user.ts")
    assert result.format in {PatchFormat.ANCHOR, PatchFormat.UNIFIED_DIFF}
    assert result.format is not PatchFormat.FULL_FILE
    assert "return null" in result.content
    assert result.change_ratio < 0.5


def test_large_rewrite_emits_full_file() -> None:
    old = "\n".join(f"const a{i} = {i};" for i in range(20))
    new = "\n".join(f"const b{i} = {i * 2};" for i in range(20))
    result = build_patch(old, new, "src/rewrite.ts")
    assert result.format is PatchFormat.FULL_FILE


def test_search_replace_format_contains_markers() -> None:
    old = "line1\nline2\nline3\n" * 30
    new = old.replace("line2", "changed", 1)
    result = build_patch(old, new, "src/file.ts", patch_format=PatchFormat.SEARCH_REPLACE)
    assert result.format is PatchFormat.SEARCH_REPLACE
    assert "FILE: src/file.ts" in result.content
    assert "<<<<<<< SEARCH" in result.content
    assert ">>>>>>> REPLACE" in result.content


def test_comment_prefix_selection() -> None:
    assert comment_prefix_for("script.py") == "#"
    assert comment_prefix_for("query.sql") == "--"
    assert comment_prefix_for("app.tsx") == "//"


def test_identical_files_return_noop() -> None:
    content = "export const x = 1;\n"
    result = build_patch(content, content, "src/x.ts")
    assert result.format is PatchFormat.NOOP
    assert result.changed_lines == 0
    assert result.content == ""
