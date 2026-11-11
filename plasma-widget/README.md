# Famagic Plasma-Widget

Kleines KDE-Plasma-6-Widget (Desktop), das die offenen Famagic-Aufgaben aus VEGA
anzeigt. Klick auf einen Eintrag (oder „Öffnen") startet/fokussiert die
Famagic-Desktop-App.

- Standardsicht: **Diese Woche** (inkl. überfälliger Aufgaben), Person **Alle**.
- Einstellungen (Rechtsklick → *Famagic konfigurieren*): Zeitraum
  (Diese Woche / Heute / 7 / 14 / 30 Tage / Alle) und Person
  (Alle / Niemand / Familienmitglied), Listen, Hintergrund-Deckkraft und
  **Unschärfe** (0–100 %, 0 = aus).
- Unschärfe: `WallpaperBlur.qml` greift das lebende Tapeten-Item der Containment
  per `ShaderEffectSource` ab und zeichnet den Ausschnitt hinter dem Widget mit
  `MultiEffect` weich (KWins Blur-behind erreicht Desktop-Widgets nicht, sie
  liegen im selben Fenster wie die Tapete). Dieselbe Datei steckt im Regenradar-
  und im Deebot-Widget.
- Status: **online grün** (VEGA + Internet), **online orange** (VEGA erreichbar,
  aber VEGA ohne Internet, inkl. „n warten"), **offline rot** (VEGA nicht erreichbar).
- Daten kommen von `http://192.168.33.24:8791/api/snapshot`. `install.sh` legt
  `~/.local/bin/famagic-desktop` an und trägt diesen Pfad ins installierte Widget ein;
  die Desktop-App liegt unter `~/famagic-sync-desktop/`.

Installation auf einem Plasma-Rechner:

```bash
./install.sh    # kopiert nach ~/.local/share/plasma/plasmoids/org.kde.famagic.widget
```

Danach ggf. Plasma neu starten bzw. Rechtsklick auf den Desktop → *Widgets
hinzufügen* → **Famagic**.
