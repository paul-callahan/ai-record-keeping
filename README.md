# AI Coding Work Summaries

Two sibling tools that turn the session history left behind by AI coding assistants into a
daily work diary. Each one runs unattended in the background and writes one markdown file
per day describing what you worked on, intended as a record you can mine for performance
reviews and resume writing.

- [claude-daily-work-summaries](claude-daily-work-summaries/) summarizes Claude Code
  sessions.
- [codex-daily-work-summaries](codex-daily-work-summaries/) summarizes Codex sessions.

They are independent projects with the same design. Install and usage details live in each
subdirectory's README; this document only explains what they do.

## What they do

Both assistants record every session to local files: Claude Code under
`~/.claude/projects/`, Codex under `~/.codex/sessions/`. Those transcripts are large and
noisy. Each tool reads its own transcripts, groups the events by calendar day, and writes:

```text
~/Documents/claude-work-summaries/daily-summary-YYYY-MM-DD.md
~/Documents/codex-work-summaries/daily-summary-YYYY-MM-DD.md
```

A summary file leads with a short overview of the day, then breaks the work down by
repository (major discussions and the decisions reached, the coding work and its outcomes,
and the git commits made in those sessions), followed by any substantive standalone chats.
The output is deliberately shaped as a diary: it weights space by significance, skips
noise like verification commands and exhaustive file lists, and never invents work the
transcripts do not support.

## How they work

The two tools share one architecture:

- **Digest pre-pass.** A plain Python step parses the raw transcripts into a compact,
  bounded per-day digest. This costs no model tokens and does all the file handling
  deterministically. The model is only ever asked to turn a digest into prose.
- **One call per active day.** Days with real activity get a single headless model call
  (`claude -p` or `codex exec`, run read-only with no session persistence). Days with no
  activity are written directly by Python with no model call at all.
- **Yesterday backward, never today.** The current day is excluded, because a file written
  at midday would permanently hide the afternoon's work. Existing files are never
  regenerated, so the run is cheap and idempotent.
- **Throttled catch-up.** Each run makes at most a few model calls, oldest day first, so a
  large backlog (for example switching this on after weeks of work) fills in gradually
  over successive runs rather than in one expensive burst. Progress is contiguous: a run
  never leaves a hole behind the days it has already reached.
- **Honest placeholders.** A day with no activity is marked as such; a day whose
  transcripts were already pruned by the assistant's retention policy is marked as
  unavailable rather than falsely reported as idle.
- **Token accounting.** Each generated file ends with a footer recording the tokens spent
  producing it.

## Scheduling

Both install as macOS launchd agents that run on a fixed interval and also at login. The
scheduling is macOS-only; the summarizer itself is a standard Python CLI, so it can be run
by hand on any platform. Each tool logs to a single file under `~/Library/Logs/`.
