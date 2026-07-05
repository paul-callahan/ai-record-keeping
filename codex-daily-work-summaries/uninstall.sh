#!/bin/sh
set -eu

INSTALL_USER=${USER:?uninstall.sh: USER must be set}
LAUNCHD_LABEL="com.$INSTALL_USER.codex-daily-summary"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"

UV_BIN=$(command -v uv || true)
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
fi

launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null || true

if [ -n "$UV_BIN" ]; then
    "$UV_BIN" tool uninstall codex-daily-summary 2>/dev/null || true
fi

rm -f "$TARGET_PLIST"

printf '%s\n' "Removed:"
printf '%s\n' "  codex-daily-summary uv tool"
printf '%s\n' "  $TARGET_PLIST"
printf '\n%s\n' "Preserved generated summaries and log files."
