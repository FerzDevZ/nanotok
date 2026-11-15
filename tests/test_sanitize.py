from nanotok.sanitize import sanitize_log, strip_ansi


def test_strip_ansi_removes_escape_sequences() -> None:
    cleaned, removed = strip_ansi("\x1b[31mERROR\x1b[0m: boom")
    assert cleaned == "ERROR: boom"
    assert removed == 2


def test_sanitize_removes_internal_frames_and_keeps_project_frames() -> None:
    raw = (
        "TypeError: cannot read properties of undefined\n"
        "    at getUser (src/lib/auth.ts:42:11)\n"
        "    at processTicksAndRejections (node:internal/process/task_queues:95:5)\n"
        "    at Module._compile (node:internal/modules/cjs/loader:1364:14)\n"
        "    at Object.<anonymous> (node_modules/next/dist/server.js:10:1)\n"
        "    at handler (app/api/login/route.ts:19:3)\n"
    )
    result = sanitize_log(raw)
    assert "src/lib/auth.ts:42:11" in result.text
    assert "app/api/login/route.ts:19:3" in result.text
    assert "node_modules/next" not in result.text
    assert "node:internal" not in result.text
    assert "internal library frames stripped" in result.text
    assert result.frames_removed >= 3


def test_sanitize_collapses_duplicate_lines_and_blank_runs() -> None:
    raw = "warn: retrying\nwarn: retrying\nwarn: retrying\n\n\ninfo: done\n"
    result = sanitize_log(raw)
    assert "repeated 2x" in result.text
    assert result.duplicates_collapsed == 2
    assert result.blank_lines_removed >= 1


def test_sanitize_preserves_fenced_code_blocks() -> None:
    raw = (
        "Error before\n"
        "```ts\n"
        "const value = user.profile.name;\n"
        "console.log(value);\n"
        "```\n"
        "after\n"
    )
    result = sanitize_log(raw)
    assert "const value = user.profile.name;" in result.text
    assert "console.log(value);" in result.text


def test_sanitize_reports_token_savings() -> None:
    raw = "\n".join(
        [
            "Build failed",
            "    at x (node_modules/a/index.js:1:1)",
            "    at y (node_modules/b/index.js:1:1)",
            "    at z (node_modules/c/index.js:1:1)",
            "    at real (src/app/page.tsx:10:2)",
        ]
    )
    result = sanitize_log(raw)
    assert result.report.original_tokens > 0
    assert result.report.compressed_tokens <= result.report.original_tokens
