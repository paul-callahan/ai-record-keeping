"""Parse Claude Code session transcripts into compact per-day digests."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from claude_daily_summary import config


def _idle_threshold() -> timedelta:
    return timedelta(minutes=config.IDLE_THRESHOLD_MINUTES)


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
    # Token usage summed from assistant events' message.usage.
    fresh_input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    # Periods of activity: consecutive events closer than the idle threshold
    # are merged into one (start, end) block. Events arrive in file order,
    # which is chronological within a session.
    blocks: list[tuple[datetime, datetime]] = field(default_factory=list)

    def record_time(self, ts: datetime) -> None:
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts
        if self.blocks:
            start, end = self.blocks[-1]
            if ts <= end + _idle_threshold():
                self.blocks[-1] = (start, max(end, ts))
                return
        self.blocks.append((ts, ts))

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
        usage = event.get("message", {}).get("usage")
        if isinstance(usage, dict):
            # Fresh input: uncached input plus cache creation, both newly
            # processed. Cache reads are tracked separately; they dominate raw
            # volume but weigh far less against plan limits.
            session.fresh_input_tokens += (usage.get("input_tokens") or 0) + (
                usage.get("cache_creation_input_tokens") or 0
            )
            session.output_tokens += usage.get("output_tokens") or 0
            session.cache_read_tokens += usage.get("cache_read_input_tokens") or 0
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


def merged_active_blocks(
    sessions: list[SessionDigest],
) -> list[tuple[datetime, datetime]]:
    """Union the sessions' activity blocks, merging gaps under the idle threshold.

    Overlapping or near-adjacent blocks from parallel sessions count once.
    """
    blocks = sorted(block for session in sessions for block in session.blocks)
    merged: list[tuple[datetime, datetime]] = []
    for start, end in blocks:
        if merged and start <= merged[-1][1] + _idle_threshold():
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _format_duration(total: timedelta) -> str:
    total_minutes = int(total.total_seconds()) // 60
    hours, minutes = divmod(total_minutes, 60)
    hour_word = "hour" if hours == 1 else "hours"
    minute_word = "minute" if minutes == 1 else "minutes"
    if hours:
        return f"{hours} {hour_word} {minutes} {minute_word} ({total_minutes} minutes)"
    return f"{minutes} {minute_word}"


ACTIVITY_TIME_HEADING = "## Estimated Claude Code Activity Time"
TOKEN_USAGE_HEADING = "## Estimated Claude Code Token Usage"


def active_time_line(sessions: list[SessionDigest]) -> str:
    """Render the activity-time section, e.g.

    ## Estimated Claude Code Activity Time
    6 hours 13 minutes (373 minutes) (09:14-12:05, 14:30-16:12).
    """
    merged = merged_active_blocks(sessions)
    if not merged:
        return f"{ACTIVITY_TIME_HEADING}\n0 minutes."
    total = sum((end - start for start, end in merged), timedelta())
    ranges = ", ".join(
        f"{start.astimezone(config.LOCAL_TZ):%H:%M}-"
        f"{end.astimezone(config.LOCAL_TZ):%H:%M}"
        for start, end in merged
    )
    return f"{ACTIVITY_TIME_HEADING}\n{_format_duration(total)} ({ranges})."


def token_usage_line(sessions: list[SessionDigest]) -> str:
    """Render the day's token usage, or empty if the transcripts carried none.

    Consumed (fresh input + output) approximates real plan usage; processed
    additionally counts cache reads, which dominate volume but cost little.
    """
    fresh_input = sum(s.fresh_input_tokens for s in sessions)
    output = sum(s.output_tokens for s in sessions)
    cache_read = sum(s.cache_read_tokens for s in sessions)
    consumed = fresh_input + output
    processed = consumed + cache_read
    if processed == 0:
        return ""
    return (
        f"{TOKEN_USAGE_HEADING}\n"
        f"{consumed:,} consumed (fresh input + output); "
        f"{processed:,} processed (including cache reads)."
    )


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
