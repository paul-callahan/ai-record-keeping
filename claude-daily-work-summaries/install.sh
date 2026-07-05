#!/bin/sh
# Install the Claude Code daily summary tool and launch agent.
# Installs the CLI via uv and renders the plist template for this user;
# does not run the tool, claude, or launchctl.
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
UV=$(command -v uv || echo "$HOME/.local/bin/uv")

PLIST_TEMPLATE="$SCRIPT_DIR/com.{USER}.claude-daily-summary.plist"
PLIST_LABEL="com.${USER}.claude-daily-summary"
PLIST_DEST="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
USER_UID=$(id -u)

"$UV" tool install --force --reinstall "$SCRIPT_DIR"

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|{USER}|$USER|g" -e "s|{HOME}|$HOME|g" "$PLIST_TEMPLATE" > "$PLIST_DEST"

echo "Installed:"
echo "  $HOME/.local/bin/claude-daily-summary (via uv tool install)"
echo "  $PLIST_DEST"
echo
echo "To start the launch agent now (it also runs on every login), run:"
echo
echo "  launchctl bootstrap gui/$USER_UID $PLIST_DEST"
echo
echo "To force an extra run on demand later:"
echo "  launchctl kickstart gui/$USER_UID/$PLIST_LABEL"
