# Implement Codex Daily Summary Backfill (digest architecture)

## Context

Build the Codex twin of an existing, working Claude Code daily-summary system. A launchd
agent runs a Python script every 5 hours; the script parses Codex session rollout files
into a compact per-day digest, calls headless Codex (`codex exec`) once per missing day
purely as a summarizer, and writes one markdown summary file per day. The summaries are a
work diary used for performance reviews and resume writing.

Core design decisions, all proven in the Claude version:

1. Exclude-today: the backfill window is yesterday back through `BACKFILL_DAYS`, never the
   current day, because existing files are never regenerated and a same-day file would
   permanently miss afternoon work.
2. Digest pre-pass: the Python wrapper parses the rollout JSONL itself and hands the model
   a bounded digest. The model runs read-only with no session persistence; Python writes
   all output files. Deterministic file handling, bounded token cost, and no-activity days
   cost no model call at all.
3. Throttled catch-up: at most `MAX_CALLS_PER_RUN = 3` model calls per run, oldest days
   first. Days over the cap are deferred (no file written) and picked up by later runs.
   Placeholder days are free and never count against the cap.
4. Honest placeholders: track the data horizon (oldest event date seen in the scan).
   Missing days older than the horizon get a "no session data available" placeholder, not
   a false "no activity" claim.

Create the source files in this project only. Do not install anything, do not run the
summary script, do not invoke `codex exec`, and do not load or start launchd during
implementation.

Create these project files:

```text
codex-daily-summary.py
com.paul.codex-daily-summary.plist
install.sh
uninstall.sh
```

## Verified Codex facts (from this machine, codex-cli 0.142.5)

- Active sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-<local-timestamp>-<uuid>.jsonl`.
  Archived sessions: `~/.codex/archived_sessions/rollout-*.jsonl` (flat directory).
- Each line is JSON: `{"timestamp": "<ISO-8601 UTC>", "type": ..., "payload": {...}}`.
  Top-level types include `session_meta`, `response_item`, `event_msg`, `turn_context`.
- `session_meta` payload carries `cwd` (project path), `git.branch`, `session_id`,
  `originator`.
- Real user prompts are `event_msg` lines with `payload.type == "user_message"` and the
  text in `payload.message`. Some `user_message` events are injected context, not typed
  input; skip messages starting with any of:
  - `\n# Files mentioned by the user:`
  - `\n# Selected text:`
  - `The following is the Codex agent history`
- Shell activity is `response_item` lines with `payload.type == "function_call"` and
  `payload.name == "exec_command"`; `payload.arguments` is a JSON-encoded string whose
  `cmd` field holds the command; if it fails to decode or has no `cmd`, skip that call and
  continue, never crash the run. File edits appear as `apply_patch` commands whose text
  contains `*** Add File: <path>`, `*** Update File: <path>`, `*** Delete File: <path>`.
- The CLI binary is not on launchd's minimal PATH. Resolve with `shutil.which("codex")`,
  falling back to `/Applications/Codex.app/Contents/Resources/codex`.
