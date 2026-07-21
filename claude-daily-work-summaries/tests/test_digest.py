import json
from datetime import date, datetime, timezone

from claude_daily_summary.digest import (
    SessionDigest,
    active_time_line,
    build_digest,
    collect_digests,
    merged_active_blocks,
    token_usage_line,
)


def _ts(hour, minute):
    return datetime(2026, 7, 1, hour, minute, tzinfo=timezone.utc)


def test_collect_digests_buckets_sessions_and_tracks_horizon(tmp_path):
    project = tmp_path / "-Users-x-dev-proj"
    project.mkdir()
    lines = [
        # event before the target window: contributes to horizon only
        json.dumps({
            "type": "user",
            "timestamp": "2026-06-25T18:00:00.000Z",
            "cwd": "/Users/x/dev/proj",
            "message": {"content": "old day work"},
        }),
        # real user prompt on the target day
        json.dumps({
            "type": "user",
            "timestamp": "2026-07-01T18:00:00.000Z",
            "isSidechain": False,
            "cwd": "/Users/x/dev/proj",
            "gitBranch": "main",
            "message": {"content": "do the thing"},
        }),
        # sidechain prompt: excluded from prompts
        json.dumps({
            "type": "user",
            "timestamp": "2026-07-01T18:01:00.000Z",
            "isSidechain": True,
            "message": {"content": "subagent noise"},
        }),
        # malformed line: skipped
        "not json {{{",
        # tool activity, with API usage
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-07-01T18:02:00.000Z",
            "message": {"usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 5000,
                "output_tokens": 25,
            }, "content": [
                {"type": "tool_use", "name": "Bash",
                 "input": {"command": "git commit -m 'fix'"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/Users/x/dev/proj/a.py"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/Users/x/dev/proj/a.py"}},
            ]},
        }),
    ]
    (project / "abc123.jsonl").write_text("\n".join(lines))

    digests, horizon = collect_digests({date(2026, 7, 1)}, projects_dir=tmp_path)

    assert horizon == date(2026, 6, 25)
    sessions = digests[date(2026, 7, 1)]
    assert len(sessions) == 1
    session = sessions[0]
    assert session.session_id == "abc123"
    assert session.project == "/Users/x/dev/proj"
    assert session.branch == "main"
    assert session.prompts == ["do the thing"]
    assert session.commands == ["git commit -m 'fix'"]
    assert session.files == ["/Users/x/dev/proj/a.py"]
    assert session.fresh_input_tokens == 150  # input + cache creation
    assert session.output_tokens == 25
    assert session.cache_read_tokens == 5000


def test_collect_digests_returns_none_horizon_when_no_transcripts(tmp_path):
    digests, horizon = collect_digests({date(2026, 7, 1)}, projects_dir=tmp_path)
    assert digests == {}
    assert horizon is None


def _session_with_prompt(session_id: str, prompt: str) -> SessionDigest:
    session = SessionDigest(session_id)
    session.record_time(datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc))
    session.prompts.append(prompt)
    return session


def test_build_digest_caps_whole_sessions_and_notes_truncation():
    first = _session_with_prompt("a", "x" * 200)
    second = _session_with_prompt("b", "y" * 200)

    digest = build_digest([first, second], char_cap=250)

    assert "x" * 200 in digest
    assert "y" * 200 not in digest
    assert "[digest truncated: 1 of 2 sessions included]" in digest


def test_build_digest_without_truncation_has_no_note():
    digest = build_digest([_session_with_prompt("a", "hello")], char_cap=1000)
    assert "digest truncated" not in digest
    assert "hello" in digest


def test_session_blocks_split_on_idle_gaps():
    session = SessionDigest("a")
    for hour, minute in [(9, 0), (9, 10), (9, 20), (10, 0), (10, 5)]:
        session.record_time(_ts(hour, minute))
    # 9:20 -> 10:00 is a 40 min gap, over the 15 min threshold: two blocks.
    assert session.blocks == [
        (_ts(9, 0), _ts(9, 20)),
        (_ts(10, 0), _ts(10, 5)),
    ]


def test_merged_active_blocks_unions_parallel_sessions():
    first = SessionDigest("a")
    for hour, minute in [(9, 0), (9, 14)]:
        first.record_time(_ts(hour, minute))
    second = SessionDigest("b")
    for hour, minute in [(9, 20), (9, 34)]:
        second.record_time(_ts(hour, minute))
    # Near-adjacent activity from parallel sessions counts once: 9:00 - 9:34.
    assert merged_active_blocks([first, second]) == [(_ts(9, 0), _ts(9, 34))]


def test_active_time_line_formats_total_and_ranges(monkeypatch):
    from claude_daily_summary import config
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(config, "_local_tz_cache", ZoneInfo("UTC"))

    session = SessionDigest("a")
    for hour, minute in [(9, 0), (9, 10), (9, 20), (14, 0), (14, 5)]:
        session.record_time(_ts(hour, minute))
    line = active_time_line([session])
    assert line == ("## Estimated Claude Code Activity Time\n"
                    "25 minutes (09:00-09:20, 14:00-14:05).")


def test_active_time_line_over_an_hour_includes_total_minutes(monkeypatch):
    from claude_daily_summary import config
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(config, "_local_tz_cache", ZoneInfo("UTC"))

    session = SessionDigest("a")
    # 6h13m of continuous activity: events every 10 minutes from 9:00 to 15:13.
    for offset in range(0, 373, 10):
        session.record_time(_ts(9 + (offset // 60), offset % 60))
    session.record_time(_ts(15, 13))
    line = active_time_line([session])
    assert line == ("## Estimated Claude Code Activity Time\n"
                    "6 hours 13 minutes (373 minutes) (09:00-15:13).")


def test_active_time_line_zero_when_no_blocks():
    assert active_time_line([]) == "## Estimated Claude Code Activity Time\n0 minutes."


def test_token_usage_line_labels_consumed_and_processed():
    first = SessionDigest("a", fresh_input_tokens=1000, output_tokens=200,
                          cache_read_tokens=50_000)
    second = SessionDigest("b", fresh_input_tokens=500, output_tokens=100,
                           cache_read_tokens=10_000)
    line = token_usage_line([first, second])
    assert line == ("## Estimated Claude Code Token Usage\n"
                    "1,800 consumed (fresh input + output); "
                    "61,800 processed (including cache reads).")


def test_token_usage_line_empty_without_usage_data():
    assert token_usage_line([SessionDigest("a")]) == ""
