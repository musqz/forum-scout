#!/usr/bin/env bash
set -e

BINDIR="$HOME/.local/bin"
APPDIR="$HOME/.local/share/applications"
DATADIR="$HOME/.local/share/forum-scout"

rm -f  "$BINDIR/forum-scout"
rm -f  "$APPDIR/forum-scout.desktop"
rm -rf "$DATADIR"

echo "forum-scout uninstalled."
echo ""
echo "User data was not removed. To delete it:"
echo "  rm -rf ~/.config/forum-scout ~/.cache/forum-scout"
