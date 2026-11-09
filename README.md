# famagic-sync

Inoffizielle Sync-Brücke für die **famagic**-Familien-App (famagic UG, Berlin).
Famagic ist eine Expo/React-Native-App mit Supabase-Backend; eine offizielle API oder
Web-App gibt es (Stand 11/2026) nicht. Dieses Projekt hält auf einem Always-on-Rechner
(hier: VEGA) eine eigene Session, spiegelt die relevanten Tabellen in SQLite und stellt
sie im LAN als HTTP-API, Web-UI, CLI, KDE-Plasma-Widget und PyQt-Desktop-App bereit.
Schreibzugriffe nutzen dieselben RPCs wie die App (inkl. Serien-/Wiederholungslogik,
Abhaken, Einkauf). Ist das Internet weg, sammelt eine lokale Outbox die Änderungen und
spielt sie beim Reconnect nach.

**Komponenten:** Sync-Dienst (`famagic_sync.py`, systemd-User-Dienst), Web-UI
(`web/`), CLI (`famagic`), Desktop-App (`desktop/`, PyQt6), Plasma-Widget
(`plasma-widget/`). Die **Monocell**-App und das dortige Desktop-Widget liegen im
[Monocell-Repo](https://github.com/3p1cball-code/monocell).

**Keine Zugangsdaten im Repo:** der Sync-Dienst speichert nur den rotierenden
Refresh-Token unter `~/.config/famagic-sync/config.json` (0600), nie das Passwort.
Der in der App-Config enthaltene Supabase-*anon*-Key ist öffentlich (er steckt in der
APK); Familiendaten liegen nicht im Repo.

## Schnellstart

Auf dem Server (VEGA):

```bash
git clone https://github.com/3p1cball-code/famagic-sync.git ~/famagic-sync
cd ~/famagic-sync
python3 famagic_sync.py --login        # einmalig: Famagic-E-Mail + Passwort
./install-server.sh                    # systemd-User-Dienst, Autostart
# optional: sudo firewall-cmd --permanent --add-port=8791/tcp && sudo firewall-cmd --reload
```

Auf jedem Client (Nobara/KDE, Yoga, …):

```bash
git clone https://github.com/3p1cball-code/famagic-sync.git ~/famagic-sync
~/famagic-sync/install-client.sh       # CLI, Desktop-App, Plasma-Widget
```

Die Clients sprechen ausschließlich mit VEGA (`http://192.168.33.24:8791`; anpassbar
über `~/.config/famagic-sync/client.json` oder `FAMAGIC_SERVER`).

## Architektur

```
Famagic-App (Flip 7)  ──┐
                        ├── Supabase (snypblaxtimxpxgwmlch, EU)
andere Familienhandys ──┘        ▲
                                 │ REST + Auth (Refresh-Token-Rotation)
                        famagic-sync auf VEGA (systemd --user)
                                 │  SQLite-Spiegel + HTTP auf 0.0.0.0:8791
                 ┌───────────────┼────────────────┐
             Web-UI         CLI (Nobara)     monocell/Widgets
```

Ein zentraler Dienst ist nötig, weil Supabase die Refresh-Tokens bei jeder Erneuerung
rotiert: mehrere Geräte mit demselben Token würden sich gegenseitig die Session
wegnehmen. Clients sprechen deshalb nur mit VEGA, nicht direkt mit Supabase.

## Dateien

| Pfad | Zweck |
|---|---|
| `~/.config/famagic-sync/config.json` | Session (0600), Port, optional API-Token |
| `~/.local/share/famagic-sync/famagic.db` | SQLite-Spiegel |
| `~/famagic-sync/famagic_sync.py` | Dienst |
| `~/famagic-sync/famagic_cli.py` | Terminal-Client (`famagic`) |
| `~/famagic-sync/web/index.html` | Web-UI |
| `~/.config/systemd/user/famagic-sync.service` | Autostart-Dienst |

## Dienst

```bash
systemctl --user status famagic-sync
systemctl --user restart famagic-sync
journalctl --user -u famagic-sync -f
```

Sync-Intervall: 3 s (config: `poll_seconds`). Änderungen aus der App erscheinen damit
nach wenigen Sekunden, eigene Schreibzugriffe sofort. Offene Clients hängen am
SSE-Stream und bekommen jede Änderung sofort gepusht.

## Offline-Betrieb (Outbox)

Ist Supabase (Internet) nicht erreichbar, bleibt VEGA bedienbar:

- **Anzeigen** kommt aus dem lokalen SQLite-Spiegel.
- **Änderungen** (Aufgaben anlegen/ändern/abhaken/löschen, Einkaufseinträge in
  Familienlisten) werden in einer **Outbox** (SQLite) vorgemerkt und sofort
  optimistisch im Snapshot gezeigt (`offline: true`, `pending: n`). Die Clients
  zeigen **„offline · n warten"**.
- Sobald die Verbindung wieder steht, spielt VEGA die Outbox **in Reihenfolge** an
  Supabase nach (bei Anlegen mit temporären IDs, die auf die echten IDs umgeschrieben
  werden), synct danach und leert die Warteschlange. Die Outbox überlebt Neustarts.
- Konflikte: Last-Write-Wins auf den geänderten Feldern; ungültige Aktionen (4xx)
  werden verworfen und geloggt, damit die Queue nicht blockiert.
- **Grenzen:** Neue Listen brauchen weiterhin Internet. Einträge in **privaten**
  Einkaufslisten lehnt der Famagic-Server derzeit per RLS ab (unabhängig von der
  Outbox); Familien-Einkaufslisten funktionieren.

## API (Port 8791)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/health` | Status |
| GET | `/api/snapshot` | kompletter Stand (Listen, Aufgaben, Mitglieder, Einkauf) inkl. `offline`/`pending` |
| GET | `/api/events` | SSE-Stream, meldet Änderungen |
| POST | `/api/tasks` | Aufgabe anlegen `{list_id,title,notes?,due_date?,due_time?,priority?,assignee_member_ids?,recurrence_rule?}` |
| PATCH | `/api/tasks/{id}` | `{title?,notes?,due_date?,due_time?,priority?,list_id?,assignee_member_ids?,recurrence_rule?}` |
| POST | `/api/tasks/{id}/complete` | `{completed:true\|false}` (nutzt App-RPC, inkl. Serien) |
| DELETE | `/api/tasks/{id}` | löschen |
| POST | `/api/shopping/items` | Einkaufseintrag `{list_id,name,quantity_text?,notes?}` |
| PATCH | `/api/shopping/items/{id}` | `{name?,quantity_text?,notes?,is_checked?}` |
| DELETE | `/api/shopping/items/{id}` | löschen |
| POST | `/api/shopping/lists` | Einkaufsliste `{title,is_private?}` |
| POST | `/api/lists` | Aufgabenliste `{title,is_private?}` |

`priority`: `normal` oder `high`. `due_date`: `YYYY-MM-DD`, `due_time`: `HH:MM[:SS]`.

Optionaler Schutz: in `config.json` `api_token` setzen. Dann verlangt `/api/*`
`Authorization: Bearer <token>` (oder `?token=` für SSE). Ohne Token ist der Dienst
nur im LAN/Tailnet erreichbar – VEGA hat kein Port-Forwarding.

## CLI

```bash
famagic lists                 # Listen
famagic ls                    # offene Aufgaben der Standardliste
famagic ls -l "Persönliche" -a
famagic add "Blumen gießen" --due 2026-11-12 --prio high -l Familienliste
famagic done 3609b4e1         # ID-Prefix reicht
famagic undone 3609b4e1
famagic edit 3609b4e1 --title "Neuer Titel" --notes "..." --due 2026-11-20
famagic show 3609b4e1
famagic del 3609b4e1
famagic watch                 # live mitlesen
```

Server: `FAMAGIC_SERVER` (Default `http://192.168.33.24:8791`), Token: `FAMAGIC_TOKEN`.

## Web-UI

`http://192.168.33.24:8791/` – mobile-first, Listen-Tabs, Abhaken, Bearbeiten,
Anlegen (Aufgaben und Einkauf). Hell/Dunkel nach Systemeinstellung.

## Desktop-App (Nobara/KDE)

`~/famagic-sync/desktop/famagic_desktop.py` (PyQt6). Installer:

```bash
~/famagic-sync/desktop/install.sh
```

- Standardliste = Familienliste, Sidebar mit Aufgaben- und Einkaufslisten.
- **Filter „Zugewiesen"** in der Werkzeugleiste (Alle / Niemand / Familienmitglied);
  wirkt auf offene und erledigte Einträge, bei Einkaufslisten ausgeblendet.
- **Wiederholung** im Dialog (Keine / Täglich / Wöchentlich / Monatlich / Jährlich);
  beim Anlegen und beim Bearbeiten aller Aufgaben. Das Fälligkeitsdatum ist die nächste
  Anzeige; Serien brauchen eines. Wöchentlich wird als „alle 7 Tage" gespeichert
  (Famagic akzeptiert kein `weekly`-Objekt). Bei einer normalen Aufgabe legt VEGA sie
  mit Serie neu an (Felder und Zuweisungen bleiben) und entfernt die alte; Aufgaben mit
  Bildern/Unteraufgaben sind ausgenommen.
- `+ Neu` bzw. `Strg+N` öffnet den Dialog: Art (Aufgabe/Einkaufsidee), Liste,
  Titel, Zuweisung, Fällig, Priorität, Notiz (Einkauf: Menge).
- Abhaken per Klick, Bearbeiten per Klick auf die Zeile, Rechtsklick-Menü.
- **Echtzeit:** SSE-Verbindung zu VEGA; Änderungen der Familie erscheinen nach dem
  nächsten Sync (≤ 3 s) sofort, eigene Schreibzugriffe direkt.
- **Tray:** läuft im Hintergrund (Autostart `--hidden`), Klick öffnet das Fenster.
  `--quick-add task` öffnet nur den Neu-Dialog – ideal für einen KDE-Kurzbefehl.
- Weitere Rechner: Ordner kopieren, `install.sh` ausführen (Pfade werden eingesetzt).

## KDE-Plasma-Widget

Quelle `~/famagic-sync/plasma-widget/` (Kopie im Share als `Medien/famagic-plasma-widget/`).
Installiert auf nobara-pc unter `~/.local/share/plasma/plasmoids/org.kde.famagic.widget`
und dem Desktop hinzugefügt (`install.sh`). Zeigt offene/überfällige Aufgaben im
gewählten Zeitraum/Person/Listen (Widget-Einstellungen: Diese Woche/Heute/7/14/30/Alle,
Alle/Niemand/Person und Listen-Checkboxen), bricht lange Titel um, Klick öffnet die
Desktop-App. Status grün/orange/rot (orange = VEGA erreichbar, kein Internet).
Der Person-Filter gilt nur für Familienlisten; Aufgaben der privaten Liste bleiben
immer sichtbar.

## Monocell

App `famagic` (Kategorie Office): Dropdown-Box mit vollen Listennamen (`v` am rechten
Rand), `+ Liste` (neue Liste), `+ Neu` unten mittig in Blau (neuer Eintrag), Abhaken
per Klick/Space/Doppelklick, gelbes `!` (bearbeiten) und rotes `X` (löschen mit
Nachfrage) je Zeile, Neu-Dialog mit Art/Liste/Zuweisung/Fällig/Priorität, Kalender
fürs Fälligkeitsdatum (TT-MM-JJJJ), Einkauf inkl. Menge, Status online grün / Fehler
rot, Auto-Refresh 5 s. Serien-Aufgaben (z. B. jährlich) werden als **erledigt**
angezeigt und stehen bei den erledigten Einträgen; VEGA hält den Status „erledigt bis
<Termin>" lokal (SQLite) und öffnet sie am Termin automatisch wieder (die Serie bleibt
serverseitig offen). Meldung „Für dieses Mal erledigt · wieder am …", Markierung „Serie" (blau).
**Desktop-Widget unten rechts** mit den fälligen Aufgaben, mehrzeilig umbrochen
(Einstellungen → Famagic: Anzeige an/aus, Zeitraum, Person, Listen einzeln an/aus;
Klick öffnet die App). Am Listenende klappt
**„Erledigt (n)"** die erledigten Einträge aus
(Klick oder Auswahl + Space/Enter), **Filter nach Zuweisung** über `f` bzw. die
„Filter: …"-Zeile (Alle/Niemand/Person, mit Trefferzahlen). Auf privaten
Aufgabenlisten werden keine Zuweisungen angeboten (Famagic verbietet sie dort; der Dienst entfernt sie auch per
API). Patch und Doku unter
`Medien/monocell-patches/2026-11-09-famagic/`.

## Firewall

Einmalig als root:

```bash
sudo firewall-cmd --permanent --add-port=8791/tcp && sudo firewall-cmd --reload
```

## Lizenz und Hinweis

MIT-Lizenz (siehe `LICENSE`). Dies ist eine **inoffizielle** Integration einer
Beta-App: Die Supabase-Endpunkte können sich mit App-Updates ändern. Nutzung auf
eigene Verantwortung; keine Gewähr für API-Stabilität.

## Sicherheit / Grenzen

- Das Passwort wird nur beim Login (`famagic_sync.py --login`) verwendet und nicht
  gespeichert; gespeichert wird der rotierende Refresh-Token (0600).
- Alle Schreibzugriffe laufen mit dem eigenen Famagic-Konto über dieselbe RLS wie die App.
  Änderungen sind sofort für die ganze Familie sichtbar (Realtime in der App).
- Famagic ist Beta: Tabellen/RPCs können sich mit App-Updates ändern. Der Dienst loggt
  Sync-Fehler, behält den letzten Stand und versucht es weiter.
- Kein Zugriff auf Familienfremdes: Supabase-RLS beschränkt auf die eigene Familie.
- Abhaken nutzt `set_task_completion` – Serienaufgaben werden wie in der App behandelt.
