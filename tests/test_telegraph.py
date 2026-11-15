from nanotok.models import CompressionTier
from nanotok.telegraph import compress_document, compress_prose


def test_fenced_code_is_never_modified() -> None:
    source = (
        "Please update the handler carefully.\n\n"
        "```ts\n"
        "export function getUser(userId: string) {\n"
        "  return db.users.findUnique({ where: { id: userId } });\n"
        "}\n"
        "```\n"
    )
    result = compress_document(source, tier=CompressionTier.L3)
    assert "export function getUser(userId: string)" in result.text
    assert "db.users.findUnique({ where: { id: userId } })" in result.text


def test_inline_code_identifiers_and_urls_are_preserved() -> None:
    source = (
        "Please make sure to update `user.profile.name` at src/lib/auth.ts "
        "because the request with --force flag fails on https://example.com/api/v1/users"
    )
    compressed = compress_prose(source, tier=CompressionTier.L2)
    assert "`user.profile.name`" in compressed
    assert "src/lib/auth.ts" in compressed
    assert "--force" in compressed
    assert "https://example.com/api/v1/users" in compressed


def test_l2_applies_symbolic_operators() -> None:
    source = "This fails because the token is missing with the request from auth service"
    compressed = compress_prose(source, tier=CompressionTier.L2)
    assert "bc" in compressed
    assert "w/" in compressed


def test_l1_reduces_fluff() -> None:
    source = (
        "Please note that you should make sure to restart the server "
        "in order to apply changes."
    )
    compressed = compress_prose(source, tier=CompressionTier.L1)
    assert len(compressed) < len(source)
    assert "please note that" not in compressed.lower()


def test_l3_never_returns_empty_for_meaningful_input() -> None:
    source = "Timeout error at src/api/client.ts line 42 because upstream is slow"
    compressed = compress_prose(source, tier=CompressionTier.L3)
    assert compressed.strip()


def test_compression_is_safe_to_repeat() -> None:
    source = "Please update the config with retries because network fails"
    once = compress_prose(source, tier=CompressionTier.L2)
    twice = compress_prose(once, tier=CompressionTier.L2)
    assert twice == once
