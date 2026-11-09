# Famagic Plasma-Widget

Kleines KDE-Plasma-6-Widget (Desktop), das die offenen Famagic-Aufgaben aus VEGA
anzeigt. Klick auf einen Eintrag (oder „Öffnen") startet/fokussiert die
Famagic-Desktop-App.

- Standardsicht: **Diese Woche** (inkl. überfälliger Aufgaben), Person **Alle**.
- Einstellungen (Rechtsklick → *Famagic konfigurieren*): Zeitraum
  (Diese Woche / Heute / 7 / 14 / 30 Tage / Alle) und Person
  (Alle / Niemand / Familienmitglied).
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
