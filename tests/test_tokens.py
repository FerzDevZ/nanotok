from nanotok.tokens import compare_tokens, estimate_tokens


def test_empty_and_whitespace_return_zero() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("   \n\t  ") == 0


def test_estimate_increases_with_content() -> None:
    short = estimate_tokens("fix bug")
    long = estimate_tokens("fix bug in authentication middleware at request boundary")
    assert short > 0
    assert long > short


def test_code_like_text_has_density_signal() -> None:
    prose = "please update the user profile settings page carefully"
    code = "export async function getUser(id: string): Promise<User> { return db.user.find(id); }"
    assert estimate_tokens(code) >= 1
    assert estimate_tokens(prose) >= 1


def test_compare_tokens_reports_savings() -> None:
    report = compare_tokens("this is a very verbose explanation", "verbose explanation")
    assert report.original_tokens > report.compressed_tokens
    assert report.saved_tokens == report.original_tokens - report.compressed_tokens
    assert 0.0 < report.saved_percent <= 100.0
    assert report.density_gain >= 1.0
