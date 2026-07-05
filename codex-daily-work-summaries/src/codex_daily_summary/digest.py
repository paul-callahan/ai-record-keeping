import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import config


PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


@dataclass
class SessionMeta:
    cwd: Optional[str] = None
    branch: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class SessionDigest:
    source_file: Path
    session_id: str
    cwd: Optional[str] = None
    branch: Optional[str] = None
    first_event: Optional[datetime] = None
    last_event: Optional[datetime] = None
    user_prompts: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    files_edited: set[str] = field(default_factory=set)

    def apply_meta(self, meta: SessionMeta) -> None:
        if meta.cwd:
            self.cwd = meta.cwd
        if meta.branch:
            self.branch = meta.branch
        if meta.session_id:
            self.session_id = meta.session_id

    def note_event_time(self, event_time: datetime) -> None:
        if self.first_event is None or event_time < self.first_event:
            self.first_event = event_time
        if self.last_event is None or event_time > self.last_event:
            self.last_event = event_time


@dataclass
class DigestCollection:
    date_buckets: dict[date, dict[str, SessionDigest]] = field(default_factory=dict)
    oldest_event_date: Optional[date] = None

    def note_event_date(self, event_date: date) -> None:
        if self.oldest_event_date is None or event_date < self.oldest_event_date:
            self.oldest_event_date = event_date


def iter_rollout_files(
    sessions_dir: Path,
    archived_dir: Path,
) -> Iterable[Path]:
    yield from sessions_dir.glob("*/*/*/*.jsonl")
    yield from archived_dir.glob("rollout-*.jsonl")


def parse_event_time(record: dict) -> Optional[datetime]:
    raw_timestamp = record.get("timestamp")
    if not isinstance(raw_timestamp, str):
        return None
    try:
        event_time = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    return event_time.astimezone(config.LOCAL_ZONE)


def truncate(value: str, limit: int) -> str:
    single_line = " ".join(value.split())
    if len(single_line) <= limit:
        return single_line
    return single_line[: limit - 3].rstrip() + "..."


def should_skip_user_message(message: str) -> bool:
    return any(message.startswith(prefix) for prefix in config.INJECTED_MESSAGE_PREFIXES)


def update_meta(record: dict, meta: SessionMeta) -> bool:
    if record.get("type") != "session_meta":
        return False
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False

    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        meta.cwd = cwd

    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id:
        meta.session_id = session_id

    git = payload.get("git")
    if isinstance(git, dict):
        branch = git.get("branch")
        if isinstance(branch, str) and branch:
            meta.branch = branch

    return True


def decode_arguments(payload: dict):
    arguments = payload.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        return None
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


def extract_command(payload: dict) -> Optional[str]:
    decoded = decode_arguments(payload)
    if not isinstance(decoded, dict):
        return None
    command = decoded.get("cmd")
    if not isinstance(command, str) or not command:
        return None
    return truncate(command, config.COMMAND_CHAR_LIMIT)


def extract_patch_text(payload: dict) -> str:
    decoded = decode_arguments(payload)
    if isinstance(decoded, str):
        return decoded
    if isinstance(decoded, dict):
        parts = [value for value in decoded.values() if isinstance(value, str)]
        return "\n".join(parts)
    return ""


def record_event_details(record: dict, session_digest: SessionDigest) -> None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return

    record_type = record.get("type")
    payload_type = payload.get("type")

    if record_type == "event_msg" and payload_type == "user_message":
        message = payload.get("message")
        if isinstance(message, str) and message and not should_skip_user_message(message):
            session_digest.user_prompts.append(truncate(message, config.PROMPT_CHAR_LIMIT))
        return

    if record_type != "response_item" or payload_type != "function_call":
        return

    name = payload.get("name")
    if not isinstance(name, str):
        return

    if name.endswith("exec_command"):
        command = extract_command(payload)
        if command:
            session_digest.commands.append(command)
        return

    if name.endswith("apply_patch"):
        patch_text = extract_patch_text(payload)
        for match in PATCH_FILE_RE.finditer(patch_text):
            session_digest.files_edited.add(match.group(1).strip())


