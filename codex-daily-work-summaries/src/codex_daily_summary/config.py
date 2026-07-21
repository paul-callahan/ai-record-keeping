import os
from pathlib import Path
from zoneinfo import ZoneInfo


HOME = Path.home()
TIME_ZONE_NAME = os.environ.get("TZ", "America/Los_Angeles")
LOCAL_ZONE = ZoneInfo(TIME_ZONE_NAME)
APP_BUNDLE_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")

MODEL = os.environ.get("CODEX_DAILY_SUMMARY_MODEL", "gpt-5.3-codex-spark")
MAX_CALLS_PER_RUN = 3
DIGEST_CHAR_LIMIT = 100_000
PROMPT_CHAR_LIMIT = 500
COMMAND_CHAR_LIMIT = 200
CODEX_TIMEOUT_SECONDS = 900
ACTIVE_TIME_GAP_MINUTES = 15

SUMMARY_DIR = HOME / "Documents" / "codex-work-summaries"
LOG_DIR = HOME / "Library" / "Logs"
LOG_FILE = LOG_DIR / "codex-daily-summary.log"
LOCK_FILE = SUMMARY_DIR / ".codex-daily-summary.lock"
SESSIONS_DIR = HOME / ".codex" / "sessions"
ARCHIVED_SESSIONS_DIR = HOME / ".codex" / "archived_sessions"

INJECTED_MESSAGE_PREFIXES = (
    "\n# Files mentioned by the user:",
    "\n# Selected text:",
    "The following is the Codex agent history",
)
