#!/usr/bin/env bash
set -e

BINDIR="$HOME/.local/bin"
APPDIR="$HOME/.local/share/applications"
DATADIR="$HOME/.local/share/forum-scout"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$BINDIR" "$APPDIR" "$DATADIR/translations"

VERSION="$(cat "$DIR/VERSION")"
sed "s/__VERSION__/$VERSION/" "$DIR/forum-scout.py" > /tmp/forum-scout-inst
install -Dm755 /tmp/forum-scout-inst "$BINDIR/forum-scout"
rm /tmp/forum-scout-inst
install -Dm644 "$DIR/forum-scout.desktop" "$APPDIR/forum-scout.desktop"

for f in "$DIR/translations/"*.json; do
    install -Dm644 "$f" "$DATADIR/translations/$(basename "$f")"
done

install -Dm644 "$DIR/forums.conf" "$DATADIR/forums.conf"

echo "forum-scout installed to $BINDIR/forum-scout"
echo "forums installed to $DATADIR/forums.conf"
echo "translations installed to $DATADIR/translations/"
echo "desktop entry installed to $APPDIR/forum-scout.desktop"

if [[ ":$PATH:" != *":$BINDIR:"* ]]; then
    echo ""
    echo "Note: $BINDIR is not in your \$PATH."
    echo "Add this line to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