def ensure_digest(
    collection: DigestCollection,
    day: date,
    rollout_file: Path,
    meta: SessionMeta,
) -> SessionDigest:
    sessions_for_date = collection.date_buckets.setdefault(day, {})
    key = str(rollout_file)
    session_digest = sessions_for_date.get(key)
    if session_digest is None:
        session_digest = SessionDigest(source_file=rollout_file, session_id=rollout_file.stem)
        sessions_for_date[key] = session_digest
    session_digest.apply_meta(meta)
    return session_digest


def apply_meta_to_existing_digests(
    collection: DigestCollection,
    rollout_file: Path,
    meta: SessionMeta,
) -> None:
    key = str(rollout_file)
    for sessions_for_date in collection.date_buckets.values():
        session_digest = sessions_for_date.get(key)
        if session_digest is not None:
            session_digest.apply_meta(meta)


def parse_rollout_file(
    rollout_file: Path,
    target_dates: set[date],
    collection: DigestCollection,
) -> None:
    meta = SessionMeta(session_id=rollout_file.stem)

    try:
        with rollout_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue

                if update_meta(record, meta):
                    apply_meta_to_existing_digests(collection, rollout_file, meta)

                event_time = parse_event_time(record)
                if event_time is None:
                    continue

                day = event_time.date()
                collection.note_event_date(day)
                if day not in target_dates:
                    continue

                session_digest = ensure_digest(collection, day, rollout_file, meta)
                session_digest.note_event_time(event_time)
                record_event_details(record, session_digest)
    except OSError:
        return


def collect_digests(
    target_days: list[date],
    sessions_dir: Path = config.SESSIONS_DIR,
    archived_dir: Path = config.ARCHIVED_SESSIONS_DIR,
) -> DigestCollection:
    collection = DigestCollection()
    if not target_days:
        return collection

    target_set = set(target_days)
    for rollout_file in iter_rollout_files(sessions_dir, archived_dir):
        parse_rollout_file(rollout_file, target_set, collection)
    return collection


def repo_label(session_digest: SessionDigest) -> str:
    if session_digest.cwd:
        return Path(session_digest.cwd).name or session_digest.cwd
    return session_digest.session_id


def render_session_digest(session_digest: SessionDigest) -> str:
    heading = repo_label(session_digest)
    lines = [f"## Session: {heading}"]
    if session_digest.cwd:
        lines.append(f"Workspace: {session_digest.cwd}")
    if session_digest.branch:
        lines.append(f"Branch: {session_digest.branch}")
    if session_digest.first_event and session_digest.last_event:
        lines.append(
            "Time: "
            f"{session_digest.first_event.strftime('%H:%M:%S')} - "
            f"{session_digest.last_event.strftime('%H:%M:%S')}"
        )
    if session_digest.user_prompts:
        lines.append("User prompts:")
        lines.extend(f"- {prompt}" for prompt in session_digest.user_prompts)
    if session_digest.commands:
        lines.append("Commands:")
        lines.extend(f"- {command}" for command in session_digest.commands)
    if session_digest.files_edited:
        lines.append("Files edited:")
        lines.extend(f"- {path}" for path in sorted(session_digest.files_edited))
    if not session_digest.user_prompts and not session_digest.commands and not session_digest.files_edited:
        lines.append("No user prompts, commands, or file edits captured for this session.")

    return "\n".join(lines)


def build_digest(
    day: date,
    sessions: list[SessionDigest],
    char_cap: int = config.DIGEST_CHAR_LIMIT,
) -> str:
    sorted_sessions = sorted(
        sessions,
        key=lambda item: item.first_event or datetime.min.replace(tzinfo=config.LOCAL_ZONE),
    )
    rendered_sessions = [render_session_digest(session) for session in sorted_sessions]

    digest_text = "\n".join(
        [
            f"# Digest for {day.isoformat()}",
            "",
            f"Sessions with activity: {len(rendered_sessions)}",
            "",
        ]
    )
    included = 0

    for rendered in rendered_sessions:
        candidate = digest_text + rendered + "\n\n"
        if included > 0 and len(candidate) > char_cap:
            break
        if included == 0 and len(candidate) > char_cap:
            digest_text = candidate[:char_cap].rstrip() + "\n"
            included = 1
            break
        digest_text = candidate
        included += 1

    total = len(rendered_sessions)
    if included < total:
        digest_text += f"\n[digest truncated: {included} of {total} sessions included]\n"

    return digest_text.rstrip()
