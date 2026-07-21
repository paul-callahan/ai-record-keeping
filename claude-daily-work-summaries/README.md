# claude-daily-summary

Writes one markdown file per day summarizing what you did in Claude Code, built from the
session transcripts already on disk. Useful at review time, when you need to remember
what you actually worked on three months ago.

A launchd agent runs it every 5 hours. Each run scans `~/.claude/projects/`, builds a
compact digest for each day that has no summary yet, and asks headless Claude
(`claude -p`, no tools) to write:

```text
~/Documents/claude-work-summaries/daily-summary-YYYY-MM-DD.md
```

## What a summary contains

A short overview of the day, then two measured sections: estimated activity time (event
timestamps merged into work blocks, gaps over 15 minutes counted as idle) and the day's
token usage (consumed = fresh input + output, plus total processed including cache
reads). After that, one section per repo covering major discussions and decisions,
coding work, and commits, followed by any standalone chats worth keeping. The end of the
file records what the summary itself cost to generate.

## Behavior

Today is never summarized. The window runs from yesterday back through `BACKFILL_DAYS`,
and existing files are never touched, so to regenerate a day, delete its file and re-run.

Each run makes at most 3 model calls (`MAX_CALLS_PER_RUN` in `config.py`), oldest day
first, then stops. A large backlog fills in over several runs instead of burning through
quota in one shot. Days with no activity are written directly by Python at no model
cost. Days older than the oldest surviving transcript get a "no transcript data" file,
since Claude Code prunes old transcripts and those days can no longer be summarized.

If Claude returns unusable output for a day, a failure marker file is written; delete it
to retry. If the call itself fails (auth, timeout, network), nothing is written and the
run stops, so that day retries on the next run.

Calendar days use the `TZ` environment variable if set, otherwise the system timezone.

## Setup

Headless runs need a long-lived OAuth token:

```sh
claude setup-token
mkdir -p ~/.config/claude-daily-summary
printf '%s' '<token>' > ~/.config/claude-daily-summary/token
chmod 600 ~/.config/claude-daily-summary/token
```

An exported `CLAUDE_CODE_OAUTH_TOKEN` overrides the token file. The tool refuses to run
if the token file is readable by group or others.

Install the CLI and the launch agent:

```sh
./install.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.$USER.claude-daily-summary.plist
```

`install.sh` installs the CLI with uv (as `~/.local/bin/claude-daily-summary`) and
renders the plist template with your username and home directory. It does not start
anything; the `bootstrap` line does. `uninstall.sh` removes the agent and the CLI but
leaves summaries, logs, and the token file alone.

## Usage

Manual run (7-day window by default; the launch agent uses 45):

```sh
BACKFILL_DAYS=7 claude-daily-summary
```

All runs log to `~/Library/Logs/claude-daily-summary.log`. Manual runs from a terminal
also print the same lines live.

Model, budget, call cap, digest size, and paths are constants in
`src/claude_daily_summary/config.py`.

## Development

```sh
uv run pytest
```
