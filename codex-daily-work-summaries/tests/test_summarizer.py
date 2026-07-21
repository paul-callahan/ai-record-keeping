import logging
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from codex_daily_summary import summarizer
from codex_daily_summary.activity_time import format_active_duration
from codex_daily_summary.digest import TokenUsage
from codex_daily_summary.summarizer import (
    estimated_time_line,
    estimated_token_line,
    generation_failed_summary,
    parse_token_usage,
    render_generation_footer,
    summarize_with_codex,
    zero_cost_footer,
)


def test_generation_footer_with_input_and_output_tokens():
    assert (
        render_generation_footer(28631, 26100, 2531)
        == "_Generation cost: 28,631 tokens (26,100 input + 2,531 output)._"
    )


def test_zero_cost_footer():
    assert zero_cost_footer() == "_Generation cost: 0 tokens (no model call)._"


def test_format_active_duration_includes_hours_and_total_minutes():
    assert format_active_duration(373) == "6 hours 13 minutes (373 minutes)"
    assert format_active_duration(61) == "1 hour 1 minute (61 minutes)"


def test_estimated_time_line_uses_hours_minutes_and_total_minutes():
    assert "0 hours 1 minute (1 minute)" in estimated_time_line(1)
    assert "0 hours 2 minutes (2 minutes)" in estimated_time_line(2)


def test_estimated_token_line_formats_split_and_unsplit_tokens():
    usage = TokenUsage(input_tokens=1000000, output_tokens=200000, unsplit_tokens=34567)

    assert estimated_token_line(usage) == (
        "Estimated Codex token usage: 1,234,567 total tokens "
        "(1,000,000 input + 200,000 output + 34,567 unsplit total) "
        "from local token_count events."
    )


def test_generation_failed_summary_instructs_manual_retry():
    rendered = generation_failed_summary(
        date(2026, 7, 2),
        "codex timed out",
        42,
        TokenUsage(input_tokens=1000, output_tokens=200, unsplit_tokens=34),
    )

    assert rendered.startswith("# Codex Daily Summary - 2026-07-02")
    assert "Summary generation failed" in rendered
    assert "Estimated Codex activity time: 0 hours 42 minutes (42 minutes)" in rendered
    assert "Estimated Codex token usage: 1,234 total tokens (1,000 input + 200 output + 34 unsplit total) from local token_count events" in rendered
    assert "Failure: codex timed out" in rendered
    assert "Delete this file" in rendered


def test_parse_token_usage_accepts_authoritative_total_tokens():
    stdout = '{"usage":{"total_tokens":28631,"input_tokens":26100,"output_tokens":2531}}\n'

    assert parse_token_usage(stdout) == (28631, 26100, 2531)


def test_parse_token_usage_accepts_codex_token_count_event():
    stdout = (
        '{"type":"event_msg","payload":{"type":"token_count","info":'
        '{"total_token_usage":{"input_tokens":26100,"output_tokens":2531,"total_tokens":28631}}}}\n'
    )

    assert parse_token_usage(stdout) == (28631, 26100, 2531)


def test_parse_token_usage_rejects_ambiguous_token_fields():
    stdout = '{"usage":{"tokens":28631,"input_tokens":26100,"output_tokens":2531}}\n'

    assert parse_token_usage(stdout) is None


def test_summarize_with_codex_rejects_non_markdown_output(monkeypatch, tmp_path):
    def fake_run(args, **kwargs):
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text("not markdown", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)

    result = summarize_with_codex(
        "codex",
        tmp_path,
        date(2026, 7, 2),
        "digest",
        logging.getLogger("test"),
    )

    assert result.failed
    assert result.markdown is None
    assert result.failure_reason == "model output was empty or malformed"
