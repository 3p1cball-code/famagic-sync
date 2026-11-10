#!/bin/sh
set -e
SELF=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/.local/share/plasma/plasmoids/org.kde.famagic.widget"
LAUNCHER="$HOME/.local/bin/famagic-desktop"
mkdir -p "$HOME/.local/bin"
cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
exec python3 "$HOME/famagic-sync-desktop/famagic_desktop.py"
LAUNCH
chmod +x "$LAUNCHER"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -a "$SELF/metadata.json" "$SELF/contents" "$DEST/"
sed "s|__FAMAGIC_OPEN__|$LAUNCHER|g" "$SELF/contents/ui/main.qml" > "$DEST/contents/ui/main.qml"
if ! grep -q "org.kde.famagic.widget" "$HOME/.config/plasma-org.kde.plasma.desktop-appletsrc" 2>/dev/null; then
    SCRIPT="var d = desktops()[0]; if (d) { d.addWidget('org.kde.famagic.widget'); }"
    if command -v qdbus6 >/dev/null 2>&1; then
        qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$SCRIPT" >/dev/null 2>&1 || true
    elif command -v gdbus >/dev/null 2>&1; then
        gdbus call --session --dest org.kde.plasmashell --object-path /PlasmaShell \
          --method org.kde.PlasmaShell.evaluateScript "$SCRIPT" >/dev/null 2>&1 || true
    fi
fi
echo "Installiert: $DEST"
echo "Falls das Widget nicht sofort erscheint: Plasma neu starten oder Rechtsklick auf den Desktop -> Widgets hinzufügen -> Famagic."
