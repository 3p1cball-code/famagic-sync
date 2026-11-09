#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

DEFAULT_SERVER = os.environ.get("FAMAGIC_SERVER", "http://192.168.33.24:8791")
TOKEN = os.environ.get("FAMAGIC_TOKEN", "")

if sys.stdout.isatty() and os.environ.get("NO_COLOR") is None:
    C_DIM = "\033[2m"
    C_BOLD = "\033[1m"
    C_ACC = "\033[38;5;214m"
    C_RED = "\033[31m"
    C_OK = "\033[32m"
    C_OFF = "\033[0m"
else:
    C_DIM = C_BOLD = C_ACC = C_RED = C_OK = C_OFF = ""


def api(server, path, method="GET", body=None):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(
        server.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as f:
            raw = f.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw.decode("utf-8", "replace")
        raise SystemExit(f"Fehler {e.code}: {payload}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Server nicht erreichbar ({server}): {e.reason}")


def snapshot(server):
    return api(server, "/api/snapshot")


def resolve_list(snap, needle):
    lists = [l for l in snap.get("lists", []) if not l.get("archived_at")]
    if not needle:
        lists.sort(key=lambda l: (not l.get("is_default"), l.get("created_at") or ""))
        return lists[0] if lists else None
    needle = needle.lower()
    hits = [l for l in lists if needle in (l.get("title") or "").lower() or l.get("id", "").startswith(needle)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"Keine Liste gefunden: {needle}")
    raise SystemExit("Mehrdeutig: " + ", ".join(l["title"] for l in hits))


def resolve_task(snap, prefix):
    hits = [t for t in snap.get("tasks", []) if t.get("id", "").startswith(prefix)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"Keine Aufgabe mit ID-Prefix {prefix}")
    raise SystemExit("ID-Prefix nicht eindeutig: " + ", ".join(t["id"][:8] for t in hits))


def due_label(t):
    d = t.get("due_date")
    if not d:
        return ""
    try:
        y, m, dd = map(int, d.split("-"))
        due = date(y, m, dd)
        delta = (due - date.today()).days
        if delta == 0:
            s = "heute"
        elif delta == 1:
            s = "morgen"
        elif delta < 0:
            s = f"{-delta} Tage überfällig"
        else:
            s = due.strftime("%d.%m.%y")
    except Exception:
        s = d
    if t.get("due_time"):
        s += " " + t["due_time"][:5]
    return s


def member_names(snap):
    out = {}
    for m in snap.get("members", []):
        name = m.get("first_name") or m.get("role") or ""
        out[m["id"]] = name
    return out


def cmd_lists(args, snap):
    default = resolve_list(snap, None)
    for l in snap.get("lists", []):
        if l.get("archived_at"):
            continue
        open_n = sum(1 for t in snap.get("tasks", []) if t.get("list_id") == l["id"] and not t.get("is_completed") and not t.get("parent_task_id"))
        mark = "*" if default and l["id"] == default["id"] else " "
        priv = " (privat)" if l.get("is_private") else ""
        print(f"{mark} {C_BOLD}{l['title']}{C_OFF}{priv}  {C_DIM}{open_n} offen  {l['id'][:8]}{C_OFF}")


def cmd_ls(args, snap):
    lst = resolve_list(snap, args.list)
    if not lst:
        print("Keine Liste")
        return
    names = member_names(snap)
    tasks = [t for t in snap.get("tasks", []) if t.get("list_id") == lst["id"] and not t.get("parent_task_id")]
    open_t = [t for t in tasks if not t.get("is_completed")]
    done_t = [t for t in tasks if t.get("is_completed")]
    open_t.sort(key=lambda t: (t.get("due_date") or "9999", t.get("position") or 0))
    print(f"{C_BOLD}{lst['title']}{C_OFF} {C_DIM}· {len(open_t)} offen{C_OFF}")
    for t in open_t:
        line = f"  {C_DIM}[ ]{C_OFF} {t['title']}"
        parts = []
        dl = due_label(t)
        if dl:
            overdue = t.get("due_date") and t["due_date"] < date.today().isoformat()
            parts.append((C_RED if overdue else C_ACC) + dl + C_OFF)
        if t.get("priority") == "high":
            parts.append(C_ACC + "wichtig" + C_OFF)
        who = [names.get(i, "?") for i in t.get("assignee_member_ids", []) if names.get(i)]
        if who:
            parts.append(C_DIM + ", ".join(who) + C_OFF)
        if parts:
            line += "  " + C_DIM + "·" + C_OFF + " " + "  ".join(parts)
        line += f"  {C_DIM}{t['id'][:8]}{C_OFF}"
        print(line)
    if args.all and done_t:
        print(f"\n{C_DIM}erledigt ({len(done_t)}){C_OFF}")
        for t in done_t:
            print(f"  {C_DIM}[x] {t['title']}  {t['id'][:8]}{C_OFF}")


def cmd_add(args, snap):
    lst = resolve_list(snap, args.list)
    if not lst:
        raise SystemExit("Keine Liste")
    body = {"list_id": lst["id"], "title": " ".join(args.title)}
    if args.notes:
        body["notes"] = args.notes
    if args.due:
        body["due_date"] = args.due
    if args.time:
        body["due_time"] = args.time
    if args.prio:
        body["priority"] = args.prio
    res = api(args.server, "/api/tasks", "POST", body)
    print(f"{C_OK}angelegt{C_OFF} {res.get('id', '')[:8]} in {lst['title']}")


def cmd_done(args, snap, completed=True):
    t = resolve_task(snap, args.id)
    api(args.server, f"/api/tasks/{t['id']}/complete", "POST", {"completed": completed})
    print(f"{C_OK}{'abgehakt' if completed else 'reaktiviert'}{C_OFF} {t['title']}")


def cmd_edit(args, snap):
    t = resolve_task(snap, args.id)
    body = {}
    if args.title:
        body["title"] = " ".join(args.title)
    if args.notes is not None:
        body["notes"] = args.notes
    if args.due is not None:
        body["due_date"] = args.due or None
    if args.time is not None:
        body["due_time"] = args.time or None
    if args.prio:
        body["priority"] = args.prio
    if not body:
        raise SystemExit("Nichts zu ändern")
    api(args.server, f"/api/tasks/{t['id']}", "PATCH", body)
    print(f"{C_OK}gespeichert{C_OFF} {t['title']}")


def cmd_show(args, snap):
    t = resolve_task(snap, args.id)
    lst = next((l for l in snap.get("lists", []) if l["id"] == t.get("list_id")), {})
    print(f"{C_BOLD}{t['title']}{C_OFF}")
    print(f"  Liste:    {lst.get('title')}")
    print(f"  Status:   {'erledigt' if t.get('is_completed') else 'offen'}")
    if t.get("due_date"):
        print(f"  Fällig:   {due_label(t)}")
    if t.get("priority"):
        print(f"  Priorität:{t['priority']}")
    if t.get("notes"):
        print(f"  Notizen:  {t['notes']}")
    print(f"  ID:       {t['id']}")


def cmd_del(args, snap):
    t = resolve_task(snap, args.id)
    if not args.yes:
        ans = input(f"„{t['title']}“ löschen? [j/N] ").strip().lower()
        if ans not in ("j", "ja", "y"):
            return
    api(args.server, f"/api/tasks/{t['id']}", "DELETE")
    print(f"{C_OK}gelöscht{C_OFF} {t['title']}")


def cmd_watch(args, snap):
    print(f"{C_DIM}Beobachte Änderungen (Ctrl+C beendet){C_OFF}")
    last = snap.get("version")
    while True:
        time.sleep(args.interval)
        try:
            s = snapshot(args.server)
        except SystemExit as e:
            print(e)
            continue
        if s.get("version") != last:
            last = s.get("version")
            os.system("clear" if sys.stdout.isatty() else "true")
            cmd_ls(args, s)


def main():
    ap = argparse.ArgumentParser(prog="famagic", description="famagic Familienliste (VEGA-Sync)")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("ls", help="Aufgaben einer Liste")
    p.add_argument("--list", "-l", default=None, help="Liste (Name oder ID-Prefix)")
    p.add_argument("--all", "-a", action="store_true", help="auch erledigte")
    p.set_defaults(fn=cmd_ls)

    p = sub.add_parser("lists", help="Listen anzeigen")
    p.set_defaults(fn=cmd_lists)

    p = sub.add_parser("add", help="Aufgabe anlegen")
    p.add_argument("title", nargs="+")
    p.add_argument("--list", "-l", default=None)
    p.add_argument("--notes", default=None)
    p.add_argument("--due", default=None, help="YYYY-MM-DD")
    p.add_argument("--time", default=None, help="HH:MM")
    p.add_argument("--prio", choices=["normal", "high"], default=None)
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("done", help="abhaken")
    p.add_argument("id")
    p.set_defaults(fn=lambda a, s: cmd_done(a, s, True))

    p = sub.add_parser("undone", help="wieder öffnen")
    p.add_argument("id")
    p.set_defaults(fn=lambda a, s: cmd_done(a, s, False))

    p = sub.add_parser("edit", help="bearbeiten")
    p.add_argument("id")
    p.add_argument("--title", nargs="+")
    p.add_argument("--notes", default=None)
    p.add_argument("--due", default=None)
    p.add_argument("--time", default=None)
    p.add_argument("--prio", choices=["normal", "high"])
    p.set_defaults(fn=cmd_edit)

    p = sub.add_parser("show", help="Details")
    p.add_argument("id")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("del", help="löschen")
    p.add_argument("id")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(fn=cmd_del)

    p = sub.add_parser("watch", help="Änderungen verfolgen")
    p.add_argument("--list", "-l", default=None)
    p.add_argument("--all", "-a", action="store_true")
    p.add_argument("--interval", type=float, default=5.0)
    p.set_defaults(fn=cmd_watch)

    args = ap.parse_args()
    if not args.cmd:
        args.cmd = "ls"
        args.list = None
        args.all = False
        args.fn = cmd_ls
    snap = snapshot(args.server)
    args.fn(args, snap)


if __name__ == "__main__":
    main()
