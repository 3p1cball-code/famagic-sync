#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import pwd
import queue
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import calendar as _calendar
from datetime import date, datetime, timedelta, timezone
from getpass import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = pwd.getpwuid(os.getuid()).pw_dir
CONFIG_DIR = os.path.join(HOME, ".config", "famagic-sync")
DATA_DIR = os.path.join(HOME, ".local", "share", "famagic-sync")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DB_PATH = os.path.join(DATA_DIR, "famagic.db")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

DEFAULT_CONFIG = {
    "supabase_url": "https://snypblaxtimxpxgwmlch.supabase.co",
    "anon_key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNueXBibGF4dGlteHB4Z3dtbGNoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQwOTE3MzksImV4cCI6MjA5OTY2NzczOX0.mm9rVy87erIKxJskGB74AhOi7BaskACaWbCWqsgoQvQ",
    "email": "",
    "user_id": "",
    "refresh_token": "",
    "access_token": "",
    "access_expires_at": 0,
    "port": 8791,
    "bind": "0.0.0.0",
    "poll_seconds": 3,
    "api_token": "",
    "timezone": "Europe/Berlin",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, _calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _add_years(d, n):
    day = min(d.day, _calendar.monthrange(d.year + n, d.month)[1])
    return date(d.year + n, d.month, day)


def next_occurrence(due, rule, today):
    freq = (rule or {}).get("freq") or "yearly"
    try:
        interval = max(1, int((rule or {}).get("interval") or 1))
    except (TypeError, ValueError):
        interval = 1
    if due is None:
        due = today
        advance = True
    else:
        advance = due <= today
    if not advance:
        return due
    while due <= today:
        if freq == "daily":
            due = due + timedelta(days=interval)
        elif freq == "weekly":
            due = due + timedelta(weeks=interval)
        elif freq == "monthly":
            due = _add_months(due, interval)
        else:
            due = _add_years(due, interval)
    return due


def log(msg):
    print(f"[{now_iso()}] {msg}", file=sys.stderr, flush=True)


def load_config(path=CONFIG_PATH):
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


class Supabase:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.base = cfg["supabase_url"].rstrip("/")

    def _headers(self):
        return {
            "apikey": self.cfg["anon_key"],
            "Authorization": "Bearer " + self.cfg["access_token"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _save_session(self, data):
        self.cfg["access_token"] = data["access_token"]
        self.cfg["refresh_token"] = data["refresh_token"]
        self.cfg["access_expires_at"] = int(time.time()) + int(data.get("expires_in", 3600)) - 60
        if data.get("user"):
            self.cfg["user_id"] = data["user"].get("id", self.cfg.get("user_id", ""))
        save_config(self.cfg)

    def login(self, email, password):
        body = json.dumps({"email": email, "password": password}).encode()
        req = urllib.request.Request(
            self.base + "/auth/v1/token?grant_type=password",
            data=body,
            headers={"apikey": self.cfg["anon_key"], "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as f:
                data = json.load(f)
        except urllib.error.HTTPError as e:
            raise SupabaseError(e.code, e.read().decode("utf-8", "replace")[:300])
        except urllib.error.URLError as e:
            raise SupabaseError(0, str(e.reason))
        self.cfg["email"] = email
        self._save_session(data)
        return data

    def refresh(self):
        if not self.cfg.get("refresh_token"):
            raise RuntimeError("Kein Refresh-Token vorhanden - bitte neu einloggen")
        body = json.dumps({"refresh_token": self.cfg["refresh_token"]}).encode()
        req = urllib.request.Request(
            self.base + "/auth/v1/token?grant_type=refresh_token",
            data=body,
            headers={"apikey": self.cfg["anon_key"], "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as f:
                data = json.load(f)
        except urllib.error.HTTPError as e:
            raise SupabaseError(e.code, e.read().decode("utf-8", "replace")[:300])
        except urllib.error.URLError as e:
            raise SupabaseError(0, str(e.reason))
        self._save_session(data)
        log("Session erneuert")
        return data

    def ensure_token(self):
        with self.lock:
            if not self.cfg.get("access_token") or time.time() >= int(self.cfg.get("access_expires_at", 0)):
                self.refresh()
            return self.cfg["access_token"]

    def request(self, method, path, params=None, body=None, prefer=None, base=None):
        url = (base or self.base + "/rest/v1") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        attempt = 0
        while True:
            attempt += 1
            token = self.ensure_token()
            headers = self._headers()
            if prefer:
                headers["Prefer"] = prefer
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as f:
                    raw = f.read()
                    return f.status, (json.loads(raw) if raw else None)
            except urllib.error.HTTPError as e:
                raw = e.read()
                if e.code == 401 and attempt < 2:
                    with self.lock:
                        self.refresh()
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = raw.decode("utf-8", "replace")
                raise SupabaseError(e.code, payload)
            except urllib.error.URLError as e:
                raise SupabaseError(0, str(e.reason))

    def rpc(self, name, args):
        return self.request("POST", "/rpc/" + name, body=args)

    def select_all(self, table, select="*"):
        status, rows = self.request("GET", "/" + table, params={"select": select})
        if not isinstance(rows, list):
            raise SupabaseError(status, rows)
        return rows


class SupabaseError(Exception):
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        super().__init__(f"Supabase {status}: {payload}")


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def json_default(obj):
    return str(obj)


class Store:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS rows (collection TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (collection, id))"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS overlays (task_id TEXT PRIMARY KEY, done_until TEXT NOT NULL, server_due TEXT, prev_due TEXT, done_at TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, created_at TEXT, attempts INTEGER DEFAULT 0, last_error TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS id_map (temp_id TEXT PRIMARY KEY, real_id TEXT NOT NULL)")
        self.db.commit()

    def get_meta(self, key, default=None):
        cur = self.db.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        self.db.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.db.commit()

    def replace_collection(self, collection, rows):
        with self.lock:
            ids = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                rid = r.get("id")
                if rid is None and collection == "task_assignees":
                    if r.get("task_id") and r.get("family_member_id"):
                        rid = "%s:%s" % (r["task_id"], r["family_member_id"])
                if rid is None:
                    continue
                ids[str(rid)] = r
            cur = self.db.execute("SELECT id, data FROM rows WHERE collection=?", (collection,))
            existing = {r[0]: r[1] for r in cur.fetchall()}
            changed = False
            for rid, row in ids.items():
                data = json.dumps(row, ensure_ascii=False, sort_keys=True, default=json_default)
                if existing.get(rid) != data:
                    self.db.execute(
                        "INSERT INTO rows(collection, id, data) VALUES(?,?,?) ON CONFLICT(collection, id) DO UPDATE SET data=excluded.data",
                        (collection, rid, data),
                    )
                    changed = True
            gone = set(existing) - set(ids)
            for rid in gone:
                self.db.execute("DELETE FROM rows WHERE collection=? AND id=?", (collection, rid))
                changed = True
            if changed:
                self.db.commit()
            return changed

    def set_overlay(self, task_id, done_until, server_due, prev_due, done_at):
        with self.lock:
            self.db.execute(
                "INSERT INTO overlays(task_id, done_until, server_due, prev_due, done_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET done_until=excluded.done_until, server_due=excluded.server_due, prev_due=excluded.prev_due, done_at=excluded.done_at",
                (task_id, done_until, server_due, prev_due, done_at),
            )
            self.db.commit()

    def get_overlay(self, task_id):
        with self.lock:
            cur = self.db.execute("SELECT task_id, done_until, server_due, prev_due, done_at FROM overlays WHERE task_id=?", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {"task_id": row[0], "done_until": row[1], "server_due": row[2], "prev_due": row[3], "done_at": row[4]}

    def delete_overlay(self, task_id):
        with self.lock:
            self.db.execute("DELETE FROM overlays WHERE task_id=?", (task_id,))
            self.db.commit()

    def overlays(self):
        with self.lock:
            cur = self.db.execute("SELECT task_id, done_until, server_due, prev_due, done_at FROM overlays")
            return [{"task_id": r[0], "done_until": r[1], "server_due": r[2], "prev_due": r[3], "done_at": r[4]}
                    for r in cur.fetchall()]

    def outbox_add(self, payload):
        with self.lock:
            cur = self.db.execute("INSERT INTO outbox(payload, created_at) VALUES(?,?)",
                                  (json.dumps(payload, ensure_ascii=False), now_iso()))
            self.db.commit()
            return cur.lastrowid

    def outbox_all(self):
        with self.lock:
            cur = self.db.execute("SELECT id, payload, attempts FROM outbox ORDER BY id")
            out = []
            for r in cur.fetchall():
                try:
                    out.append((r[0], json.loads(r[1]), r[2]))
                except ValueError:
                    pass
            return out

    def outbox_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def outbox_delete(self, oid):
        with self.lock:
            self.db.execute("DELETE FROM outbox WHERE id=?", (oid,))
            self.db.commit()

    def outbox_error(self, oid, err):
        with self.lock:
            self.db.execute("UPDATE outbox SET attempts=attempts+1, last_error=? WHERE id=?", (str(err)[:500], oid))
            self.db.commit()

    def outbox_replace(self, oid, payload):
        with self.lock:
            self.db.execute("UPDATE outbox SET payload=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), oid))
            self.db.commit()

    def id_map_set(self, temp_id, real_id):
        with self.lock:
            self.db.execute("INSERT INTO id_map(temp_id, real_id) VALUES(?,?) ON CONFLICT(temp_id) DO UPDATE SET real_id=excluded.real_id",
                            (temp_id, real_id))
            self.db.commit()

    def id_map_get(self, temp_id):
        with self.lock:
            cur = self.db.execute("SELECT real_id FROM id_map WHERE temp_id=?", (temp_id,))
            row = cur.fetchone()
            return row[0] if row else None

    def rows(self, collection):
        with self.lock:
            cur = self.db.execute("SELECT data FROM rows WHERE collection=?", (collection,))
            out = []
            for (data,) in cur.fetchall():
                try:
                    out.append(json.loads(data))
                except Exception:
                    pass
            return out


class Service:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sb = Supabase(cfg)
        self.store = Store()
        self.version = int(self.store.get_meta("version", "0") or 0)
        self.synced_at = self.store.get_meta("synced_at")
        self.last_error = None
        self.subscribers = []
        self.sub_lock = threading.Lock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.snapshot_cache = None
        self.snapshot_version = -1
        self.offline = False

    def _bump(self):
        self.version += 1
        self.store.set_meta("version", self.version)
        self.snapshot_cache = None
        self.notify()

    def reconcile_overlays(self):
        today = date.today().isoformat()
        tasks = {t.get("id"): t for t in self.store.rows("tasks")}
        changed = False
        for ov in self.store.overlays():
            t = tasks.get(ov["task_id"])
            stale = (
                not t
                or not t.get("recurrence_rule")
                or (t.get("due_date") or None) != ov.get("server_due")
                or today >= (ov.get("done_until") or "9999")
            )
            if stale:
                self.store.delete_overlay(ov["task_id"])
                changed = True
                log("Serie-Status zurückgesetzt: %s" % (t.get("title") if t else ov["task_id"]))
        return changed

    def notify(self):
        with self.sub_lock:
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(self.version)
                except Exception:
                    dead.append(q)
            for q in dead:
                self.subscribers.remove(q)

    def subscribe(self):
        q = queue.Queue(maxsize=8)
        with self.sub_lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.sub_lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def sync_once(self):
        changed = False
        errors = []
        net_error = False
        families = None
        lists = None
        shopping = None
        try:
            _, families = self.sb.request(
                "GET", "/families",
                params={"select": "*,family_members(*,profile:public_profiles!family_members_linked_user_id_fkey(id,first_name,last_name,username,avatar_url))"},
            )
        except SupabaseError as e:
            errors.append(f"families: {e}")
            if self._is_net(e):
                net_error = True
        try:
            _, lists = self.sb.request(
                "GET", "/task_lists",
                params={"select": "*,tasks(*,task_assignees(*))"},
            )
        except SupabaseError as e:
            errors.append(f"task_lists: {e}")
            if self._is_net(e):
                net_error = True
        try:
            _, shopping = self.sb.request(
                "GET", "/shopping_lists",
                params={"select": "*,shopping_list_items(*)"},
            )
        except SupabaseError as e:
            errors.append(f"shopping_lists: {e}")
            if self._is_net(e):
                net_error = True
        if net_error:
            self.offline = True
        elif not errors:
            self.offline = False
        if families is not None:
            fam_rows = []
            member_rows = []
            profiles = {}
            for fam in families:
                members = fam.pop("family_members", []) or []
                for m in members:
                    prof = m.get("profile")
                    if prof and prof.get("id"):
                        profiles[prof["id"]] = prof
                    member_rows.append(m)
                fam_rows.append(fam)
            changed |= self.store.replace_collection("families", fam_rows)
            changed |= self.store.replace_collection("family_members", member_rows)
            changed |= self.store.replace_collection("profiles", list(profiles.values()))
        if lists is not None:
            list_rows = []
            task_rows = []
            assign_rows = []
            for lst in lists:
                tasks = lst.pop("tasks", []) or []
                for t in tasks:
                    assign_rows.extend(t.pop("task_assignees", []) or [])
                    task_rows.append(t)
                list_rows.append(lst)
            changed |= self.store.replace_collection("task_lists", list_rows)
            changed |= self.store.replace_collection("tasks", task_rows)
            changed |= self.store.replace_collection("task_assignees", assign_rows)
        if shopping is not None:
            shop_rows = []
            item_rows = []
            for sl in shopping:
                item_rows.extend(sl.pop("shopping_list_items", []) or [])
                shop_rows.append(sl)
            changed |= self.store.replace_collection("shopping_lists", shop_rows)
            changed |= self.store.replace_collection("shopping_list_items", item_rows)
        if self.reconcile_overlays():
            changed = True
        self.synced_at = now_iso()
        self.store.set_meta("synced_at", self.synced_at)
        if changed:
            self.version += 1
            self.store.set_meta("version", self.version)
            self.snapshot_cache = None
            self.notify()
        if errors:
            self.last_error = "; ".join(errors)
            log("Sync-Fehler: " + self.last_error)
        else:
            self.last_error = None
        return changed

    def sync_loop(self):
        while not self.stop.is_set():
            try:
                self.sync_once()
                if not self.offline and self.store.outbox_count():
                    self.flush_outbox()
                    if not self.offline:
                        self.sync_once()
            except Exception as e:
                self.last_error = str(e)
                log(f"Sync abgebrochen: {e}")
            self.wake.wait(self.cfg.get("poll_seconds", 15))
            self.wake.clear()

    def _apply_pending(self, tasks, assignees, shopping_items):
        ops = self.store.outbox_all()
        if not ops:
            return
        today = date.today()
        now = now_iso()
        tasks_by_id = {t.get("id"): t for t in tasks}
        for oid, op, _ in ops:
            kind = op.get("kind")
            if kind == "task_create":
                tid = op.get("temp_id")
                task = {
                    "id": tid, "list_id": op.get("list_id"), "title": op.get("title"),
                    "notes": op.get("notes"), "is_completed": False, "completed_at": None,
                    "completed_by_user_id": None, "due_date": op.get("due_date"),
                    "due_time": op.get("due_time"), "priority": op.get("priority") or "normal",
                    "position": 10 ** 9, "created_at": now, "updated_at": now,
                    "recurrence_rule": op.get("recurrence_rule"), "parent_task_id": None,
                    "client_id": op.get("client_id"), "image_urls": [],
                }
                tasks.append(task)
                tasks_by_id[tid] = task
                for m in op.get("assignee_member_ids") or []:
                    assignees.append({"task_id": tid, "family_member_id": m})
            elif kind == "task_update":
                t = tasks_by_id.get(op.get("task_id"))
                if not t:
                    continue
                for k, v in (op.get("fields") or {}).items():
                    t[k] = v
                if op.get("has_assignees"):
                    assignees[:] = [a for a in assignees if a.get("task_id") != t.get("id")]
                    for m in op.get("assignee_member_ids") or []:
                        assignees.append({"task_id": t.get("id"), "family_member_id": m})
                if op.get("has_recurrence"):
                    t["recurrence_rule"] = op.get("recurrence_rule")
            elif kind == "task_complete":
                t = tasks_by_id.get(op.get("task_id"))
                if not t:
                    continue
                done = bool(op.get("completed"))
                t["is_completed"] = done
                t["completed_at"] = now if done else None
                if done and t.get("recurrence_rule"):
                    due = today
                    try:
                        y, m, d = (int(x) for x in (t.get("due_date") or "").split("-"))
                        due = date(y, m, d)
                    except (ValueError, TypeError):
                        pass
                    nxt = due if due > today else next_occurrence(due, t["recurrence_rule"], today)
                    t["recurrence_done_until"] = nxt.isoformat()
                    if nxt.isoformat() != t.get("due_date"):
                        t["due_date"] = nxt.isoformat()
                else:
                    t.pop("recurrence_done_until", None)
            elif kind == "task_delete":
                t = tasks_by_id.get(op.get("task_id"))
                if t:
                    tasks[:] = [x for x in tasks if x.get("id") != t.get("id")]
                    tasks_by_id.pop(t.get("id"), None)
                    assignees[:] = [a for a in assignees if a.get("task_id") != t.get("id")]
            elif kind == "shopping_create":
                item = {
                    "id": op.get("temp_id"), "list_id": op.get("list_id"), "name": op.get("name"),
                    "quantity_text": op.get("quantity_text"), "notes": op.get("notes"),
                    "is_checked": False, "position": 10 ** 9, "created_at": now, "updated_at": now,
                    "added_by_user_id": self.cfg.get("user_id"), "source": "manual",
                }
                shopping_items.append(item)
            elif kind == "shopping_update":
                for item in shopping_items:
                    if item.get("id") == op.get("item_id"):
                        for k, v in (op.get("fields") or {}).items():
                            item[k] = v
            elif kind == "shopping_delete":
                shopping_items[:] = [i for i in shopping_items if i.get("id") != op.get("item_id")]

    def snapshot(self):
        if self.snapshot_cache is not None and self.snapshot_version == self.version:
            return self.snapshot_cache
        families = self.store.rows("families")
        lists = self.store.rows("task_lists")
        tasks = self.store.rows("tasks")
        members = self.store.rows("family_members")
        assignees = self.store.rows("task_assignees")
        shopping_lists = self.store.rows("shopping_lists")
        shopping_items = self.store.rows("shopping_list_items")
        overlays = {o["task_id"]: o for o in self.store.overlays()}
        for t in tasks:
            ov = overlays.get(t.get("id"))
            if ov:
                t["is_completed"] = True
                t["completed_at"] = ov.get("done_at")
                t["recurrence_done_until"] = ov.get("done_until")
                t["recurrence_prev_due"] = ov.get("prev_due")
        self._apply_pending(tasks, assignees, shopping_items)
        by_task = {}
        for a in assignees:
            by_task.setdefault(a.get("task_id"), []).append(a.get("family_member_id"))
        for t in tasks:
            t["assignee_member_ids"] = by_task.get(t.get("id"), [])
        lists.sort(key=lambda l: (l.get("archived_at") is not None, l.get("created_at") or ""))
        tasks.sort(key=lambda t: (t.get("position") if isinstance(t.get("position"), (int, float)) else 0, t.get("created_at") or ""))
        items_by_list = {}
        for it in shopping_items:
            items_by_list.setdefault(it.get("list_id"), []).append(it)
        for sl in shopping_lists:
            sl["items"] = sorted(
                items_by_list.get(sl.get("id"), []),
                key=lambda i: (i.get("is_checked", False), i.get("position") if isinstance(i.get("position"), (int, float)) else 0),
            )
        snap = {
            "version": self.version,
            "synced_at": self.synced_at,
            "server_time": now_iso(),
            "me": self.cfg.get("user_id", ""),
            "family": families[0] if families else None,
            "lists": lists,
            "tasks": tasks,
            "members": members,
            "profiles": self.store.rows("profiles"),
            "shopping_lists": shopping_lists,
            "error": self.last_error,
            "offline": self.offline,
            "pending": self.store.outbox_count(),
        }
        self.snapshot_cache = snap
        self.snapshot_version = self.version
        return snap

    def find_list(self, list_id):
        for l in self.store.rows("task_lists"):
            if l.get("id") == list_id:
                return l
        return None

    def list_is_private(self, list_id):
        lst = self.find_list(list_id)
        return bool(lst and lst.get("is_private"))

    def find_task(self, task_id):
        return next((t for t in self.store.rows("tasks") if t.get("id") == task_id), None)

    def list_next_position(self, collection, list_field, list_id):
        positions = []
        for row in self.store.rows(collection):
            if row.get(list_field) == list_id and isinstance(row.get("position"), (int, float)):
                positions.append(row["position"])
        return (max(positions) + 1) if positions else 1

    def _is_net(self, e):
        return e.status == 0 or 500 <= e.status < 600

    def _resolve_id(self, ident):
        seen = set()
        while ident and ident not in seen:
            seen.add(ident)
            real = self.store.id_map_get(ident)
            if not real:
                return ident
            ident = real
        return ident

    def _should_queue(self, *ids):
        if self.offline or self.store.outbox_count():
            return True
        for ident in ids:
            if ident and str(ident).startswith("local-"):
                return True
        return False

    def _queue(self, payload, temp_id=None):
        self.store.outbox_add(payload)
        self._bump()
        res = {"success": True, "pending": True}
        if temp_id:
            res["id"] = temp_id
        self.wake.set()
        return res

    def _server_task(self, task_id):
        task = self.find_task(task_id)
        if task:
            return task
        try:
            _, rows = self.sb.request("GET", "/tasks", params={"select": "*", "id": "eq." + task_id})
            return rows[0] if rows else None
        except SupabaseError:
            return None

    def _server_assignees(self, task_id):
        rows = [a.get("family_member_id") for a in self.store.rows("task_assignees")
                if a.get("task_id") == task_id]
        if rows:
            return rows
        try:
            _, rows = self.sb.request("GET", "/task_assignees", params={"select": "*", "task_id": "eq." + task_id})
            return [a.get("family_member_id") for a in rows]
        except SupabaseError:
            return []

    def _remote_create_task(self, payload):
        list_id = self._resolve_id(payload.get("list_id"))
        title = (payload.get("title") or "").strip()
        if not list_id or not title:
            raise ValueError("list_id und title sind erforderlich")
        args = {
            "p_list_id": list_id,
            "p_title": title,
            "p_client_id": payload.get("client_id") or str(uuid.uuid4()),
            "p_due_timezone": payload.get("due_timezone") or self.cfg.get("timezone", "Europe/Berlin"),
        }
        notes = (payload.get("notes") or "").strip()
        if notes:
            args["p_notes"] = notes
        if payload.get("due_date"):
            args["p_due_date"] = payload["due_date"]
        if payload.get("due_time"):
            t = payload["due_time"]
            args["p_due_time"] = t if len(t) > 5 else t + ":00"
        if payload.get("priority") in ("high", "normal"):
            args["p_priority"] = payload["priority"]
        if payload.get("reminder_enabled") is not None:
            args["p_reminder_enabled"] = bool(payload["reminder_enabled"])
        if payload.get("assignee_member_ids") and not self.list_is_private(list_id):
            args["p_assignee_ids"] = payload["assignee_member_ids"]
        rule = payload.get("recurrence_rule")
        if rule:
            if rule.get("freq") == "weekly":
                rule = {"freq": "daily", "interval": 7 * int(rule.get("interval") or 1)}
            args["p_recurrence_rule"] = rule
        status, res = self.sb.rpc("create_task", args)
        if not isinstance(res, dict) or not res.get("success"):
            raise SupabaseError(status, res)
        return {"id": res.get("task_id"), "success": True}

    def _apply_task_update(self, task_id, body):
        task = self._server_task(task_id)
        if "recurrence_rule" in body and task:
            rule = body["recurrence_rule"]
            if rule and rule.get("freq") == "weekly":
                rule = {"freq": "daily", "interval": 7 * int(rule.get("interval") or 1)}
            has_recurrence = bool(task.get("recurrence_rule"))
            if rule is not None and not has_recurrence:
                return self._add_recurrence_by_recreate(task, body, rule)
            if has_recurrence:
                status, res = self.sb.rpc("update_task", {
                    "p_task_id": task_id,
                    "p_recurrence_rule": rule,
                    "p_recurrence_rule_provided": True,
                })
                if not isinstance(res, dict) or not res.get("success"):
                    raise SupabaseError(status, res)
        allowed = {"title", "notes", "due_date", "due_time", "priority", "list_id"}
        nullable = {"due_date", "due_time"}
        patch = {k: body[k] for k in allowed if k in body and (body[k] is not None or k in nullable)}
        if "due_time" in patch and patch["due_time"]:
            t = patch["due_time"]
            patch["due_time"] = t if len(t) > 5 else t + ":00"
        if "title" in patch:
            patch["title"] = patch["title"].strip()
            if not patch["title"]:
                raise ValueError("Titel darf nicht leer sein")
        if patch:
            status, rows = self.sb.request(
                "PATCH", "/tasks", params={"id": "eq." + task_id}, body=patch, prefer="return=representation"
            )
            if status not in (200, 204):
                raise SupabaseError(status, rows)
        assignees_allowed = not (task and self.list_is_private(task.get("list_id")))
        if "assignee_member_ids" in body and assignees_allowed:
            ids = body["assignee_member_ids"] or []
            self.sb.request("DELETE", "/task_assignees", params={"task_id": "eq." + task_id}, prefer="return=minimal")
            if ids:
                rows = [{"task_id": task_id, "family_member_id": m} for m in ids]
                self.sb.request("POST", "/task_assignees", body=rows, prefer="return=minimal")
        if not patch and "assignee_member_ids" not in body and "recurrence_rule" not in body:
            raise ValueError("Keine änderbaren Felder angegeben")
        self.wake.set()
        return {"success": True}

    def _remote_update_task(self, payload):
        task_id = self._resolve_id(payload.get("task_id"))
        body = dict(payload.get("fields") or {})
        if payload.get("has_assignees"):
            body["assignee_member_ids"] = payload.get("assignee_member_ids") or []
        if payload.get("has_recurrence"):
            body["recurrence_rule"] = payload.get("recurrence_rule")
        return self._apply_task_update(task_id, body)

    def _add_recurrence_by_recreate(self, task, body, rule):
        if task.get("parent_task_id"):
            raise ValueError("Serie ist für Unteraufgaben nicht möglich")
        if task.get("image_urls"):
            raise ValueError("Serie nicht möglich: Aufgabe hat Bilder")
        if any(t.get("parent_task_id") == task.get("id") for t in self.store.rows("tasks")):
            raise ValueError("Serie nicht möglich: Aufgabe hat Unteraufgaben")
        list_id = body.get("list_id") or task.get("list_id")
        due_date = body.get("due_date", task.get("due_date"))
        if not due_date:
            raise ValueError("Serie braucht ein Fällig-Datum")
        title = body.get("title", task.get("title")) or ""
        if not title.strip():
            raise ValueError("Titel darf nicht leer sein")
        args = {
            "p_list_id": list_id,
            "p_title": title,
            "p_due_date": due_date,
            "p_priority": body.get("priority", task.get("priority")) or "normal",
            "p_client_id": str(uuid.uuid4()),
            "p_due_timezone": task.get("due_timezone") or self.cfg.get("timezone", "Europe/Berlin"),
            "p_recurrence_rule": rule,
        }
        notes = body.get("notes", task.get("notes")) or ""
        if notes:
            args["p_notes"] = notes
        due_time = body.get("due_time", task.get("due_time"))
        if due_time:
            args["p_due_time"] = due_time
        if task.get("reminder_enabled"):
            args["p_reminder_enabled"] = True
        if task.get("cluster_id"):
            args["p_cluster_id"] = task["cluster_id"]
        if task.get("linked_shopping_list_id"):
            args["p_linked_shopping_list_id"] = task["linked_shopping_list_id"]
        assignees = body.get("assignee_member_ids")
        if assignees is None:
            assignees = self._server_assignees(task["id"])
        if assignees and not self.list_is_private(list_id):
            args["p_assignee_ids"] = assignees
        status, res = self.sb.rpc("create_task", args)
        if not isinstance(res, dict) or not res.get("success"):
            raise SupabaseError(status, res)
        new_id = res.get("task_id")
        self.sb.request("DELETE", "/tasks", params={"id": "eq." + task["id"]}, prefer="return=minimal")
        self.wake.set()
        return {"success": True, "id": new_id, "replaced": True, "outcome": "recurrence_added", "task_id": new_id}

    def _apply_complete(self, task_id, completed):
        task = self._server_task(task_id)
        if task and task.get("recurrence_rule"):
            if completed:
                due = today = date.today()
                if task.get("due_date"):
                    try:
                        y, m, d = (int(x) for x in task["due_date"].split("-"))
                        due = date(y, m, d)
                    except (ValueError, TypeError):
                        pass
                nxt = due if due > today else next_occurrence(due, task["recurrence_rule"], today)
                if nxt != due:
                    status, rows = self.sb.request(
                        "PATCH", "/tasks", params={"id": "eq." + task_id},
                        body={"due_date": nxt.isoformat()}, prefer="return=minimal",
                    )
                    if status not in (200, 204):
                        raise SupabaseError(status, rows)
                self.store.set_overlay(task_id, nxt.isoformat(), nxt.isoformat(), task.get("due_date"), now_iso())
                self._bump()
                return {"success": True, "outcome": "completed_until", "is_completed": True,
                        "next_due_date": nxt.isoformat(), "task_id": task_id}
            ov = self.store.get_overlay(task_id)
            if ov:
                if ov.get("prev_due") and ov.get("server_due") != ov.get("prev_due"):
                    status, rows = self.sb.request(
                        "PATCH", "/tasks", params={"id": "eq." + task_id},
                        body={"due_date": ov["prev_due"]}, prefer="return=minimal",
                    )
                    if status not in (200, 204):
                        raise SupabaseError(status, rows)
                self.store.delete_overlay(task_id)
                self._bump()
            return {"success": True, "outcome": "reopened", "is_completed": False, "task_id": task_id}
        for attempt in range(2):
            args = {"p_task_id": task_id, "p_completed": bool(completed)}
            status, res = self.sb.rpc("set_task_completion", args)
            if isinstance(res, dict) and res.get("success") and not res.get("error"):
                self.wake.set()
                return res
            if attempt == 0:
                self.sync_once()
                continue
            raise SupabaseError(status, res)

    def _remote_complete_task(self, payload):
        return self._apply_complete(self._resolve_id(payload.get("task_id")), payload.get("completed", True))

    def _remote_delete_task(self, payload):
        task_id = self._resolve_id(payload.get("task_id"))
        status, _ = self.sb.request("DELETE", "/tasks", params={"id": "eq." + task_id}, prefer="return=minimal")
        if status not in (200, 204):
            raise SupabaseError(status, _)
        self.wake.set()
        return {"success": True}

    def _remote_create_shopping_item(self, payload):
        list_id = self._resolve_id(payload.get("list_id"))
        name = (payload.get("name") or "").strip()
        if not list_id or not name:
            raise ValueError("list_id und name sind erforderlich")
        row = {"list_id": list_id, "name": name, "added_by_user_id": self.cfg.get("user_id"),
               "position": self.list_next_position("shopping_list_items", "list_id", list_id)}
        if payload.get("quantity_text"):
            row["quantity_text"] = str(payload["quantity_text"]).strip()
        if payload.get("notes"):
            row["notes"] = str(payload["notes"]).strip()
        status, rows = self.sb.request("POST", "/shopping_list_items", body=row, prefer="return=representation")
        if status not in (200, 201):
            raise SupabaseError(status, rows)
        self.wake.set()
        return {"success": True, "id": rows[0]["id"] if rows else None}

    def _remote_update_shopping_item(self, payload):
        item_id = self._resolve_id(payload.get("item_id"))
        patch = dict(payload.get("fields") or {})
        if "name" in patch:
            patch["name"] = (patch["name"] or "").strip()
            if not patch["name"]:
                raise ValueError("Name darf nicht leer sein")
        status, rows = self.sb.request(
            "PATCH", "/shopping_list_items", params={"id": "eq." + item_id}, body=patch, prefer="return=representation"
        )
        if status not in (200, 204):
            raise SupabaseError(status, rows)
        self.wake.set()
        return {"success": True}

    def _remote_delete_shopping_item(self, payload):
        item_id = self._resolve_id(payload.get("item_id"))
        status, _ = self.sb.request("DELETE", "/shopping_list_items", params={"id": "eq." + item_id}, prefer="return=minimal")
        if status not in (200, 204):
            raise SupabaseError(status, _)
        self.wake.set()
        return {"success": True}

    def create_task(self, body):
        list_id = body.get("list_id")
        title = (body.get("title") or "").strip()
        if not list_id or not title:
            raise ValueError("list_id und title sind erforderlich")
        payload = {
            "kind": "task_create",
            "temp_id": None,
            "list_id": list_id,
            "title": title,
            "notes": (body.get("notes") or "").strip(),
            "due_date": body.get("due_date"),
            "due_time": body.get("due_time"),
            "priority": body.get("priority"),
            "reminder_enabled": body.get("reminder_enabled"),
            "assignee_member_ids": body.get("assignee_member_ids") or [],
            "recurrence_rule": body.get("recurrence_rule"),
            "client_id": str(uuid.uuid4()),
            "due_timezone": self.cfg.get("timezone", "Europe/Berlin"),
        }
        if self._should_queue(list_id):
            payload["temp_id"] = "local-" + str(uuid.uuid4())
            return self._queue(payload, payload["temp_id"])
        try:
            return self._remote_create_task(payload)
        except SupabaseError as e:
            if self._is_net(e):
                self.offline = True
                payload["temp_id"] = "local-" + str(uuid.uuid4())
                return self._queue(payload, payload["temp_id"])
            raise

    def update_task(self, task_id, body):
        task_id = self._resolve_id(task_id)
        fields = {}
        allowed = {"title", "notes", "due_date", "due_time", "priority", "list_id"}
        for k in allowed:
            if k in body and (body[k] is not None or k in ("due_date", "due_time")):
                fields[k] = body[k]
        payload = {"kind": "task_update", "task_id": task_id, "fields": fields,
                   "has_assignees": "assignee_member_ids" in body,
                   "assignee_member_ids": body.get("assignee_member_ids") or [],
                   "has_recurrence": "recurrence_rule" in body,
                   "recurrence_rule": body.get("recurrence_rule")}
        if self._should_queue(task_id):
            return self._queue(payload)
        try:
            return self._remote_update_task(payload)
        except SupabaseError as e:
            if self._is_net(e):
                self.offline = True
                return self._queue(payload)
            raise

    def complete_task(self, task_id, completed):
        task_id = self._resolve_id(task_id)
        payload = {"kind": "task_complete", "task_id": task_id, "completed": bool(completed)}
        if self._should_queue(task_id):
            if not completed:
                self.store.delete_overlay(task_id)
            return self._queue(payload)
        try:
            return self._remote_complete_task(payload)
        except SupabaseError as e:
            if self._is_net(e):
                self.offline = True
                if not completed:
                    self.store.delete_overlay(task_id)
                return self._queue(payload)
            raise

    def delete_task(self, task_id):
        task_id = self._resolve_id(task_id)
        payload = {"kind": "task_delete", "task_id": task_id}
        if self._should_queue(task_id):
            return self._queue(payload)
        try:
            return self._remote_delete_task(payload)
        except SupabaseError as e:
            if self._is_net(e):
                self.offline = True
                return self._queue(payload)
            raise

    def create_shopping_item(self, body):
        list_id = body.get("list_id")
        name = (body.get("name") or "").strip()
        if not list_id or not name:
            raise ValueError("list_id und name sind erforderlich")
        payload = {"kind": "shopping_create", "temp_id": None, "list_id": list_id, "name": name,
                   "quantity_text": body.get("quantity_text"), "notes": body.get("notes")}
        if self._should_queue(list_id):
            payload["temp_id"] = "local-" + str(uuid.uuid4())
            return self._queue(payload, payload["temp_id"])
        try:
            return self._remote_create_shopping_item(payload)
        except SupabaseError as e:
            if self._is_net(e):
                self.offline = True
                payload["temp_id"] = "local-" + str(uuid.uuid4())
                return self._queue(payload, payload["temp_id"])
            raise

    def update_shopping_item(self, item_id, body):
        item_id = self._resolve_id(item_id)
        allowed = {"name", "quantity_text", "notes", "is_checked"}
        fields = {k: body[k] for k in allowed if k in body}
        if not fields:
            raise ValueError("Keine änderbaren Felder angegeben")
        payload = {"kind": "shopping_update", "item_id": item_id, "fields": fields}
        if self._should_queue(item_id):
            return self._queue(payload)
        try:
            return self._remote_update_shopping_item(payload)
        except SupabaseError as e:
            if self._is_net(e):
                self.offline = True
                return self._queue(payload)
            raise

    def delete_shopping_item(self, item_id):
        item_id = self._resolve_id(item_id)
        payload = {"kind": "shopping_delete", "item_id": item_id}
        if self._should_queue(item_id):
            return self._queue(payload)
        try:
            return self._remote_delete_shopping_item(payload)
        except SupabaseError as e:
            if self._is_net(e):
                self.offline = True
                return self._queue(payload)
            raise

    def create_shopping_list(self, body):
        title = (body.get("title") or "").strip()
        if not title:
            raise ValueError("title ist erforderlich")
        if self.offline:
            raise ValueError("Neue Listen brauchen Internet")
        families = self.store.rows("families")
        row = {"title": title, "created_by_user_id": self.cfg.get("user_id"),
               "is_private": bool(body.get("is_private")),
               "family_id": None if body.get("is_private") else (families[0]["id"] if families else None)}
        status, rows = self.sb.request("POST", "/shopping_lists", body=row, prefer="return=representation")
        if status not in (200, 201):
            raise SupabaseError(status, rows)
        self.wake.set()
        return {"success": True, "id": rows[0]["id"] if rows else None}

    def create_task_list(self, body):
        title = (body.get("title") or "").strip()
        if not title:
            raise ValueError("title ist erforderlich")
        if self.offline:
            raise ValueError("Neue Listen brauchen Internet")
        families = self.store.rows("families")
        row = {"title": title, "created_by_user_id": self.cfg.get("user_id"),
               "is_private": bool(body.get("is_private")),
               "family_id": None if body.get("is_private") else (families[0]["id"] if families else None)}
        status, rows = self.sb.request("POST", "/task_lists", body=row, prefer="return=representation")
        if status not in (200, 201):
            raise SupabaseError(status, rows)
        self.wake.set()
        return {"success": True, "id": rows[0]["id"] if rows else None}

    def flush_outbox(self):
        ops = self.store.outbox_all()
        if not ops:
            return False
        removed = False
        for oid, payload, attempts in ops:
            try:
                kind = payload.get("kind")
                if kind == "task_create":
                    res = self._remote_create_task(payload)
                    self._map_temp(payload.get("temp_id"), res.get("id"))
                elif kind == "task_update":
                    res = self._remote_update_task(payload)
                    if res.get("replaced") and res.get("id"):
                        self._map_temp(payload.get("task_id"), res.get("id"))
                elif kind == "task_complete":
                    self._remote_complete_task(payload)
                elif kind == "task_delete":
                    self._remote_delete_task(payload)
                elif kind == "shopping_create":
                    res = self._remote_create_shopping_item(payload)
                    self._map_temp(payload.get("temp_id"), res.get("id"))
                elif kind == "shopping_update":
                    self._remote_update_shopping_item(payload)
                elif kind == "shopping_delete":
                    self._remote_delete_shopping_item(payload)
                self.store.outbox_delete(oid)
                removed = True
            except SupabaseError as e:
                if self._is_net(e):
                    self.offline = True
                    self.store.outbox_error(oid, e)
                    log("Outbox: offline (%s)" % e)
                    break
                self.store.outbox_error(oid, e)
                self.store.outbox_delete(oid)
                removed = True
                log("Outbox verworfen (%s): %s" % (payload.get("kind"), e))
            except Exception as e:
                self.store.outbox_error(oid, e)
                self.store.outbox_delete(oid)
                removed = True
                log("Outbox verworfen (%s): %s" % (payload.get("kind"), e))
        if removed:
            self._bump()
        return removed

    def _map_temp(self, temp_id, real_id):
        if not temp_id or not real_id:
            return
        self.store.id_map_set(temp_id, real_id)
        for oid, payload, _ in self.store.outbox_all():
            changed = False
            for key in ("task_id", "list_id", "item_id"):
                if payload.get(key) == temp_id:
                    payload[key] = real_id
                    changed = True
            if changed:
                self.store.outbox_replace(oid, payload)

class Handler(BaseHTTPRequestHandler):
    service = None

    def log_message(self, fmt, *args):
        log("HTTP " + fmt % args)

    def _send(self, status, payload, content_type="application/json; charset=utf-8", extra=None):
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False).encode()
        elif isinstance(payload, str):
            body = payload.encode()
        else:
            body = payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _authorized(self):
        token = self.service.cfg.get("api_token") or ""
        if not token:
            return True
        auth = self.headers.get("Authorization") or ""
        if auth == "Bearer " + token:
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return q.get("token", [""])[0] == token

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/health":
                self._send(200, {
                    "ok": True,
                    "version": self.service.version,
                    "synced_at": self.service.synced_at,
                    "error": self.service.last_error,
                })
                return
            if path == "/api/snapshot":
                if not self._authorized():
                    self._send(401, {"error": "unauthorized"})
                    return
                self._send(200, self.service.snapshot())
                return
            if path == "/api/events":
                if not self._authorized():
                    self._send(401, {"error": "unauthorized"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                q = self.service.subscribe()
                try:
                    self.wfile.write(f"event: hello\ndata: {self.service.version}\n\n".encode())
                    self.wfile.flush()
                    while not self.service.stop.is_set():
                        try:
                            v = q.get(timeout=20)
                            self.wfile.write(f"event: update\ndata: {v}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    self.service.unsubscribe(q)
                return
            if path in ("/", "/index.html"):
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    self._send(200, f.read(), content_type="text/html; charset=utf-8")
                return
            self._send(404, {"error": "not found"})
        except Exception as e:
            log(f"GET {path} fehlgeschlagen: {e}")
            self._send(500, {"error": str(e)})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            body = self._json_body()
            if path == "/api/tasks":
                self._send(201, self.service.create_task(body))
                return
            if path.startswith("/api/tasks/") and path.endswith("/complete"):
                task_id = path.split("/")[3]
                self._send(200, self.service.complete_task(task_id, body.get("completed", True)))
                return
            if path == "/api/shopping/items":
                self._send(201, self.service.create_shopping_item(body))
                return
            if path == "/api/shopping/lists":
                self._send(201, self.service.create_shopping_list(body))
                return
            if path == "/api/lists":
                self._send(201, self.service.create_task_list(body))
                return
            self._send(404, {"error": "not found"})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except SupabaseError as e:
            self._send(502, {"error": "supabase", "status": e.status, "detail": e.payload})
        except Exception as e:
            log(f"POST {path} fehlgeschlagen: {e}")
            self._send(500, {"error": str(e)})

    def do_PATCH(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            if path.startswith("/api/shopping/items/"):
                item_id = path.split("/")[4]
                self._send(200, self.service.update_shopping_item(item_id, self._json_body()))
                return
            if path.startswith("/api/tasks/"):
                task_id = path.split("/")[3]
                self._send(200, self.service.update_task(task_id, self._json_body()))
                return
            self._send(404, {"error": "not found"})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except SupabaseError as e:
            self._send(502, {"error": "supabase", "status": e.status, "detail": e.payload})
        except Exception as e:
            log(f"PATCH {path} fehlgeschlagen: {e}")
            self._send(500, {"error": str(e)})

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            if path.startswith("/api/shopping/items/"):
                item_id = path.split("/")[4]
                self._send(200, self.service.delete_shopping_item(item_id))
                return
            if path.startswith("/api/tasks/"):
                task_id = path.split("/")[3]
                self._send(200, self.service.delete_task(task_id))
                return
            self._send(404, {"error": "not found"})
        except SupabaseError as e:
            self._send(502, {"error": "supabase", "status": e.status, "detail": e.payload})
        except Exception as e:
            log(f"DELETE {path} fehlgeschlagen: {e}")
            self._send(500, {"error": str(e)})


def cmd_login(cfg):
    email = cfg.get("email") or input("Famagic E-Mail: ").strip()
    password = getpass("Famagic Passwort: ")
    sb = Supabase(cfg)
    data = sb.login(email, password)
    print("Login OK:", data.get("user", {}).get("email"), data.get("user", {}).get("id"))
    print("Config:", CONFIG_PATH)


def cmd_check(cfg):
    sb = Supabase(cfg)
    sb.ensure_token()
    svc = Service(cfg)
    svc.sync_once()
    snap = svc.snapshot()
    print("Familie:", (snap.get("family") or {}).get("name"))
    print("Listen:", len(snap["lists"]), "Aufgaben:", len(snap["tasks"]), "Einkaufslisten:", len(snap["shopping_lists"]))
    print("Sync:", svc.synced_at, "Fehler:", svc.last_error)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--port", type=int)
    ap.add_argument("--bind")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.port:
        cfg["port"] = args.port
    if args.bind:
        cfg["bind"] = args.bind
    if args.login:
        cmd_login(cfg)
        return
    if args.check:
        cmd_check(cfg)
        return
    svc = Service(cfg)
    if args.once:
        svc.sync_once()
        print(json.dumps(svc.snapshot(), ensure_ascii=False, indent=2))
        return
    if not cfg.get("refresh_token"):
        print("Keine Session. Bitte zuerst: famagic_sync.py --login", file=sys.stderr)
        sys.exit(2)
    Handler.service = svc
    server = ThreadingHTTPServer((cfg.get("bind", "0.0.0.0"), cfg.get("port", 8791)), Handler)
    t = threading.Thread(target=svc.sync_loop, daemon=True)
    t.start()
    log(f"famagic-sync läuft auf http://{cfg.get('bind')}:{cfg.get('port')}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        svc.stop.set()
        svc.wake.set()
        server.server_close()


if __name__ == "__main__":
    main()
