import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from . import config
from .activity_time import format_active_duration
from .digest import TokenUsage, format_token_usage


PROMPT_TEMPLATE = """You are given a digest of Codex coding sessions for {date} ({time_zone}).
This is a work diary used for performance reviews and resume writing.
Write the complete contents of a daily summary markdown file. Output ONLY the raw markdown,
starting with the line:
# Codex Daily Summary - {date}

Structure:

## Summary
No more than 3 sentences on what was done that day.

## Estimated Codex Activity Time
Report the estimated active time exactly as provided in the digest, including the
inactivity cutoff.

## Estimated Codex Token Usage
Report the estimated token usage exactly as provided in the digest.

## Repos / Workspaces
Bulleted list of the repos worked in that day, if any.

Then one section per repo, most significant first:

## <repo name> (branch when relevant)
### Major Discussions
Significant discussions, investigations, and the decisions reached. Bold topic line, then
short bullets with the findings and the decision. Skip minor back-and-forth.
### Coding Work
Overview of the coding work and its outcomes, grouped by feature or change, not by file.
You may name a key module with a one-phrase purpose when it anchors the work; never
inventory the files touched.
### Git Commits
List the commits created in these sessions. If none are recorded, write "None recorded"
(commits made outside Codex sessions are not visible in the digest).

## Standalone Chats
Q&A or discussions unrelated to the repo work, regardless of which directory the session
ran in. Include only chats with substance: a decision, a learning, or a solution worth
remembering. Omit the section if there were none.

## Caveats
One or two lines, only if the digest notes truncation or transcripts appear incomplete.

Rules:
- Weight space by significance: major work gets detail, minor items get one clause or
  nothing at all.
- If work was implemented in the session, it must appear under Coding Work even if
  authored by another agent under review.
- No long unbroken paragraphs; use bold topic lines and short bullets.
- Do not repeat the same information in more than one section.
- Do not list verification or test commands.
- Omit any section or subsection that would be empty.
- Do not narrate session friction or tooling mishaps unless they cost significant time.
- Do not invent work not supported by the digest. No commentary outside the file content.
- Treat estimated active time as approximate interaction time, not verified attention time.
- Treat estimated token usage as an approximate local event total, not a billing statement.

DIGEST:
{digest}
"""


@dataclass
class SummaryResult:
    markdown: Optional[str]
    failed: bool = False
    failure_reason: Optional[str] = None


