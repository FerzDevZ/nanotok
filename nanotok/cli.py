"""Command-line interface for nanotok v3.0.

Contract:
- exit 0: success
- exit 2: invalid user input / argument / protocol violation
- exit 3: configuration or I/O failure
- payload -> stdout, diagnostics/stats -> stderr (pipe-safe)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from nanotok import __version__
from nanotok.config import CONFIG_FILENAME, NanotokConfig, discover_config, load_config
from nanotok.errors import ConfigError, InputError, NanotokError, TemplateError
from nanotok.intent import route_prompt
from nanotok.models import AgentTask, CompressionTier, PatchFormat, SessionState
from nanotok.patching import build_patch
from nanotok.sanitize import sanitize_log
from nanotok.session import (
    build_checkpoint,
    compile_agent_task,
    pack_spec,
    parse_agent_task,
    session_state_from_mapping,
)
from nanotok.telegraph import compress_document
from nanotok.templates import init_project
from nanotok.tokens import compare_tokens, estimate_tokens

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_CONFIG = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanotok",
        description="nanotok v3.0 — ultra-high-density token compression engine & CLI toolkit",
    )
    parser.add_argument("--version", action="version", version=f"nanotok {__version__}")
    parser.add_argument(
        "--config",
        default=None,
        help=f"Path to {CONFIG_FILENAME} (default: auto-discover upward from cwd)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    sanitize_parser = subparsers.add_parser(
        "sanitize", help="Layer 0: strip ANSI, internal frames, and log noise"
    )
    sanitize_parser.add_argument("file", help="Input file path or '-' for stdin")
    _add_tier_argument(sanitize_parser, required=False)
    sanitize_parser.set_defaults(handler=_handle_sanitize)

    compress_parser = subparsers.add_parser(
        "compress", help="Layer 2: compress prose while protecting fenced code"
    )
    compress_parser.add_argument("file", help="Input file path or '-' for stdin")
    _add_tier_argument(compress_parser, required=False)
    compress_parser.set_defaults(handler=_handle_compress)

    estimate_parser = subparsers.add_parser("estimate", help="Estimate token count for text")
    estimate_parser.add_argument("file", help="Input file path or '-' for stdin")
    estimate_parser.set_defaults(handler=_handle_estimate)

    pack_parser = subparsers.add_parser(
        "pack", help="Layer 5: compress verbose spec/PRD into dense structured brief"
    )
    pack_parser.add_argument("file", help="Input file path or '-' for stdin")
    _add_tier_argument(pack_parser, required=False)
    pack_parser.set_defaults(handler=_handle_pack)

    checkpoint_parser = subparsers.add_parser(
        "checkpoint", help="Layer 5: emit <=90-token session snapshot"
    )
    checkpoint_parser.add_argument("--state", help="Path to JSON state file")
    checkpoint_parser.add_argument("--stack", help="Stack/technology summary")
    checkpoint_parser.add_argument("--done", help="Comma-separated completed items")
    checkpoint_parser.add_argument("--wip", help="Current work-in-progress item")
    checkpoint_parser.add_argument("--blocker", help="Current blocker")
    checkpoint_parser.add_argument("--next", dest="next_step", help="Immediate next action")
    checkpoint_parser.set_defaults(handler=_handle_checkpoint)

    diff_parser = subparsers.add_parser(
        "diff", help="Layer 1: emit minimal patch (anchor/search/unified/full) for an edit"
    )
    diff_parser.add_argument("old", help="Path to old file (or '-' for stdin)")
    diff_parser.add_argument("new", help="Path to new file")
    diff_parser.add_argument(
        "--path", required=True, dest="target_path", help="Display path in patch"
    )
    diff_parser.add_argument(
        "--format",
        choices=[fmt.value for fmt in PatchFormat if fmt is not PatchFormat.NOOP],
        default=PatchFormat.AUTO.value,
        help="Patch format (default: auto)",
    )
    diff_parser.add_argument(
        "--context", type=int, default=3, help="Context lines per hunk (default: 3)"
    )
    diff_parser.set_defaults(handler=_handle_diff)

    route_parser = subparsers.add_parser(
        "route",
        help="Layer 3+4: classify intent, select tier, print rich JSON output contract",
    )
    route_parser.add_argument("prompt", help="Prompt text to route")
    route_parser.add_argument("--attachments", type=int, default=0, help="Attachment/file count")
    route_parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="Output JSON (default; accepted for explicit mode)",
    )
    _add_tier_argument(route_parser, required=False)
    route_parser.set_defaults(handler=_handle_route)

    tier_parser = subparsers.add_parser(
        "tier",
        help="Layer 3+4: resolve intent/tier with detailed escalation reasons (JSON)",
    )
    tier_parser.add_argument("prompt", nargs="?", help="Prompt text (or use --file)")
    tier_parser.add_argument("--file", help="Read prompt from file or '-' for stdin")
    tier_parser.add_argument("--attachments", type=int, default=0, help="Attachment/file count")
    _add_tier_argument(tier_parser, required=False)
    tier_parser.set_defaults(handler=_handle_tier)

    bus_parser = subparsers.add_parser(
        "bus", help="Layer 5: compile or decode inter-agent minified JSON task"
    )
    bus_parser.add_argument("--decode", help="Decode a minified JSON task payload")
    bus_parser.add_argument("--type", dest="action", help="Task action verb (compile mode)")
    bus_parser.add_argument("--file", dest="task_file", help="Target file path")
    bus_parser.add_argument("--line", type=int, dest="task_line", help="Target line number")
    bus_parser.add_argument("--error", dest="task_error", help="Error summary")
    bus_parser.add_argument("--request", dest="task_request", help="Task request")
    bus_parser.add_argument("--context", dest="task_context", help="Extra context")
    bus_parser.set_defaults(handler=_handle_bus)

    bench_parser = subparsers.add_parser(
        "bench", help="Compare baseline vs nanotok output token counts"
    )
    bench_parser.add_argument("baseline", help="Baseline file")
    bench_parser.add_argument("nanotok", help="Nanotok-compressed file")
    bench_parser.set_defaults(handler=_handle_bench)

    init_parser = subparsers.add_parser(
        "init", help="Deploy nanotok rule/config files into a project directory"
    )
    init_parser.add_argument(
        "--target",
        choices=["claude", "cursor", "windsurf", "skill", "agent-skill", "config", "all"],
        default="all",
    )
    init_parser.add_argument("--dir", default=".", help="Target directory (default: cwd)")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    init_parser.set_defaults(handler=_handle_init)

    config_parser = subparsers.add_parser("config", help="Inspect or validate nanotok config")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    show_parser = config_sub.add_parser("show", help="Print effective config as JSON")
    show_parser.set_defaults(handler=_handle_config_show)
    validate_parser = config_sub.add_parser(
        "validate", help="Validate discovered or explicit config"
    )
    validate_parser.set_defaults(handler=_handle_config_validate)

    return parser


def entrypoint(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = _resolve_config(args)
        return int(args.handler(args, config))
    except (InputError, TemplateError) as input_error:
        print(f"nanotok: {input_error}", file=sys.stderr)
        return EXIT_INPUT
    except ConfigError as config_error:
        print(f"nanotok: {config_error}", file=sys.stderr)
        return EXIT_CONFIG
    except OSError as io_error:
        print(f"nanotok: {io_error}", file=sys.stderr)
        return EXIT_CONFIG
    except NanotokError as nanotok_error:
        print(f"nanotok: {nanotok_error}", file=sys.stderr)
        return EXIT_INPUT


def _resolve_config(args: argparse.Namespace) -> NanotokConfig:
    explicit_path = getattr(args, "config", None)
    if explicit_path:
        return load_config(Path(explicit_path))
    discovered = discover_config(Path.cwd())
    return load_config(discovered)


def _add_tier_argument(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument(
        "--tier",
        choices=[tier.value for tier in CompressionTier],
        default=None,
        required=required,
        help="Compression tier (L1/L2/L3). Default: config default_tier.",
    )


def _read_input(file_argument: str) -> str:
    if file_argument == "-":
        return sys.stdin.read()
    return Path(file_argument).read_text(encoding="utf-8")


def _requested_tier(args: argparse.Namespace) -> CompressionTier | None:
    tier_value = getattr(args, "tier", None)
    return CompressionTier.parse(tier_value) if tier_value else None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_sanitize(args: argparse.Namespace, config: NanotokConfig) -> int:
    raw_text = _read_input(args.file)
    result = sanitize_log(raw_text, config=config)
    sys.stdout.write(result.text)
    if not result.text.endswith("\n"):
        sys.stdout.write("\n")
    report = result.report
    print(
        f"[nanotok sanitize] {report.original_tokens}->{report.compressed_tokens} tokens "
        f"saved={report.saved_percent}% ansi={result.ansi_removed} "
        f"frames={result.frames_removed} dup={result.duplicates_collapsed}",
        file=sys.stderr,
    )
    return EXIT_OK


def _handle_compress(args: argparse.Namespace, config: NanotokConfig) -> int:
    raw_text = _read_input(args.file)
    tier = _requested_tier(args) or config.default_tier
    result = compress_document(raw_text, tier=tier, config=config)
    sys.stdout.write(result.text)
    if result.text and not result.text.endswith("\n"):
        sys.stdout.write("\n")
    report = result.report
    print(
        f"[nanotok compress {tier.value}] {report.original_tokens}->{report.compressed_tokens} "
        f"saved={report.saved_percent}% density={report.density_gain}x "
        f"segments={result.compressed_segments}",
        file=sys.stderr,
    )
    return EXIT_OK


def _handle_estimate(args: argparse.Namespace, _config: NanotokConfig) -> int:
    raw_text = _read_input(args.file)
    print(estimate_tokens(raw_text))
    return EXIT_OK


def _handle_pack(args: argparse.Namespace, config: NanotokConfig) -> int:
    raw_text = _read_input(args.file)
    tier = _requested_tier(args) or CompressionTier.L2
    packed = pack_spec(raw_text, tier=tier, config=config)
    sys.stdout.write(packed.text)
    if packed.text and not packed.text.endswith("\n"):
        sys.stdout.write("\n")
    report = packed.report
    print(
        f"[nanotok pack {tier.value}] {report.original_tokens}->{report.compressed_tokens} "
        f"saved={report.saved_percent}% sections={','.join(packed.sections) or '-'}",
        file=sys.stderr,
    )
    return EXIT_OK


def _handle_checkpoint(args: argparse.Namespace, config: NanotokConfig) -> int:
    if args.state:
        state_payload = json.loads(Path(args.state).read_text(encoding="utf-8"))
        if not isinstance(state_payload, dict):
            raise InputError("checkpoint state file must contain a JSON object")
        state = session_state_from_mapping(state_payload)
    else:
        if not args.stack:
            raise InputError("checkpoint requires --state or --stack")
        done_items = tuple(item.strip() for item in (args.done or "").split(",") if item.strip())
        state = SessionState(
            stack=args.stack.strip(),
            done=done_items,
            wip=(args.wip or "").strip(),
            blocker=(args.blocker or "").strip(),
            next_step=(args.next_step or "").strip(),
        )

    checkpoint = build_checkpoint(state, config=config)
    sys.stdout.write(checkpoint.text)
    sys.stdout.write("\n")
    print(
        f"[nanotok checkpoint] tokens={checkpoint.token_estimate} truncated={checkpoint.truncated}",
        file=sys.stderr,
    )
    return EXIT_OK


def _handle_diff(args: argparse.Namespace, config: NanotokConfig) -> int:
    old_text = _read_input(args.old)
    new_text = Path(args.new).read_text(encoding="utf-8")
    patch_format = PatchFormat(args.format)
    result = build_patch(
        old_text,
        new_text,
        args.target_path,
        config=config,
        patch_format=patch_format,
        context_lines=args.context,
    )
    if result.content:
        sys.stdout.write(result.content)
        if not result.content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        sys.stdout.write("# no changes\n")
    print(
        f"[nanotok diff] format={result.format.value} ratio={result.change_ratio} "
        f"changed={result.changed_lines} hunks={result.hunk_count} "
        f"saved={result.report.saved_percent}%",
        file=sys.stderr,
    )
    return EXIT_OK


def _handle_route(args: argparse.Namespace, config: NanotokConfig) -> int:
    routed = route_prompt(
        args.prompt,
        tier_request=_requested_tier(args),
        attachment_count=max(0, args.attachments),
        config=config,
    )
    payload = routed.to_mapping()
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
    sys.stdout.write("\n")
    return EXIT_OK


def _handle_tier(args: argparse.Namespace, config: NanotokConfig) -> int:
    if args.file:
        prompt = _read_input(args.file)
    elif args.prompt is not None:
        prompt = args.prompt
    else:
        raise InputError("tier requires PROMPT or --file")
    routed = route_prompt(
        prompt,
        tier_request=_requested_tier(args),
        attachment_count=max(0, args.attachments),
        config=config,
    )
    payload = {
        "mode": "tier",
        "intent": routed.intent.value,
        "tier": routed.tier.value,
        "escalated": routed.escalated,
        "escalation_reason": routed.escalation_reason,
        "token_estimate": routed.token_estimate,
        "attachment_count": routed.attachment_count,
        "tier_decision": routed.tier_decision,
        "contract": routed.contract,
    }
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
    sys.stdout.write("\n")
    return EXIT_OK


def _handle_bus(args: argparse.Namespace, _config: NanotokConfig) -> int:
    if args.decode:
        task = parse_agent_task(args.decode)
        sys.stdout.write(
            json.dumps(
                {
                    "action": task.action,
                    "file": task.file,
                    "line": task.line,
                    "error": task.error,
                    "request": task.request,
                    "context": task.context,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        sys.stdout.write("\n")
        return EXIT_OK

    if not args.action:
        raise InputError("bus compile mode requires --type <action>")
    task = AgentTask(
        action=args.action,
        file=args.task_file,
        line=args.task_line,
        error=args.task_error,
        request=args.task_request,
        context=args.task_context,
    )
    sys.stdout.write(compile_agent_task(task))
    sys.stdout.write("\n")
    return EXIT_OK


def _handle_bench(args: argparse.Namespace, _config: NanotokConfig) -> int:
    baseline_text = Path(args.baseline).read_text(encoding="utf-8")
    nanotok_text = Path(args.nanotok).read_text(encoding="utf-8")
    report = compare_tokens(baseline_text, nanotok_text)
    lines = [
        "=== nanotok v3.0 Efficiency Benchmark ===",
        f"Baseline Output : {report.original_tokens:,} tokens",
        f"nanotok Output  : {report.compressed_tokens:,} tokens",
        f"Tokens Saved    : {report.saved_tokens:,} tokens ({report.saved_percent:.2f}%)",
        f"Density Gain    : {report.density_gain:.2f}x",
    ]
    sys.stdout.write("\n".join(lines))
    sys.stdout.write("\n")
    return EXIT_OK


def _handle_init(args: argparse.Namespace, _config: NanotokConfig) -> int:
    written_files = init_project(Path(args.dir), target=args.target, force=args.force)
    for written_file in written_files:
        print(f"[OK] {written_file}")
    return EXIT_OK


def _handle_config_show(_args: argparse.Namespace, config: NanotokConfig) -> int:
    sys.stdout.write(json.dumps(config.to_mapping(), indent=2, ensure_ascii=False))
    sys.stdout.write("\n")
    return EXIT_OK


def _handle_config_validate(args: argparse.Namespace, _config: NanotokConfig) -> int:
    # Re-resolve explicitly so validate reports the same path logic as runtime.
    explicit_path = getattr(args, "config", None)
    config_path = Path(explicit_path) if explicit_path else discover_config(Path.cwd())
    if config_path is None:
        print(f"[OK] no {CONFIG_FILENAME} found; defaults are valid")
        return EXIT_OK
    load_config(config_path)
    print(f"[OK] valid config: {config_path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(entrypoint())
