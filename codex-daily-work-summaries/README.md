# Codex Daily Summary

Generates daily Codex work summaries from local Codex rollout JSONL files. The script
builds a bounded digest for each missing completed day, asks `codex exec` to summarize
only days with activity, and writes one markdown file per day under:

```text
$HOME/Documents/codex-work-summaries/
```

The current day is excluded so a partial same-day summary cannot permanently hide later
work. Missing no-activity days are written without a model call.

## Setup

Install the project CLI and copy the launchd plist:

```sh
./install.sh
```

The installer uses `uv tool install --force <project dir>` and does not load launchd or
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
uv run pytest
```
