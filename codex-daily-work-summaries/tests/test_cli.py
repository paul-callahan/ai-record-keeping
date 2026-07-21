import logging
from datetime import date

from codex_daily_summary import cli
from codex_daily_summary.digest import DigestCollection, SessionDigest, TokenUsage
from codex_daily_summary.summarizer import SummaryResult


def collection_for_days(days, tmp_path, token_usage=None):
    return DigestCollection(
        date_buckets={
            day: {
                day.isoformat(): SessionDigest(
                    source_file=tmp_path / f"rollout-{day}.jsonl",
                    session_id=day.isoformat(),
                )
            }
            for day in days
        },
        token_usage=token_usage or {},
        oldest_event_date=min(days),
    )


def test_process_missing_dates_stops_after_model_call_cap(monkeypatch, tmp_path):
    days = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    collection = collection_for_days(days[:2], tmp_path)

    monkeypatch.setattr(cli, "collect_digests", lambda missing_dates: collection)
    monkeypatch.setattr(cli.config, "MAX_CALLS_PER_RUN", 1)
    monkeypatch.setattr(cli, "summary_path", lambda day: tmp_path / f"daily-summary-{day}.md")
    monkeypatch.setattr(cli, "build_digest", lambda day, sessions, token_usage=None: "digest")
    monkeypatch.setattr(
        cli,
        "summarize_with_codex",
        lambda codex, home, day, digest, logger: SummaryResult(
            markdown=f"# Codex Daily Summary - {day}\n"
        ),
    )

    result = cli.process_missing_dates("codex", days, logging.getLogger("test"))

    assert result == 0
    assert (tmp_path / "daily-summary-2026-07-01.md").exists()
    assert not (tmp_path / "daily-summary-2026-07-02.md").exists()
    assert not (tmp_path / "daily-summary-2026-07-03.md").exists()


def test_process_missing_dates_writes_failure_placeholder_and_continues(monkeypatch, tmp_path):
    days = [date(2026, 7, 1), date(2026, 7, 2)]
    collection = collection_for_days(
        days,
        tmp_path,
        token_usage={days[0]: TokenUsage(input_tokens=1000, output_tokens=200, unsplit_tokens=34)},
    )

    def summarize(codex, home, day, digest, logger):
        if day == days[0]:
            return SummaryResult(markdown=None, failed=True, failure_reason="model output was empty or malformed")
        return SummaryResult(markdown=f"# Codex Daily Summary - {day}\n")

    monkeypatch.setattr(cli, "collect_digests", lambda missing_dates: collection)
    monkeypatch.setattr(cli.config, "MAX_CALLS_PER_RUN", 3)
    monkeypatch.setattr(cli, "summary_path", lambda day: tmp_path / f"daily-summary-{day}.md")
    monkeypatch.setattr(cli, "build_digest", lambda day, sessions, token_usage=None: "digest")
    monkeypatch.setattr(cli, "summarize_with_codex", summarize)

    result = cli.process_missing_dates("codex", days, logging.getLogger("test"))

    failed_summary = (tmp_path / "daily-summary-2026-07-01.md").read_text(encoding="utf-8")
    assert result == 1
    assert failed_summary.startswith("# Codex Daily Summary - 2026-07-01")
    assert "Summary generation failed" in failed_summary
    assert "Estimated Codex activity time: 0 hours 0 minutes (0 minutes)" in failed_summary
    assert "Estimated Codex token usage: 1,234 total tokens (1,000 input + 200 output + 34 unsplit total) from local token_count events" in failed_summary
    assert "Failure: model output was empty or malformed" in failed_summary
    assert "Delete this file" in failed_summary
    assert (tmp_path / "daily-summary-2026-07-02.md").exists()


def test_failure_placeholders_prevent_oldest_days_from_stalling_next_run(monkeypatch, tmp_path):
    days = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 4)]
    collection = collection_for_days(days, tmp_path)

    monkeypatch.setattr(cli, "collect_digests", lambda missing_dates: collection)
    monkeypatch.setattr(cli.config, "MAX_CALLS_PER_RUN", 3)
    monkeypatch.setattr(cli, "summary_path", lambda day: tmp_path / f"daily-summary-{day}.md")
    monkeypatch.setattr(cli, "build_digest", lambda day, sessions, token_usage=None: "digest")
    monkeypatch.setattr(
        cli,
        "summarize_with_codex",
        lambda codex, home, day, digest, logger: SummaryResult(
            markdown=None,
            failed=True,
            failure_reason="codex timed out",
        ),
    )

    first_result = cli.process_missing_dates("codex", days, logging.getLogger("test"))

    assert first_result == 1
    assert (tmp_path / "daily-summary-2026-07-01.md").exists()
    assert (tmp_path / "daily-summary-2026-07-02.md").exists()
    assert (tmp_path / "daily-summary-2026-07-03.md").exists()
    assert not (tmp_path / "daily-summary-2026-07-04.md").exists()

    monkeypatch.setattr(
        cli,
        "summarize_with_codex",
        lambda codex, home, day, digest, logger: SummaryResult(
            markdown=f"# Codex Daily Summary - {day}\n"
        ),
    )
    next_missing = [day for day in days if not (tmp_path / f"daily-summary-{day}.md").exists()]

    second_result = cli.process_missing_dates("codex", next_missing, logging.getLogger("test"))

    assert second_result == 0
    assert (tmp_path / "daily-summary-2026-07-04.md").exists()
