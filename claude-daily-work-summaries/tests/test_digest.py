import json
from datetime import date, datetime, timezone

from claude_daily_summary.digest import SessionDigest, build_digest, collect_digests


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
        # tool activity
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-07-01T18:02:00.000Z",
            "message": {"content": [
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
