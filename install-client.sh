#!/bin/sh
set -e
SELF=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HOME/.local/bin"
ln -sf "$SELF/famagic_cli.py" "$HOME/.local/bin/famagic"
"$SELF/desktop/install.sh"
"$SELF/plasma-widget/install.sh"
echo "Famagic clients installed (CLI: famagic)."
