#!/bin/sh
set -e
SELF=$(cd "$(dirname "$0")" && pwd)
APP="$HOME/famagic-sync-desktop"
ICON="$HOME/.local/share/icons/hicolor/256x256/apps/famagic-desktop.png"
APPS="$HOME/.local/share/applications"
AUTOSTART="$HOME/.config/autostart"
PY=python3

if [ "$1" = "--uninstall" ]; then
    rm -f "$APPS/famagic-desktop.desktop" "$APPS/famagic-desktop-quickadd.desktop"
    rm -f "$AUTOSTART/famagic-desktop.desktop" "$ICON"
    echo "Famagic-Desktop entfernt (Programmordner $APP bleibt)."
    exit 0
fi

mkdir -p "$APP" "$APPS" "$AUTOSTART" "$(dirname "$ICON")"
if [ "$SELF" != "$APP" ]; then
    cp -f "$SELF/famagic_desktop.py" "$APP/"
fi
chmod +x "$APP/famagic_desktop.py"
QT_QPA_PLATFORM=offscreen "$PY" "$APP/famagic_desktop.py" --write-icon "$ICON"

cat > "$APPS/famagic-desktop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Famagic
Comment=Familienliste (VEGA-Sync)
Exec=$PY $APP/famagic_desktop.py
Icon=$ICON
Terminal=false
Categories=Office;Utility;
StartupWMClass=famagic
Keywords=Todo;Familie;Liste;Aufgaben;
EOF

cat > "$APPS/famagic-desktop-quickadd.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Famagic: Neue Aufgabe
Comment=Schnell eine Aufgabe erfassen
Exec=$PY $APP/famagic_desktop.py --quick-add task
Icon=$ICON
Terminal=false
NoDisplay=true
StartupWMClass=famagic
EOF

cat > "$AUTOSTART/famagic-desktop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Famagic (Hintergrund)
Exec=$PY $APP/famagic_desktop.py --hidden
Icon=$ICON
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
chmod +x "$APP/famagic_desktop.py"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
echo "Installiert:"
echo "  App:        $APP/famagic_desktop.py"
echo "  Menüeintrag: Famagic"
echo "  Autostart:  $AUTOSTART/famagic-desktop.desktop (Tray, --hidden)"
echo "  Schnellzugriff: Kurzbefehl auf '$PY $APP/famagic_desktop.py --quick-add task' legen"
