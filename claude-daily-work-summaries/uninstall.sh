#!/bin/sh
# Uninstall the Claude Code daily summary launch agent and CLI.
# Preserves generated summaries, logs, the lock file, and the token file.
set -eu

PLIST_LABEL="com.${USER}.claude-daily-summary"

launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null \
    || echo "Launch agent was not loaded, continuing."

UV=$(command -v uv || echo "$HOME/.local/bin/uv")
"$UV" tool uninstall claude-daily-summary 2>/dev/null \
    || echo "CLI was not installed, continuing."

rm -f "$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

echo "Removed the launch agent plist and the installed CLI."
echo "Summaries in $HOME/Documents/claude-work-summaries, the log at"
echo "$HOME/Library/Logs/claude-daily-summary.log, and the token file in"
echo "$HOME/.config/claude-daily-summary/ were left in place."