- `codex exec` flags to use: `--ephemeral` (do not persist the run as a session, which
  prevents the summarizer's own runs from appearing as activity in later summaries),
  `-s read-only` (sandbox), `--cd <dir>` and `--skip-git-repo-check` (run rooted at the
  home directory outside a git repo), and `-o <file>` / `--output-last-message <file>`
  (write only the agent's final message to a file; stdout carries progress noise, so read
  the result from this file, not stdout).
- Auth: `codex exec` uses the CLI's own stored credentials; no token plumbing is needed
  (unlike the Claude twin, which required an OAuth token file for launchd runs). Verify
  once manually before installing.
- There is no budget-cap flag; cost is bounded by the digest size cap and the per-run call
  cap. `-m <model>` is available as a tunable constant (empty means the configured
  default).

## Implementation

### codex-daily-summary.py

Python implementation intended to be installed later as `~/bin/codex-daily-summary.py`.
Standard library only. Tunable constants at the top: optional model, `MAX_CALLS_PER_RUN =
3`, digest size caps (~100k chars per day), prompt/command truncation lengths (~500/~200
chars), per-call timeout (900 s), injected-message skip prefixes.

Startup and hygiene:

- `#!/usr/bin/env python3`.
- Read `BACKFILL_DAYS` from the environment, default `7`, validate as positive integer.
- Resolve the Codex binary (see facts above); fail clearly if not found.
- Create runtime directories only when executed: `~/Documents/codex-work-summaries`,
  `~/Library/Logs`.
- Exclusive non-blocking `fcntl.flock` (`LOCK_EX | LOCK_NB`) at
  `~/Documents/codex-work-summaries/.codex-daily-summary.lock`; on `BlockingIOError`,
  print a message and exit 0. Do not use a plain blocking `LOCK_EX`.
- Append stdout and stderr to `~/Library/Logs/codex-daily-summary.out.log` and
  `~/Library/Logs/codex-daily-summary.err.log` (dup2 onto fds 1 and 2).

Date selection (exclude-today):

- Target dates in America/Los_Angeles (`zoneinfo`): yesterday back through
  `BACKFILL_DAYS`. Skip dates whose
  `~/Documents/codex-work-summaries/daily-summary-YYYY-MM-DD.md` exists. If nothing is
  missing, exit 0 before scanning anything.

Digest pre-pass (runs once, only if any date is missing):

- Scan `~/.codex/sessions/*/*/*/*.jsonl` and `~/.codex/archived_sessions/*.jsonl`, with
  file mtime as a cheap pre-filter (skip files last modified before local midnight of the
  oldest target date).
- Parse line by line with `json.loads`, skipping malformed lines. Convert each event's UTC
  timestamp to its LA calendar date; bucket by date (a session spanning midnight
  contributes to multiple dates). While scanning, track the data horizon: the oldest event
  date seen anywhere, even outside the target window.
- Per session per date, collect: project path (`session_meta` `cwd`, fall back to the
  filename UUID), branch (`session_meta` `git.branch`), first/last event times, user
  prompts (minus injected-context prefixes, truncated), commands (`exec_command` `cmd`,
  truncated; these capture commits and test runs), and files edited (from `apply_patch`
  markers, deduplicated).
- Cap the per-date digest by whole sessions in start-time order; when sessions are
  dropped, append `[digest truncated: N of M sessions included]`.

Per missing date, oldest first, with a model-call counter:

- Date older than the horizon (or nothing scanned at all): write a placeholder stating no
  session data is available for this date (sessions pruned or absent), plus the zero-cost
  footer below. Free.
- No sessions for the date: write

  ```
  # Codex Daily Summary - YYYY-MM-DD

  No Codex activity found.
  ```

  plus the zero-cost footer. Free.
- Sessions exist but the call counter has reached `MAX_CALLS_PER_RUN`: skip without
  writing a file (deferred; retried next run). After the loop, log how many days were
  deferred. Deferral is not a failure; exit code stays 0.
- Otherwise: invoke Codex (below), increment the counter.

Model invocation, with the digest embedded in the prompt (single subprocess argument, no
shell) and the final message directed to a `tempfile`:

```
codex exec --ephemeral -s read-only --cd <home> --skip-git-repo-check -o <tmpfile> <prompt>
```

Apply the timeout so a hung call cannot wedge the job behind the flock. On success, read
the temp file; validate non-empty and starting with `#`; append the token footer; write to
the summary file. On any failure (non-zero exit, timeout, empty or malformed output), log
the error AND the subprocess stdout/stderr to the error log (a hidden error message on
stdout cost real debugging time in the Claude twin), do NOT write the summary file, and
continue with remaining dates. Exit non-zero only if a model call actually failed.

Token footer: every summary file ends with a line like
`_Generation cost: 28,631 tokens (26,100 input + 2,531 output)._` after a `---` rule, and
placeholders end with `_Generation cost: 0 tokens (no model call)._`. For real calls, get
usage from `codex exec` however is cleanest (for example `--json` emits `token_count`
events); figure out the exact mechanism during implementation, and if usage is genuinely
unavailable, fall back to `_Generation cost: unknown._` rather than dropping the footer.

### Summarization prompt (embedded template, one call per date)

This is the exact prompt proven in the Claude twin, adapted only in product name. Keep it
verbatim apart from the `{date}`/`{digest}` substitution mechanism:

```text
You are given a digest of Codex coding sessions for {date} (America/Los_Angeles).
This is a work diary used for performance reviews and resume writing.
Write the complete contents of a daily summary markdown file. Output ONLY the raw markdown,
starting with the line:
# Codex Daily Summary - {date}

Structure:

## Summary
No more than 3 sentences on what was done that day.

## Repos / Workspaces
Bulleted list of the repos worked in that day, if any.

Then one section per repo, most significant first:

## <repo name> (branch when relevant)
### Major Discussions
Significant discussions, investigations, and the decisions reached. Bold topic line, then
short bullets with the findings and the decision. Skip minor back-and-forth.
### Coding Work
Overview of the coding work and its outcomes, grouped by feature or change, not by file.
You may name a key module with a one-phrase purpose when it anchors the work; never
inventory the files touched.
### Git Commits
List the commits created in these sessions. If none are recorded, write "None recorded"
(commits made outside Codex sessions are not visible in the digest).

## Standalone Chats
Q&A or discussions unrelated to the repo work, regardless of which directory the session
ran in. Include only chats with substance: a decision, a learning, or a solution worth
remembering. Omit the section if there were none.

## Caveats
One or two lines, only if the digest notes truncation or transcripts appear incomplete.

Rules:
- Weight space by significance: major work gets detail, minor items get one clause or
  nothing at all.
- If work was implemented in the session, it must appear under Coding Work even if
  authored by another agent under review.
- No long unbroken paragraphs; use bold topic lines and short bullets.
- Do not repeat the same information in more than one section.
- Do not list verification or test commands.
- Omit any section or subsection that would be empty.
- Do not narrate session friction or tooling mishaps unless they cost significant time.
- Do not invent work not supported by the digest. No commentary outside the file content.

DIGEST:
{digest}
```

### com.paul.codex-daily-summary.plist

- Label `com.paul.codex-daily-summary`.
- `ProgramArguments`: `/Users/paul.c/bin/codex-daily-summary.py`.
- `EnvironmentVariables`: `BACKFILL_DAYS` = `45` (wide window for catch-up; the code
  default stays 7 for manual runs).
- `RunAtLoad` true (idempotent, so safe; covers reboots and long sleeps).
- `StartInterval` `18000` (every 5 hours; combined with the call cap this spreads catch-up
  across usage-limit windows).
- `StandardOutPath` `/Users/paul.c/Library/Logs/codex-daily-summary.out.log` and
  `StandardErrorPath` `/Users/paul.c/Library/Logs/codex-daily-summary.err.log`.

### install.sh

- `#!/bin/sh`, `set -eu`, resolve the project directory from `$0`.
- Copy the project script to `~/bin/codex-daily-summary.py` and the plist to
  `~/Library/LaunchAgents/com.paul.codex-daily-summary.plist`.
- Create `~/bin` and `~/Library/LaunchAgents` if needed; make the installed script
  executable.
- If following the amendments that make this a uv project: the install command must be
  `uv tool install --force --reinstall <project dir>`. `--force` alone reuses uv's cached
  wheel and silently installs stale code when the source changed without a version bump;
  `--reinstall` forces a rebuild (confirmed the hard way in the Claude twin).
- Do not run the Python script, do not invoke `codex`, do not run `launchctl`.
- Print the manual commands for later:
  `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.paul.codex-daily-summary.plist`
  and `launchctl kickstart gui/$(id -u)/com.paul.codex-daily-summary`.

### uninstall.sh

- `#!/bin/sh`, `set -eu`, safe to run later by the user.
- `launchctl bootout "gui/$(id -u)/com.paul.codex-daily-summary"`, tolerating "not
  loaded" failures.
- Remove only `~/bin/codex-daily-summary.py` and
  `~/Library/LaunchAgents/com.paul.codex-daily-summary.plist`.
- Preserve summaries, logs, and the lock file; do not remove
  `~/Documents/codex-work-summaries` or `~/Library/Logs/codex-daily-summary.*.log`.

## Verification

Run only source-level checks during implementation:

```sh
ls -l codex-daily-summary.py com.paul.codex-daily-summary.plist install.sh uninstall.sh
PYTHONPYCACHEPREFIX=/private/tmp/codex-pycache python3 -m py_compile codex-daily-summary.py
plutil -lint com.paul.codex-daily-summary.plist
sh -n install.sh
sh -n uninstall.sh
```

Also exercise pure logic (date-window selection, horizon/placeholder branching, digest
capping, token footer rendering) by importing the module and calling those functions with
synthetic data; do not run `main()`.

Do not execute `install.sh` or `uninstall.sh`, do not run `codex-daily-summary.py`, do not
invoke `codex exec`, and do not run any `launchctl` command.

## Known caveats (informational, no action during implementation)

- macOS TCC: launchd-spawned python3 writing to `~/Documents` may hit a privacy prompt or
  "Operation not permitted" on the first run; grant access when prompted or relocate the
  output directory later.
- The parser targets the rollout schema observed today; a future Codex release could
  change it. The parser skips unknown shapes rather than crashing, so a schema change
  degrades summaries instead of breaking the run.
- The injected-message skip-prefix list is empirical; if summaries show boilerplate
  prompts, extend the list.
- Codex session retention policy is unverified; if old rollouts are pruned, the horizon
  placeholder covers it honestly.

## Additional Work Beyond The Prompt

None.
