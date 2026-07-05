"""Invoke headless Claude to turn a day's digest into a summary file."""

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from claude_daily_summary import config

log = logging.getLogger(__name__)

SUMMARY_PROMPT_TEMPLATE = """You are given a digest of Claude Code coding sessions for {date} ({tz}).
This is a work diary used for performance reviews and resume writing.
Write the complete contents of a daily summary markdown file. Output ONLY the raw markdown,
starting with the line:
# Claude Code Daily Summary - {date}

Structure:

## Summary
No more than 3 sentences on what was done that day.

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
(commits made outside Claude Code sessions are not visible in the digest).

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

DIGEST:
{digest}"""


def resolve_claude_binary() -> str:
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    sys.exit("claude binary not found on PATH or at ~/.local/bin/claude")


def resolve_oauth_token(token_file: Path = config.TOKEN_FILE) -> str | None:
    """Return the OAuth token for the claude subprocess, or None.

    An already-exported CLAUDE_CODE_OAUTH_TOKEN wins over the token file.
    The token file must not be readable by group or others.
    """
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    if not token_file.is_file():
        return None
    mode = token_file.stat().st_mode
    if mode & 0o077:
        sys.exit(
            f"{token_file} is readable by group/others "
            f"(mode {oct(mode & 0o777)}); run: chmod 600 {token_file}"
        )
    token = token_file.read_text().strip()
    return token or None


def token_footer(usage: dict | None) -> str:
    u = usage or {}
    input_total = (
        (u.get("input_tokens") or 0)
        + (u.get("cache_creation_input_tokens") or 0)
        + (u.get("cache_read_input_tokens") or 0)
    )
    output = u.get("output_tokens") or 0
    total = input_total + output
    return (
        f"---\n_Generation cost: {total:,} tokens "
        f"({input_total:,} input + {output:,} output)._"
    )


def summarize_date(
    claude_bin: str, day: date, digest: str, token: str | None
) -> str | None:
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        date=day.isoformat(), digest=digest, tz=config.LOCAL_TZ.key
    )
    env = os.environ.copy()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    # The prompt goes in on stdin, not as an argv element: --tools is variadic
    # and would otherwise swallow a trailing prompt argument.
    cmd = [
        claude_bin,
        "-p",
        "--model", config.MODEL,
        "--no-session-persistence",
        "--tools", "",
        "--max-budget-usd", config.MAX_BUDGET_USD,
        "--output-format", "json",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=config.CLAUDE_TIMEOUT_SECONDS,
            cwd=Path.home(),
            env=env,
        )
    except subprocess.TimeoutExpired:
        log.error("%s: claude timed out after %ds", day, config.CLAUDE_TIMEOUT_SECONDS)
        return None
    if result.stderr.strip():
        log.warning("%s: claude stderr: %s", day, result.stderr.strip())
    if result.returncode != 0:
        log.error("%s: claude exited with code %d", day, result.returncode)
        if result.stdout.strip():
            log.error("%s: claude stdout: %s", day, result.stdout.strip())
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        log.error("%s: could not parse claude JSON output", day)
        log.error("%s: claude stdout: %s", day, result.stdout.strip()[:2000])
        return None
    if data.get("is_error") or data.get("subtype") != "success":
        log.error("%s: claude reported error: subtype=%s errors=%s",
                  day, data.get("subtype"), data.get("errors"))
        return None
    markdown = (data.get("result") or "").strip()
    if not markdown.startswith("#"):
        log.error("%s: claude output is empty or not markdown, skipping", day)
        if markdown:
            log.error("%s: claude result: %s", day, markdown)
        return None
    return f"{markdown}\n\n{token_footer(data.get('usage'))}\n"
