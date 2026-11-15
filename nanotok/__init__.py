"""nanotok v3.0 — ultra-high-density token compression engine.

Public API surface for embedding in tools and scripts. The CLI lives in
:mod:`nanotok.cli`.
"""

from nanotok.config import DEFAULT_CONFIG, NanotokConfig, discover_config, load_config
from nanotok.errors import ConfigError, InputError, NanotokError, TemplateError
from nanotok.intent import classify_intent, output_contract, route_prompt
from nanotok.models import AgentTask, CompressionTier, Intent, PatchFormat, SessionState
from nanotok.patching import build_patch
from nanotok.sanitize import sanitize_log
from nanotok.session import build_checkpoint, compile_agent_task, pack_spec, parse_agent_task
from nanotok.telegraph import compress_document, compress_prose
from nanotok.tiers import select_tier
from nanotok.tokens import compare_tokens, estimate_tokens

__version__ = "3.0.0"

__all__ = [
    "DEFAULT_CONFIG",
    "AgentTask",
    "CompressionTier",
    "ConfigError",
    "InputError",
    "Intent",
    "NanotokConfig",
    "NanotokError",
    "PatchFormat",
    "SessionState",
    "TemplateError",
    "__version__",
    "build_checkpoint",
    "build_patch",
    "classify_intent",
    "compare_tokens",
    "compile_agent_task",
    "compress_document",
    "compress_prose",
    "discover_config",
    "estimate_tokens",
    "load_config",
    "output_contract",
    "pack_spec",
    "parse_agent_task",
    "route_prompt",
    "sanitize_log",
    "select_tier",
]
