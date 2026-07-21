# Codex Daily Summary

Generates one markdown summary per completed day from local Codex session logs.

The tool reads Codex rollout JSONL files, builds a compact digest for each missing day,
and asks `codex exec` to turn active days into prose. Days with no activity are written
without a model call.

Summaries are written to:

```text
$HOME/Documents/codex-work-summaries/daily-summary-YYYY-MM-DD.md
```

Existing files are skipped. The current day is skipped too, so an early run cannot hide
work done later the same day.

## What It Reads

The parser reads local Codex session files from:

```text
$HOME/.codex/sessions/
$HOME/.codex/archived_sessions/
```

Events are bucketed by their recorded timestamps in the configured timezone, not by file
mtime or session directory names. Set `TZ` to control day boundaries. If `TZ` is unset,
the default is `America/Los_Angeles`.

## What Goes Into A Summary

For each active day, the digest includes:

- workspaces and branches
- user prompts, excluding injected Codex context
- commands run through Codex
- files found in patch markers
- estimated active time
- estimated token usage

Active time is estimated by merging event timestamps into work blocks. Gaps over 15
minutes are treated as idle, so this is interaction time from the logs, not proof that you
were continuously working.

Daily token usage comes from local Codex `token_count` events. When the event data has the
fields, the summary reports input, output, and unsplit total buckets. This is local
transcript accounting, not a billing statement.

## Catch-Up Behavior

Runs process missing days from oldest to newest. A run makes at most a few model calls, so
a large backlog fills in over multiple runs instead of all at once. When the call limit is
reached, the tool stops for that run rather than skipping ahead and leaving holes.

If a day is older than the available Codex transcripts, the file is marked unavailable. If
a model call fails for an active day, the tool writes a failure placeholder so that one bad
day does not block the rest of the backlog. Delete that day's file and rerun to try again.

## Install

From this directory:

```sh
./install.sh
```

The installer:

- installs the CLI with `uv tool install --force --reinstall`
- writes the launchd plist to `$HOME/Library/LaunchAgents/com.$USER.codex-daily-summary.plist`
- does not run the summary tool
- does not load or start launchd

The installed CLI path is:

```text
$HOME/.local/bin/codex-daily-summary
```

## Manual Run

Run the last 3 completed days:

```sh
BACKFILL_DAYS=3 codex-daily-summary
```

Choose a model with `CODEX_DAILY_SUMMARY_MODEL`:

```sh
CODEX_DAILY_SUMMARY_MODEL=gpt-5.3-codex-spark BACKFILL_DAYS=3 codex-daily-summary
```

If `CODEX_DAILY_SUMMARY_MODEL` is unset, the default is `gpt-5.3-codex-spark`.

## Launchd

After installation, load the agent yourself:

```sh
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.$USER.codex-daily-summary.plist"
```

Start an extra run on demand:

```sh
launchctl kickstart -k "gui/$(id -u)/com.$USER.codex-daily-summary"
```

The launchd job sets `BACKFILL_DAYS=65` and runs every 5 hours. The manual default is 3
completed days.

Unload the agent:

```sh
launchctl bootout "gui/$(id -u)/com.$USER.codex-daily-summary"
```

## Logs

Logs go to:

```text
$HOME/Library/Logs/codex-daily-summary.log
```

Inspect recent logs:

```sh
tail -n 100 "$HOME/Library/Logs/codex-daily-summary.log"
```

## Uninstall

```sh
./uninstall.sh
```

The uninstaller unloads the launchd agent if it is loaded, uninstalls the uv tool, and
removes the plist. It leaves generated summaries and logs alone.

## Development

```sh
uv sync
uv run python -m pytest
```
