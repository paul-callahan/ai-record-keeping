import json
import os
from datetime import datetime
from pathlib import Path

from codex_daily_summary.digest import TokenUsage, SessionDigest, build_digest, collect_digests, estimate_active_minutes


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def test_collect_digests_buckets_by_event_date_and_tracks_horizon(tmp_path):
    sessions_dir = tmp_path / "sessions"
    archived_dir = tmp_path / "archived_sessions"
    rollout = sessions_dir / "2026" / "07" / "02" / "rollout-2026-07-02T10-00-00-test.jsonl"
    write_jsonl(
        rollout,
        [
            {
                "timestamp": "2026-07-01T16:00:00Z",
                "type": "session_meta",
                "payload": {"cwd": "/work/repo", "git": {"branch": "main"}, "session_id": "abc"},
            },
            {
                "timestamp": "2026-07-02T17:00:00Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Implement the summary job"},
            },
        ],
    )

    collection = collect_digests(
        target_days=[__import__("datetime").date(2026, 7, 2)],
        sessions_dir=sessions_dir,
        archived_dir=archived_dir,
    )

    assert collection.oldest_event_date.isoformat() == "2026-07-01"
    sessions = list(collection.date_buckets[__import__("datetime").date(2026, 7, 2)].values())
    assert len(sessions) == 1
    assert sessions[0].cwd == "/work/repo"
    assert sessions[0].branch == "main"
    assert sessions[0].user_prompts == ["Implement the summary job"]


def test_collect_digests_uses_event_timestamp_not_file_mtime(tmp_path):
    sessions_dir = tmp_path / "sessions"
    archived_dir = tmp_path / "archived_sessions"
    rollout = sessions_dir / "2026" / "07" / "02" / "rollout-stale-mtime.jsonl"
    write_jsonl(
        rollout,
        [
            {
                "timestamp": "2026-07-02T17:00:00Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "This event is in the target window"},
            },
        ],
    )
    os.utime(rollout, (0, 0))

    collection = collect_digests(
        target_days=[__import__("datetime").date(2026, 7, 2)],
        sessions_dir=sessions_dir,
        archived_dir=archived_dir,
    )

    sessions = list(collection.date_buckets[__import__("datetime").date(2026, 7, 2)].values())
    assert sessions[0].user_prompts == ["This event is in the target window"]


def test_collect_digests_sums_split_and_unsplit_token_usage_by_event_date(tmp_path):
    day = __import__("datetime").date(2026, 7, 2)
    sessions_dir = tmp_path / "sessions"
    archived_dir = tmp_path / "archived_sessions"
    rollout = sessions_dir / "2026" / "07" / "02" / "rollout-token-counts.jsonl"
    write_jsonl(
        rollout,
        [
            {
                "timestamp": "2026-07-02T17:00:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {"input_tokens": 70, "output_tokens": 30, "total_tokens": 100},
                        "total_token_usage": {"total_tokens": 1000},
                    },
                },
            },
            {
                "timestamp": "2026-07-02T17:01:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"total_tokens": 25}},
                },
            },
            {
                "timestamp": "2026-07-02T17:02:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 9999}},
                },
            },
        ],
    )

    collection = collect_digests(
        target_days=[day],
        sessions_dir=sessions_dir,
        archived_dir=archived_dir,
    )

    usage = collection.token_usage[day]
    assert usage.input_tokens == 70
    assert usage.output_tokens == 30
    assert usage.unsplit_tokens == 25
    assert usage.total_tokens == 125


def test_late_session_meta_applies_to_existing_digest(tmp_path):
    sessions_dir = tmp_path / "sessions"
    archived_dir = tmp_path / "archived_sessions"
    rollout = sessions_dir / "2026" / "07" / "02" / "rollout-late-meta.jsonl"
    write_jsonl(
        rollout,
        [
            {
                "timestamp": "2026-07-02T17:00:00Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Prompt before metadata"},
            },
            {
                "timestamp": "2026-07-02T17:01:00Z",
                "type": "session_meta",
                "payload": {"cwd": "/work/repo", "git": {"branch": "main"}, "session_id": "abc"},
            },
        ],
    )

    collection = collect_digests(
        target_days=[__import__("datetime").date(2026, 7, 2)],
        sessions_dir=sessions_dir,
        archived_dir=archived_dir,
    )

    sessions = list(collection.date_buckets[__import__("datetime").date(2026, 7, 2)].values())
    assert sessions[0].cwd == "/work/repo"
    assert sessions[0].branch == "main"
    assert sessions[0].session_id == "abc"


def test_collect_digests_filters_injected_prompt_prefixes(tmp_path):
    sessions_dir = tmp_path / "sessions"
    archived_dir = tmp_path / "archived_sessions"
    rollout = sessions_dir / "2026" / "07" / "02" / "rollout-test.jsonl"
    write_jsonl(
        rollout,
        [
            {
                "timestamp": "2026-07-02T17:00:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "\n# Files mentioned by the user:\nignored",
                },
            },
            {
                "timestamp": "2026-07-02T17:01:00Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Keep this prompt"},
            },
        ],
    )

    collection = collect_digests(
        target_days=[__import__("datetime").date(2026, 7, 2)],
        sessions_dir=sessions_dir,
        archived_dir=archived_dir,
    )

    sessions = list(collection.date_buckets[__import__("datetime").date(2026, 7, 2)].values())
    assert sessions[0].user_prompts == ["Keep this prompt"]


def test_estimate_active_minutes_ignores_long_gaps():
    event_times = [
        datetime.fromisoformat("2026-07-02T09:00:00-07:00"),
        datetime.fromisoformat("2026-07-02T09:10:00-07:00"),
        datetime.fromisoformat("2026-07-02T10:00:00-07:00"),
        datetime.fromisoformat("2026-07-02T10:05:00-07:00"),
    ]

    assert estimate_active_minutes(event_times) == 15


def test_build_digest_includes_estimated_active_time_and_token_usage():
    day = __import__("datetime").date(2026, 7, 2)
    session = SessionDigest(source_file=Path("one.jsonl"), session_id="one", cwd="/tmp/one")
    session.note_event_time(datetime.fromisoformat("2026-07-02T09:00:00-07:00"))
    session.note_event_time(datetime.fromisoformat("2026-07-02T09:12:00-07:00"))

    rendered = build_digest(day, [session], token_usage=TokenUsage(input_tokens=1000, output_tokens=200, unsplit_tokens=34))

    assert "Estimated Codex active time: 0 hours 12 minutes (12 minutes) using a 15-minute inactivity cutoff" in rendered
    assert "Estimated Codex token usage: 1,234 total tokens (1,000 input + 200 output + 34 unsplit total) from local token_count events" in rendered
    assert "Estimated active time: 0 hours 12 minutes (12 minutes)" in rendered


def test_build_digest_marks_truncation_when_sessions_are_dropped():
    day = __import__("datetime").date(2026, 7, 2)
    first = SessionDigest(source_file=Path("one.jsonl"), session_id="one", cwd="/tmp/one")
    second = SessionDigest(source_file=Path("two.jsonl"), session_id="two", cwd="/tmp/two")
    first.user_prompts.append("x" * 200)
    second.user_prompts.append("y" * 200)

    rendered = build_digest(day, [first, second], char_cap=240)

    assert "[digest truncated:" in rendered
    assert "Source:" not in rendered
