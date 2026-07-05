from datetime import date

from claude_daily_summary import cli, config
from claude_daily_summary.summarizer import Outcome, SummaryResult


def _dates(*days):
    return [date(2026, 6, day) for day in days]


def _ok(day):
    return SummaryResult(Outcome.OK, markdown=f"# Claude Code Daily Summary - {day}\n")


def test_backfill_contiguous_with_content_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUMMARIES_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_CALLS_PER_RUN", 3)

    d1, d2, d3, d4, d5, d6 = _dates(1, 2, 3, 4, 5, 6)
    digests = {d1: ["s"], d3: ["s"], d4: ["s"], d5: ["s"]}  # d2, d6 have no activity
    horizon = d1

    def summarize(day):
        if day == d3:  # call ran, output unusable -> failure placeholder
            return SummaryResult(Outcome.CONTENT_FAILURE, footer="\n---\n_x_\n")
        return _ok(day)

    failures = cli.backfill([d1, d2, d3, d4, d5, d6], digests, horizon, summarize)

    def exists(day):
        return (tmp_path / f"daily-summary-{day.isoformat()}.md").exists()

    # No holes behind the frontier, including the failed day; cap stops at d5/d6.
    assert exists(d1) and exists(d2) and exists(d3) and exists(d4)
    assert not exists(d5) and not exists(d6)
    assert failures == 1

    failed_text = (tmp_path / f"daily-summary-{d3.isoformat()}.md").read_text()
    assert "failed" in failed_text.lower()
    assert "delete this file to retry" in failed_text.lower()


def test_backfill_systemic_failure_aborts_without_placeholder(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUMMARIES_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_CALLS_PER_RUN", 3)

    d1, d2, d3 = _dates(1, 2, 3)
    digests = {d1: ["s"], d2: ["s"], d3: ["s"]}
    horizon = d1

    def summarize(day):
        if day == d1:
            return SummaryResult(Outcome.SYSTEMIC_FAILURE)
        return _ok(day)

    failures = cli.backfill([d1, d2, d3], digests, horizon, summarize)

    # A systemic failure writes nothing and aborts, so the day retries next run
    # instead of being marked done with a placeholder.
    assert not (tmp_path / f"daily-summary-{d1.isoformat()}.md").exists()
    assert not (tmp_path / f"daily-summary-{d2.isoformat()}.md").exists()
    assert failures == 1


def test_backfill_writes_no_activity_and_pruned_placeholders(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUMMARIES_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_CALLS_PER_RUN", 3)

    pruned_day, quiet_day = _dates(1, 5)
    horizon = date(2026, 6, 3)  # pruned_day is older than the horizon

    def summarize(day):  # pragma: no cover - no activity days call it
        raise AssertionError("no model call expected")

    failures = cli.backfill([pruned_day, quiet_day], {}, horizon, summarize)

    assert failures == 0
    assert "No transcript data" in (
        tmp_path / f"daily-summary-{pruned_day.isoformat()}.md"
    ).read_text()
    assert "No Claude Code activity" in (
        tmp_path / f"daily-summary-{quiet_day.isoformat()}.md"
    ).read_text()
