import fcntl
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from . import config
from .digest import build_digest, collect_digests
from .summarizer import (
    no_activity_summary,
    no_session_data_summary,
    summarize_with_codex,
)


def parse_backfill_days() -> int:
    raw_value = os.environ.get("BACKFILL_DAYS", "3")
    try:
        backfill_days = int(raw_value)
    except ValueError:
        print(
            f"codex-daily-summary: BACKFILL_DAYS must be a positive integer, got {raw_value!r}",
            file=sys.stderr,
        )
        sys.exit(2)

    if backfill_days <= 0:
        print(
            f"codex-daily-summary: BACKFILL_DAYS must be a positive integer, got {raw_value!r}",
            file=sys.stderr,
        )
        sys.exit(2)

    return backfill_days


def resolve_codex() -> Optional[str]:
    codex = shutil.which("codex")
    if codex:
        return codex
    if config.APP_BUNDLE_CODEX.is_file() and os.access(config.APP_BUNDLE_CODEX, os.X_OK):
        return str(config.APP_BUNDLE_CODEX)
    return None


def configure_logging(log_file: Path = config.LOG_FILE) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("codex_daily_summary")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if sys.stdout.isatty():
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger


def target_dates(backfill_days: int, now: Optional[datetime] = None) -> list[date]:
    current = now.astimezone(config.LOCAL_ZONE) if now else datetime.now(config.LOCAL_ZONE)
    today = current.date()
    return [today - timedelta(days=offset) for offset in range(backfill_days, 0, -1)]


def summary_path(day: date, summaries_dir: Path = config.SUMMARY_DIR) -> Path:
    return summaries_dir / f"daily-summary-{day.isoformat()}.md"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def date_has_no_session_data(day: date, oldest_event_date: Optional[date]) -> bool:
    return oldest_event_date is None or day < oldest_event_date


def process_missing_dates(codex: str, missing_dates: list[date], logger: logging.Logger) -> int:
    collection = collect_digests(missing_dates)
    failed = False
    calls_made = 0
    deferred = 0

    for index, day in enumerate(missing_dates):
        started = time.monotonic()
        output_path = summary_path(day)
        sessions = list(collection.date_buckets.get(day, {}).values())

        if date_has_no_session_data(day, collection.oldest_event_date):
            atomic_write(output_path, no_session_data_summary(day))
            logger.info(
                "%s: wrote no-session-data placeholder in %ss",
                day.isoformat(),
                round(time.monotonic() - started),
            )
            continue

        if not sessions:
            atomic_write(output_path, no_activity_summary(day))
            logger.info(
                "%s: wrote no-activity summary in %ss",
                day.isoformat(),
                round(time.monotonic() - started),
            )
            continue

        if calls_made >= config.MAX_CALLS_PER_RUN:
            deferred = len(missing_dates) - index
            break

        calls_made += 1
        digest = build_digest(day, sessions)
        result = summarize_with_codex(codex, config.HOME, day, digest, logger)
        if result.failed or result.markdown is None:
            logger.error(
                "%s: summary failed after %ss",
                day.isoformat(),
                round(time.monotonic() - started),
            )
            failed = True
            continue
        atomic_write(output_path, result.markdown)
        logger.info(
            "%s: wrote summary from %s session(s) in %ss",
            day.isoformat(),
            len(sessions),
            round(time.monotonic() - started),
        )

    if deferred:
        logger.info("deferred %s day(s) after reaching MAX_CALLS_PER_RUN", deferred)

    return 1 if failed else 0


def main() -> int:
    config.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    logger = configure_logging()

    with config.LOCK_FILE.open("a") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("another run is already in progress")
            return 0

        backfill_days = parse_backfill_days()
        dates = target_dates(backfill_days)
        missing_dates = [day for day in dates if not summary_path(day).exists()]
        if not missing_dates:
            logger.info("no missing summary files")
            return 0

        codex = resolve_codex()
        if codex is None:
            logger.error(
                "codex-daily-summary: codex CLI was not found on PATH or at "
                "%s",
                config.APP_BUNDLE_CODEX,
            )
            return 127

        return process_missing_dates(codex, missing_dates, logger)
