"""Entry point: locking, logging, date selection, and the per-day loop."""

import fcntl
import logging
import os
import sys
import time
from datetime import datetime, timedelta

from claude_daily_summary import config
from claude_daily_summary.digest import build_digest, collect_digests
from claude_daily_summary.summarizer import (
    resolve_claude_binary,
    resolve_oauth_token,
    summarize_date,
)

log = logging.getLogger(__name__)

NO_ACTIVITY_TEMPLATE = """# Claude Code Daily Summary - {date}

No Claude Code activity found.
"""

PRUNED_TEMPLATE = """# Claude Code Daily Summary - {date}

No transcript data available; transcripts from this date were already pruned
when this backfill ran.
"""

FAILED_TEMPLATE = """# Claude Code Daily Summary - {date}

Summary generation failed for this date. Delete this file to retry on the next run.
"""

FREE_FOOTER = "\n---\n_Generation cost: 0 tokens (no model call)._\n"
FAILED_FOOTER = "\n---\n_Generation failed; token cost not recorded._\n"


def read_backfill_days() -> int:
    raw = os.environ.get("BACKFILL_DAYS", "7")
    try:
        days = int(raw)
    except ValueError:
        days = 0
    if days <= 0:
        sys.exit(f"BACKFILL_DAYS must be a positive integer, got: {raw!r}")
    return days


def setup_logging() -> None:
    """Log to the single file; echo to the terminal on interactive runs."""
    handlers: list[logging.Handler] = [logging.FileHandler(config.LOG_FILE)]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def _summary_path(day):
    return config.SUMMARIES_DIR / f"daily-summary-{day.isoformat()}.md"


def backfill(ordered, digests, horizon, summarize) -> int:
    """Fill missing days oldest-first; return the number of failed model calls.

    Invariant: no holes behind the frontier. Every day processed gets a file, a
    summary, a placeholder, or a failure marker, so a failed model call never
    leaves a gap. Once the per-run call cap is reached the loop stops, so the
    only unwritten days are a contiguous recent suffix that the next run fills.
    """
    failures = 0
    calls_made = 0
    for index, day in enumerate(ordered):
        summary_file = _summary_path(day)
        sessions = digests.get(day)
        if not sessions:
            if horizon is None or day < horizon:
                summary_file.write_text(
                    PRUNED_TEMPLATE.format(date=day.isoformat()) + FREE_FOOTER
                )
                log.info("%s: before data horizon (%s), wrote pruned placeholder",
                         day, horizon)
            else:
                summary_file.write_text(
                    NO_ACTIVITY_TEMPLATE.format(date=day.isoformat()) + FREE_FOOTER
                )
                log.info("%s: no activity, wrote placeholder", day)
            continue
        if calls_made >= config.MAX_CALLS_PER_RUN:
            log.info("call cap (%d) reached, stopping; %d day(s) left for next run",
                     config.MAX_CALLS_PER_RUN, len(ordered) - index)
            break
        calls_made += 1
        started = time.monotonic()
        summary = summarize(day)
        elapsed = time.monotonic() - started
        if summary is None:
            summary_file.write_text(
                FAILED_TEMPLATE.format(date=day.isoformat()) + FAILED_FOOTER
            )
            log.error("%s: summary failed after %.0fs; wrote failure placeholder "
                      "(delete it to retry)", day, elapsed)
            failures += 1
            continue
        summary_file.write_text(summary)
        log.info("%s: wrote summary from %d session(s) in %.0fs",
                 day, len(sessions), elapsed)
    return failures


def main() -> int:
    backfill_days = read_backfill_days()
    claude_bin = resolve_claude_binary()
    token = resolve_oauth_token()

    config.SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging()

    lock = open(config.LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("Another claude-daily-summary run holds the lock, exiting.")
        return 0

    today = datetime.now(config.LOCAL_TZ).date()
    target_dates = [today - timedelta(days=n) for n in range(1, backfill_days + 1)]
    missing = [
        day for day in target_dates
        if not _summary_path(day).exists()
    ]
    log.info("run start, %d of %d days missing", len(missing), backfill_days)
    if not missing:
        return 0

    digests, horizon = collect_digests(set(missing))

    def summarize(day):
        return summarize_date(claude_bin, day, build_digest(digests[day]), token)

    failures = backfill(sorted(missing), digests, horizon, summarize)
    return 1 if failures else 0
