#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
INSTALL_USER=${USER:?install.sh: USER must be set}
LAUNCHD_LABEL="com.$INSTALL_USER.codex-daily-summary"

SOURCE_PLIST="$SCRIPT_DIR/com.{USER}.codex-daily-summary.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"

if [ ! -f "$SOURCE_PLIST" ]; then
    printf '%s\n' "install.sh: missing source file: $SOURCE_PLIST" >&2
    exit 1
fi

UV_BIN=$(command -v uv || true)
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
fi

if [ -z "$UV_BIN" ]; then
    printf '%s\n' "install.sh: uv not found on PATH or at $HOME/.local/bin/uv" >&2
    exit 1
fi

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[\/&]/\\&/g'
}

PLIST_USER=$(escape_sed_replacement "$INSTALL_USER")
PLIST_HOME=$(escape_sed_replacement "$HOME")

mkdir -p "$HOME/Library/LaunchAgents"
"$UV_BIN" tool install --force "$SCRIPT_DIR"
sed \
    -e "s/{USER}/$PLIST_USER/g" \
    -e "s/{HOME}/$PLIST_HOME/g" \
    "$SOURCE_PLIST" > "$TARGET_PLIST"

printf '%s\n' "Installed:"
printf '%s\n' "  $HOME/.local/bin/codex-daily-summary"
printf '%s\n' "  $TARGET_PLIST"
printf '\n%s\n' "Not loaded. To load and start the launch agent, run:"
printf '%s\n' "launchctl bootstrap gui/\$(id -u) $TARGET_PLIST"
printf '\n%s\n' "To force an extra run on demand later:"
printf '%s\n' "launchctl kickstart -k gui/\$(id -u)/$LAUNCHD_LABEL"
