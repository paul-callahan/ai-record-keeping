# Codex Daily Summary

Generates daily Codex work summaries from local Codex rollout JSONL files. The script
builds a bounded digest for each missing completed day, asks `codex exec` to summarize
only days with activity, and writes one markdown file per day under:

```text
$HOME/Documents/codex-work-summaries/
```

The current day is excluded so a partial same-day summary cannot permanently hide later
work. Missing no-activity days are written without a model call.

## How It Works

The CLI looks for missing files named `daily-summary-YYYY-MM-DD.md` in the summary
directory. It walks completed calendar days from oldest to newest inside the configured
backfill window and skips any date that already has a summary file.

For each missing date, it parses local Codex rollout JSONL files from:

```text
$HOME/.codex/sessions/
$HOME/.codex/archived_sessions/
```

Events are bucketed by their recorded timestamps in the configured timezone, not by file
mtime or session directory name. The parser builds a bounded digest with session
workspace, branch, user prompts, executed commands, and files seen in patch markers.

If a missing date has no Codex activity, the CLI writes a no-activity summary directly
without a model call. If the date has activity, it calls `codex exec` in read-only,
ephemeral mode and writes the returned markdown only if the output is non-empty and starts
with a markdown heading.

The run uses a lock file in the summary directory so overlapping invocations do not run at
the same time. Model calls are capped per run, so large backfills may take multiple
scheduled or manual runs. When the cap is reached, the CLI stops at that date so later
placeholder files do not create gaps ahead of unfinished activity days.

## Setup

Install the project CLI and copy the launchd plist:

```sh
./install.sh
```

The installer uses `uv tool install --force --reinstall <project dir>` and does not load launchd or
run the summary tool. It renders the source plist template
`com.{USER}.codex-daily-summary.plist` to:

```text
$HOME/Library/LaunchAgents/com.$USER.codex-daily-summary.plist
```

The rendered launchd label is:

```text
com.$USER.codex-daily-summary
```

## Usage

Manual run:

```sh
BACKFILL_DAYS=3 codex-daily-summary
```

The summary window uses the `TZ` environment variable for day boundaries. If `TZ` is
unset, it defaults to `America/Los_Angeles`.

Set the model with `CODEX_DAILY_SUMMARY_MODEL`:

```sh
CODEX_DAILY_SUMMARY_MODEL=gpt-5.3-codex-spark BACKFILL_DAYS=3 codex-daily-summary
```

If `CODEX_DAILY_SUMMARY_MODEL` is unset, the default is `gpt-5.3-codex-spark`.

Launchd installs the CLI at:

```text
$HOME/.local/bin/codex-daily-summary
```

## Logs

All logs go to:

```text
$HOME/Library/Logs/codex-daily-summary.log
```

## Development

```sh
uv sync
uv run python -m pytest
```
