from datetime import date, datetime, timezone

from claude_daily_summary import cli, config
from claude_daily_summary.digest import SessionDigest
from claude_daily_summary.summarizer import Outcome, SummaryResult


def _dates(*days):
    return [date(2026, 6, day) for day in days]


def _sessions(day):
    session = SessionDigest("s")
    session.record_time(datetime(2026, 6, day.day, 9, 0, tzinfo=timezone.utc))
    session.record_time(datetime(2026, 6, day.day, 9, 10, tzinfo=timezone.utc))
    return [session]


def _ok(day):
    markdown = (
        f"# Claude Code Daily Summary - {day}\n\n"
        "## Summary\nDid things.\n\n"
        "## Repos / Workspaces\n- repo\n\n"
        "---\n_Generation cost: 1 tokens (1 input + 0 output)._\n"
    )
    return SummaryResult(Outcome.OK, markdown=markdown)


def test_backfill_contiguous_with_content_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUMMARIES_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_CALLS_PER_RUN", 3)

    d1, d2, d3, d4, d5, d6 = _dates(1, 2, 3, 4, 5, 6)
    # d2, d6 have no activity
    digests = {d: _sessions(d) for d in (d1, d3, d4, d5)}
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

    # Days with sessions carry the measured active time, success or failure.
    ok_text = (tmp_path / f"daily-summary-{d1.isoformat()}.md").read_text()
    activity_heading = "## Estimated Claude Code Activity Time"
    assert f"{activity_heading}\n10 minutes" in ok_text
    assert f"{activity_heading}\n10 minutes" in failed_text
    # Metrics sit after the Summary section, not in the footer.
    assert ok_text.index("## Summary") < ok_text.index(activity_heading)
    assert ok_text.index(activity_heading) < ok_text.index("## Repos / Workspaces")


def test_backfill_systemic_failure_aborts_without_placeholder(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUMMARIES_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_CALLS_PER_RUN", 3)

    d1, d2, d3 = _dates(1, 2, 3)
    digests = {d: _sessions(d) for d in (d1, d2, d3)}
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


def test_insert_after_summary_places_block_before_next_heading():
    markdown = "# T\n\n## Summary\nBody.\n\n## Repos / Workspaces\n- r\n"
    block = "## Estimated Claude Code Activity Time\n5 minutes."
    result = cli.insert_after_summary(markdown, block)
    assert result.index("Body.") < result.index(block)
    assert result.index(block) < result.index("## Repos / Workspaces")


def test_insert_after_summary_falls_back_to_append():
    markdown = "# T\n\nUnstructured text.\n"
    block = "## Estimated Claude Code Activity Time\n5 minutes."
    result = cli.insert_after_summary(markdown, block)
    assert result.endswith(block + "\n")


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
