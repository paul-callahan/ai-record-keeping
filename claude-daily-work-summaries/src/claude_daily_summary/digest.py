"""Parse Claude Code session transcripts into compact per-day digests."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from claude_daily_summary import config


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit] + " [truncated]"
    return text


@dataclass
class SessionDigest:
    session_id: str
    project: str | None = None
    branch: str | None = None
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    prompts: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def record_time(self, ts: datetime) -> None:
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts

    def render(self) -> str:
        start = self.first_ts.astimezone(config.LOCAL_TZ).strftime("%H:%M")
        end = self.last_ts.astimezone(config.LOCAL_TZ).strftime("%H:%M")
        lines = [
            f"Session {self.session_id} | project: {self.project or 'unknown'}"
            f" | branch: {self.branch or 'unknown'} | {start} - {end}"
        ]
        if self.prompts:
            lines.append("User prompts:")
            lines.extend(f"- {p}" for p in self.prompts)
        if self.commands:
            lines.append("Commands run:")
            lines.extend(f"- {c}" for c in self.commands)
        if self.files:
            lines.append("Files edited:")
            lines.extend(f"- {f}" for f in self.files)
        return "\n".join(lines)


def _parse_timestamp(event: dict) -> datetime | None:
    raw = event.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _record_event(session: SessionDigest, event: dict, slug: str) -> None:
    if session.project is None:
        session.project = event.get("cwd") or slug
    if session.branch is None and event.get("gitBranch"):
        session.branch = event["gitBranch"]
    etype = event.get("type")
    if etype == "user" and not event.get("isSidechain"):
        content = event.get("message", {}).get("content")
        if isinstance(content, str) and content.strip():
            session.prompts.append(truncate(content, config.PROMPT_TRUNCATE_CHARS))
    elif etype == "assistant":
        blocks = event.get("message", {}).get("content")
        if not isinstance(blocks, list):
            return
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tool_input = block.get("input") or {}
            if name == "Bash" and tool_input.get("command"):
                session.commands.append(
                    truncate(tool_input["command"], config.COMMAND_TRUNCATE_CHARS)
                )
            elif name in ("Edit", "Write") and tool_input.get("file_path"):
                path = tool_input["file_path"]
                if path not in session.files:
                    session.files.append(path)


def collect_digests(
    target_dates: set[date],
    projects_dir: Path = config.PROJECTS_DIR,
) -> tuple[dict[date, list[SessionDigest]], date | None]:
    """Return ({date: [SessionDigest]}, horizon) for the given LA calendar dates.

    horizon is the oldest event date seen across all scanned transcripts, or None
    if no events were seen; dates older than it have no data because the
    transcripts were pruned, not because there was no activity.
    """
    oldest_start = datetime.combine(
        min(target_dates), datetime.min.time(), config.LOCAL_TZ
    )
    oldest_epoch = oldest_start.timestamp()
    by_date: dict[date, dict[str, SessionDigest]] = {}
    horizon: date | None = None

    for transcript in sorted(projects_dir.glob("*/*.jsonl")):
        try:
            if transcript.stat().st_mtime < oldest_epoch:
                continue
        except OSError:
            continue
        slug = transcript.parent.name
        session_id = transcript.stem
        with open(transcript, errors="replace") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_timestamp(event)
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                day = ts.astimezone(config.LOCAL_TZ).date()
                if horizon is None or day < horizon:
                    horizon = day
                if day not in target_dates:
                    continue
                session = by_date.setdefault(day, {}).setdefault(
                    session_id, SessionDigest(session_id)
                )
                session.record_time(ts)
                _record_event(session, event, slug)

    digests = {
        day: sorted(sessions.values(), key=lambda s: s.first_ts)
        for day, sessions in by_date.items()
    }
    return digests, horizon


def build_digest(
    sessions: list[SessionDigest],
    char_cap: int = config.DIGEST_CHAR_CAP,
) -> str:
    blocks = []
    used = 0
    included = 0
    for session in sessions:
        block = session.render()
        if used + len(block) > char_cap and included > 0:
            break
        blocks.append(block)
        used += len(block)
        included += 1
    digest = "\n\n".join(blocks)
    if included < len(sessions):
        digest += (
            f"\n\n[digest truncated: {included} of {len(sessions)} sessions included]"
        )
    return digest
