#!/bin/sh
set -e
SELF=$(cd "$(dirname "$0")" && pwd)
UNIT="$HOME/.config/systemd/user/famagic-sync.service"
mkdir -p "$(dirname "$UNIT")"
sed "s|%h|$HOME|g; s|/usr/bin/python3|$(command -v python3)|" "$SELF/famagic-sync.service" > "$UNIT"
systemctl --user daemon-reload
systemctl --user enable --now famagic-sync.service
echo "Server unit installed: $UNIT"
echo "If no session exists yet: python3 $SELF/famagic_sync.py --login"
