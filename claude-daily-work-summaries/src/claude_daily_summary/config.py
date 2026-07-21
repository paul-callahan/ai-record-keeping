"""Tunable constants and filesystem locations."""

import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MODEL = "sonnet"
MAX_BUDGET_USD = "2.00"
MAX_CALLS_PER_RUN = 3
CLAUDE_TIMEOUT_SECONDS = 900
PROMPT_TRUNCATE_CHARS = 500
COMMAND_TRUNCATE_CHARS = 200
DIGEST_CHAR_CAP = 100_000
IDLE_THRESHOLD_MINUTES = 15

PROJECTS_DIR = Path.home() / ".claude" / "projects"
SUMMARIES_DIR = Path.home() / "Documents" / "claude-work-summaries"
LOGS_DIR = Path.home() / "Library" / "Logs"
LOCK_FILE = SUMMARIES_DIR / ".claude-daily-summary.lock"
TOKEN_FILE = Path.home() / ".config" / "claude-daily-summary" / "token"
LOG_FILE = LOGS_DIR / "claude-daily-summary.log"

_local_tz_cache: ZoneInfo | None = None


def _local_timezone() -> ZoneInfo:
    """Resolve the local timezone: TZ env var first, then the system setting."""
    tz_name = os.environ.get("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            sys.exit(f"TZ is set to unknown timezone: {tz_name!r}")
    try:
        # macOS: /etc/localtime is a symlink into the zoneinfo database
        link = os.readlink("/etc/localtime")
        return ZoneInfo(link.split("zoneinfo/")[-1])
    except (OSError, ZoneInfoNotFoundError):
        sys.exit("Could not determine local timezone; set the TZ environment variable")


def __getattr__(name: str):
    # LOCAL_TZ is resolved lazily and cached so that importing this module can
    # never exit the process; timezone resolution happens on first real use.
    if name == "LOCAL_TZ":
        global _local_tz_cache
        if _local_tz_cache is None:
            _local_tz_cache = _local_timezone()
        return _local_tz_cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
