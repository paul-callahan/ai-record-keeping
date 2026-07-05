"""Entry point: locking, logging, date selection, and the per-day loop."""

import fcntl
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from claude_daily_summary import config
from claude_daily_summary.digest import build_digest, collect_digests
from claude_daily_summary.summarizer import (
    Outcome,
    resolve_claude_binary,
    resolve_oauth_token,
    summarize_date,
)

log = logging.getLogger("claude_daily_summary")

NO_ACTIVITY_TEMPLATE = """# Claude Code Daily Summary - {date}

No Claude Code activity found.
"""

PRUNED_TEMPLATE = """# Claude Code Daily Summary - {date}

No transcript data available for this date. It predates the oldest surviving
transcript, so the session was either inactive or already pruned.
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
        log.error("BACKFILL_DAYS must be a positive integer, got: %r", raw)
        raise SystemExit(2)
    return days


def setup_logging() -> None:
    """Log to the single file; echo to the terminal on interactive runs."""
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.propagate = False

    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)

    if sys.stdout.isatty():
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        log.addHandler(stream_handler)


def _summary_path(day):
    return config.SUMMARIES_DIR / f"daily-summary-{day.isoformat()}.md"


def atomic_write(path: Path, content: str) -> None:
    """Write via a temp file and rename, so a kill mid-write leaves no partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def backfill(ordered, digests, horizon, summarize) -> int:
    """Fill missing days oldest-first; return the number of failed days.

    Invariant: no holes behind the frontier. A day whose model call ran but
    produced unusable output gets a failure placeholder (marked done, delete to
    retry). A day whose call failed systemically writes nothing and aborts the
    run, so it retries next time rather than being poisoned. Reaching the
    per-run call cap also stops the loop, leaving a contiguous recent suffix.
    """
    failures = 0
    calls_made = 0
    for index, day in enumerate(ordered):
        summary_file = _summary_path(day)
        sessions = digests.get(day)
        if not sessions:
            if horizon is None or day < horizon:
                atomic_write(summary_file, PRUNED_TEMPLATE.format(date=day.isoformat()) + FREE_FOOTER)
                log.info("%s: before data horizon (%s), wrote pruned placeholder",
                         day, horizon)
            else:
                atomic_write(summary_file, NO_ACTIVITY_TEMPLATE.format(date=day.isoformat()) + FREE_FOOTER)
                log.info("%s: no activity, wrote placeholder", day)
            continue
        if calls_made >= config.MAX_CALLS_PER_RUN:
            log.info("call cap (%d) reached, stopping; %d day(s) left for next run",
                     config.MAX_CALLS_PER_RUN, len(ordered) - index)
            break
        calls_made += 1
        started = time.monotonic()
        result = summarize(day)
        elapsed = time.monotonic() - started
        if result.outcome is Outcome.SYSTEMIC_FAILURE:
            log.error("%s: systemic failure after %.0fs; aborting run, will retry next run",
                      day, elapsed)
            failures += 1
            break
        if result.outcome is Outcome.CONTENT_FAILURE:
            atomic_write(
                summary_file,
                FAILED_TEMPLATE.format(date=day.isoformat()) + (result.footer or FAILED_FOOTER),
            )
            log.error("%s: content failure after %.0fs; wrote failure placeholder "
                      "(delete it to retry)", day, elapsed)
            failures += 1
            continue
        atomic_write(summary_file, result.markdown)
        log.info("%s: wrote summary from %d session(s) in %.0fs",
                 day, len(sessions), elapsed)
    return failures


def main() -> int:
    config.SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging()

    backfill_days = read_backfill_days()
    claude_bin = resolve_claude_binary()
    token = resolve_oauth_token()

    lock = open(config.LOCK_FILE, "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("Another claude-daily-summary run holds the lock, exiting.")
        return 0

    today = datetime.now(config.LOCAL_TZ).date()
    target_dates = [today - timedelta(days=n) for n in range(1, backfill_days + 1)]
    missing = [day for day in target_dates if not _summary_path(day).exists()]
    log.info("run start, %d of %d days missing", len(missing), backfill_days)
    if not missing:
        return 0

    digests, horizon = collect_digests(set(missing))

    def summarize(day):
        return summarize_date(claude_bin, day, build_digest(digests[day]), token)

    failures = backfill(sorted(missing), digests, horizon, summarize)
    return 1 if failures else 0
