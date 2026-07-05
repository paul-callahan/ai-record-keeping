"""Backfill daily summaries of Claude Code activity.

Parses Claude Code session transcripts (~/.claude/projects/*/*.jsonl) into a
compact per-day digest, then calls headless Claude (claude -p, no tools) to
write one markdown summary per missing calendar day. The current day is never
summarized so that late work is not lost to an already-written file.
"""
