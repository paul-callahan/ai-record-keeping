# claude-daily-summary

Generates a daily work-diary markdown file from Claude Code session transcripts.
Intended as a record for performance reviews and resume writing.

A launchd agent runs the tool every 5 hours. Each run parses the transcripts under
`~/.claude/projects/` into a compact per-day digest, then calls headless Claude
(`claude -p`, no tools) once per missing day to write
`~/Documents/claude-work-summaries/daily-summary-YYYY-MM-DD.md`.

## Design

- The current day is never summarized; the window is yesterday back through
  `BACKFILL_DAYS`. Existing files are never regenerated, so late work is not lost to an
  already-written file.
- Python parses the transcripts and writes all files; the model only turns a bounded
  digest into prose. Days with no activity cost no model call.
- At most `MAX_CALLS_PER_RUN` model calls per run (see `config.py`); older missing days
  are processed first and the rest are deferred to the next run.
- Missing days older than the oldest surviving transcript get an explicit "no transcript
  data available" placeholder rather than a false "no activity" claim.
- Every file ends with a footer recording the tokens spent generating it.
- Calendar days use your local timezone: the `TZ` environment variable if set, otherwise
  the system timezone (macOS `/etc/localtime`).

## Setup

Authentication for headless runs uses a long-lived OAuth token:

```sh
claude setup-token
mkdir -p ~/.config/claude-daily-summary
printf '%s' '<token>' > ~/.config/claude-daily-summary/token
chmod 600 ~/.config/claude-daily-summary/token
```

An exported `CLAUDE_CODE_OAUTH_TOKEN` overrides the token file. The tool aborts if the
token file is readable by group or others.

Install the tool and the launch agent:

```sh
./install.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.$USER.claude-daily-summary.plist
```

`install.sh` installs the CLI with `uv tool install` (as
`~/.local/bin/claude-daily-summary`) and renders the plist template
(`com.{USER}.claude-daily-summary.plist`) with your username and home directory into
`~/Library/LaunchAgents/com.<user>.claude-daily-summary.plist`; it does not start
anything. `uninstall.sh` reverses both but preserves generated summaries, logs, and the
token file.

## Usage

Manual run (defaults to a 7-day window; the launch agent uses 45):

```sh
BACKFILL_DAYS=7 claude-daily-summary
```

All runs write timestamped lines to `~/Library/Logs/claude-daily-summary.log`; manual
runs from a terminal also print the same lines live.

To regenerate a day, delete its file in `~/Documents/claude-work-summaries/` and re-run.

Tunables (model, per-call budget, call cap, digest size, paths) are constants in
`src/claude_daily_summary/config.py`.

## Development

```sh
uv run pytest
```
