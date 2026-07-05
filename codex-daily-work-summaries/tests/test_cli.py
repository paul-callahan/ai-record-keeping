import logging
from datetime import date

from codex_daily_summary import cli
from codex_daily_summary.digest import DigestCollection, SessionDigest
from codex_daily_summary.summarizer import SummaryResult


def test_process_missing_dates_stops_after_model_call_cap(monkeypatch, tmp_path):
    days = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    collection = DigestCollection(
        date_buckets={
            days[0]: {"one": SessionDigest(source_file=tmp_path / "one.jsonl", session_id="one")},
            days[1]: {"two": SessionDigest(source_file=tmp_path / "two.jsonl", session_id="two")},
        },
        oldest_event_date=days[0],
    )

    monkeypatch.setattr(cli, "collect_digests", lambda missing_dates: collection)
    monkeypatch.setattr(cli.config, "MAX_CALLS_PER_RUN", 1)
    monkeypatch.setattr(cli, "summary_path", lambda day: tmp_path / f"daily-summary-{day}.md")
    monkeypatch.setattr(cli, "build_digest", lambda day, sessions: "digest")
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
