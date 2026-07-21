# AI Coding Work Summaries

Two sibling tools that turn local AI coding session logs into a daily work diary. Each
one runs in the background and writes one markdown file per day, giving you a record you
can use for performance reviews, status updates, and resume notes.

- [claude-daily-work-summaries](claude-daily-work-summaries/) summarizes Claude Code
  sessions.
- [codex-daily-work-summaries](codex-daily-work-summaries/) summarizes Codex sessions.

They are independent projects with the same design. Install and usage details live in each
subdirectory's README.

## What they do

Both assistants record sessions to local files: Claude Code under
`~/.claude/projects/`, Codex under `~/.codex/sessions/`. Each tool reads its own logs,
groups events by calendar day, and writes:

```text
~/Documents/claude-work-summaries/daily-summary-YYYY-MM-DD.md
~/Documents/codex-work-summaries/daily-summary-YYYY-MM-DD.md
```

A summary file starts with a short overview of the day, then breaks the work down by
repository: major discussions, decisions, coding work, outcomes, and commits recorded in
those sessions. Substantive standalone chats are included too. The summaries favor the
work that mattered and skip noise like exhaustive file lists and routine verification
commands.

Each file also includes basic measurements from the logs. Active time is estimated by
merging event timestamps into work blocks, with gaps over 15 minutes treated as idle.
Daily token usage comes from the local transcript data: Claude reports consumed tokens
(fresh input + output) and total processed tokens (including cache reads), while Codex
reports total tokens split into input, output, and unsplit total buckets.

## Sample Codex Summary

Here is the shape of a generated Codex summary. This example is made up.

```md
# Codex Daily Summary - 2026-07-20

## Summary
Spent the day tightening the daily summary tooling and cleaning up the install flow. The
main work was making token accounting easier to read, improving launchd documentation,
and removing a few stale assumptions from the README files.

## Estimated Codex Activity Time
Estimated Codex activity time: 3 hours 18 minutes (198 minutes) using a 15-minute
inactivity cutoff.

## Estimated Codex Token Usage
Estimated Codex token usage: 184,220 total tokens (142,300 input + 31,920 output +
10,000 unsplit total) from local token_count events.

## Repos / Workspaces
- codex-daily-work-summaries
- ai-record-keeping

## codex-daily-work-summaries
### Major Discussions
**Token accounting**
- Decided to report input, output, and unsplit totals separately instead of showing one
  blended token number.
- Kept the wording clear that these are local transcript totals, not billing records.

**Launchd setup**
- Clarified that install copies the plist but does not load or start the agent.
- Added explicit bootstrap, kickstart, and bootout commands for later use.

### Coding Work
**Daily token usage**
- Added split token aggregation from Codex token_count events.
- Carried the token usage line into generated summaries and failure placeholders.

**Documentation cleanup**
- Reworked the project README into a more direct setup and usage guide.
- Updated the parent README so Claude and Codex token accounting are described separately.

### Git Commits
None recorded.

## Standalone Chats
**SSH setup**
- Discussed a dual-key GitHub SSH config for work and personal accounts.

---
_Generation cost: 28,631 tokens (26,100 input + 2,531 output)._
```

## Scheduling

Both install as macOS launchd agents that run on a fixed interval and also at login. The
scheduling is macOS-only; the summarizer itself is a standard Python CLI, so it can be run
by hand on any platform. Each tool logs to a single file under `~/Library/Logs/`.