def render_generation_footer(
    token_count: Optional[int],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> str:
    if token_count is None:
        return "_Generation cost: unknown._"
    if input_tokens is not None and output_tokens is not None:
        return (
            f"_Generation cost: {token_count:,} tokens "
            f"({input_tokens:,} input + {output_tokens:,} output)._"
        )
    return f"_Generation cost: {token_count:,} tokens._"


def zero_cost_footer() -> str:
    return "_Generation cost: 0 tokens (no model call)._"


def with_footer(markdown: str, footer: str) -> str:
    return markdown.rstrip() + "\n\n---\n" + footer + "\n"


def estimated_time_line(active_minutes: int) -> str:
    return (
        f"Estimated Codex activity time: {format_active_duration(active_minutes)} "
        f"using a {config.ACTIVE_TIME_GAP_MINUTES}-minute inactivity cutoff."
    )


def estimated_token_line(token_usage: TokenUsage) -> str:
    return f"Estimated Codex token usage: {format_token_usage(token_usage)}."


def no_activity_summary(day: date) -> str:
    body = (
        f"# Codex Daily Summary - {day.isoformat()}\n\n"
        "No Codex activity found.\n\n"
        f"{estimated_time_line(0)}\n\n"
        f"{estimated_token_line(TokenUsage())}"
    )
    return with_footer(body, zero_cost_footer())


def no_session_data_summary(day: date) -> str:
    body = (
        f"# Codex Daily Summary - {day.isoformat()}\n\n"
        "No Codex session data is available for this date. Sessions may have been pruned or absent.\n\n"
        "Estimated Codex activity time: unavailable because no session data was found.\n\n"
        "Estimated Codex token usage: unavailable because no session data was found."
    )
    return with_footer(body, zero_cost_footer())


def generation_failed_summary(day: date, reason: str, active_minutes: int, token_usage: TokenUsage) -> str:
    body = (
        f"# Codex Daily Summary - {day.isoformat()}\n\n"
        "Summary generation failed. Delete this file and rerun `codex-daily-summary` to retry.\n\n"
        f"{estimated_time_line(active_minutes)}\n\n"
        f"{estimated_token_line(token_usage)}\n\n"
        f"Failure: {reason}"
    )
    return with_footer(body, render_generation_footer(None, None, None))


def maybe_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def usage_from_mapping(value: dict):
    token_count = maybe_int(value.get("total_tokens"))
    if token_count is None:
        return None

    input_tokens = None
    output_tokens = None
    for key in ("input_tokens", "prompt_tokens"):
        input_tokens = maybe_int(value.get(key))
        if input_tokens is not None:
            break
    for key in ("output_tokens", "completion_tokens"):
        output_tokens = maybe_int(value.get(key))
        if output_tokens is not None:
            break

    return token_count, input_tokens, output_tokens


def codex_token_count_usage(value: dict):
    if value.get("type") == "token_count":
        info = value.get("info")
        if isinstance(info, dict):
            usage = info.get("total_token_usage")
            if isinstance(usage, dict):
                found = usage_from_mapping(usage)
                if found is not None:
                    return found

    payload = value.get("payload")
    if isinstance(payload, dict):
        return codex_token_count_usage(payload)

    return None


def find_token_usage(value):
    if isinstance(value, dict):
        found = codex_token_count_usage(value)
        if found is not None:
            return found

        found = usage_from_mapping(value)
        if found is not None:
            return found

        for nested in value.values():
            found = find_token_usage(nested)
            if found is not None:
                return found

    if isinstance(value, list):
        for nested in value:
            found = find_token_usage(nested)
            if found is not None:
                return found

    return None


def parse_token_usage(stdout_text: str):
    latest = None
    for line in stdout_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = find_token_usage(event)
        if found is not None:
            latest = found
    return latest


def log_subprocess_output(
    logger: logging.Logger,
    day: date,
    stdout_text: str,
    stderr_text: str,
    level: int,
) -> None:
    if stdout_text:
        logger.log(level, "%s: subprocess stdout:\n%s", day.isoformat(), stdout_text.rstrip())
    if stderr_text:
        logger.log(level, "%s: subprocess stderr:\n%s", day.isoformat(), stderr_text.rstrip())


def summarize_with_codex(
    codex: str,
    home: Path,
    day: date,
    digest_text: str,
    logger: logging.Logger,
) -> SummaryResult:
    prompt = PROMPT_TEMPLATE.format(
        date=day.isoformat(),
        time_zone=config.TIME_ZONE_NAME,
        digest=digest_text,
    )
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        output_path = Path(handle.name)

    args = [
        codex,
        "exec",
        "--ephemeral",
        "--json",
        "-s",
        "read-only",
        "--cd",
        str(home),
        "--skip-git-repo-check",
        "-o",
        str(output_path),
    ]
    if config.MODEL:
        args.extend(["-m", config.MODEL])
    args.append(prompt)

    try:
        completed = subprocess.run(
            args,
            timeout=config.CODEX_TIMEOUT_SECONDS,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        usage = parse_token_usage(completed.stdout)
        footer = render_generation_footer(*usage) if usage else render_generation_footer(None, None, None)

        if completed.stderr and completed.returncode == 0:
            log_subprocess_output(logger, day, "", completed.stderr, logging.WARNING)

        if completed.returncode != 0:
            logger.error("%s: codex failed with exit code %s", day.isoformat(), completed.returncode)
            log_subprocess_output(logger, day, completed.stdout, completed.stderr, logging.ERROR)
            return SummaryResult(
                markdown=None,
                failed=True,
                failure_reason=f"codex exited with status {completed.returncode}",
            )

        try:
            output = output_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("%s: failed to read Codex output: %s", day.isoformat(), exc)
            return SummaryResult(
                markdown=None,
                failed=True,
                failure_reason="output file could not be read",
            )

        output = output.strip()
        if not output or not output.startswith("#"):
            logger.error("%s: Codex output was empty or malformed", day.isoformat())
            log_subprocess_output(logger, day, completed.stdout, completed.stderr, logging.ERROR)
            return SummaryResult(
                markdown=None,
                failed=True,
                failure_reason="model output was empty or malformed",
            )

        return SummaryResult(markdown=with_footer(output, footer))
    except subprocess.TimeoutExpired as exc:
        logger.error("%s: codex timed out", day.isoformat())
        log_subprocess_output(logger, day, exc.stdout or "", exc.stderr or "", logging.ERROR)
        return SummaryResult(markdown=None, failed=True, failure_reason="codex timed out")
    finally:
        try:
            output_path.unlink()
        except OSError:
            pass
