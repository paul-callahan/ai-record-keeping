import logging

import pytest

from claude_daily_summary.summarizer import resolve_oauth_token, token_footer


def test_token_footer_folds_cache_reads_into_input():
    footer = token_footer({
        "input_tokens": 24_900,
        "output_tokens": 2_531,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1_200,
    })
    assert "28,631 tokens" in footer
    assert "26,100 input + 2,531 output" in footer


def test_token_footer_handles_missing_usage():
    assert "0 tokens (0 input + 0 output)" in token_footer(None)


def test_env_var_overrides_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("from-file")
    token_file.chmod(0o600)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "from-env")
    assert resolve_oauth_token(token_file) == "from-env"


def test_token_read_from_600_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    token_file = tmp_path / "token"
    token_file.write_text("from-file\n")
    token_file.chmod(0o600)
    assert resolve_oauth_token(token_file) == "from-file"


def test_missing_and_empty_token_file_return_none(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    assert resolve_oauth_token(tmp_path / "absent") is None
    empty = tmp_path / "token"
    empty.write_text("  \n")
    empty.chmod(0o600)
    assert resolve_oauth_token(empty) is None


def test_loose_token_file_permissions_abort(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    token_file = tmp_path / "token"
    token_file.write_text("leaky")
    token_file.chmod(0o644)
    with caplog.at_level(logging.ERROR, logger="claude_daily_summary.summarizer"):
        with pytest.raises(SystemExit):
            resolve_oauth_token(token_file)
    assert "chmod 600" in caplog.text
