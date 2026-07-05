from datetime import date

from claude_daily_summary import cli, config


def _dates(*days):
    return [date(2026, 6, day) for day in days]


def test_backfill_is_contiguous_with_cap_and_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUMMARIES_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_CALLS_PER_RUN", 3)

    d1, d2, d3, d4, d5, d6 = _dates(1, 2, 3, 4, 5, 6)
    digests = {
        d1: ["s"],            # activity, succeeds  (call 1)
        d3: ["s"],            # activity, fails     (call 2)
        d4: ["s"],            # activity, succeeds  (call 3)
        d5: ["s"],            # activity, over cap  -> stop before here
        # d2, d6 have no activity
    }
    horizon = d1  # nothing pruned

    def summarize(day):
        return None if day == d3 else f"# Claude Code Daily Summary - {day}\n"

    failures = cli.backfill([d1, d2, d3, d4, d5, d6], digests, horizon, summarize)

    def exists(day):
        return (tmp_path / f"daily-summary-{day.isoformat()}.md").exists()

    # Everything up to the frontier has a file: no holes, including the failed day.
    assert exists(d1) and exists(d2) and exists(d3) and exists(d4)
    # The cap stops the run; the remainder is a contiguous suffix for next time.
    assert not exists(d5) and not exists(d6)
    assert failures == 1

    # The failed day is a marked placeholder, not a gap, and invites a retry.
    failed_text = (tmp_path / f"daily-summary-{d3.isoformat()}.md").read_text()
    assert "failed" in failed_text.lower()
    assert "delete this file to retry" in failed_text.lower()


def test_backfill_writes_no_activity_and_pruned_placeholders(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SUMMARIES_DIR", tmp_path)
    monkeypatch.setattr(config, "MAX_CALLS_PER_RUN", 3)

    pruned_day, quiet_day = _dates(1, 5)
    horizon = date(2026, 6, 3)  # pruned_day is older than the horizon

    def summarize(day):  # pragma: no cover - no activity days call it
        raise AssertionError("no model call expected")

    failures = cli.backfill([pruned_day, quiet_day], {}, horizon, summarize)

    assert failures == 0
    assert "pruned" in (tmp_path / f"daily-summary-{pruned_day.isoformat()}.md").read_text()
    assert "No Claude Code activity" in (
        tmp_path / f"daily-summary-{quiet_day.isoformat()}.md"
    ).read_text()
