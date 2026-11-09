#!/usr/bin/env python3
import argparse
import json
import os
import pwd
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date

from PyQt6.QtCore import QDate, QRectF, Qt, QTime, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QTextEdit, QTimeEdit, QVBoxLayout, QWidget,
)

HOME = pwd.getpwuid(os.getuid()).pw_dir
CLIENT_CFG = os.path.join(HOME, ".config", "famagic-sync", "client.json")
DEFAULT_SERVER = "http://192.168.33.24:8791"
APP_ID = "famagic-desktop"

AMBER = "#e8a13a"
BG = "#141414"
CARD = "#1d1d1d"
CARD2 = "#242424"
LINE = "#2e2e2e"
TEXT = "#ececec"
MUTED = "#9a9a9a"
DIM = "#6f6f6f"
RED = "#d96a5a"

QSS = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 14px; }}
QMainWindow {{ background: {BG}; }}
QLabel#wordmark {{ color: {AMBER}; font-size: 14px; font-weight: 700; letter-spacing: 3px; }}
QLabel#family {{ color: {MUTED}; font-size: 11px; letter-spacing: 1px; }}
QLabel#status {{ color: {DIM}; font-size: 11px; }}
QLabel#section {{ color: {DIM}; font-size: 10px; letter-spacing: 2px; font-weight: 600; }}
QLabel#viewtitle {{ color: {TEXT}; font-size: 17px; font-weight: 600; }}
QLabel#due {{ color: {MUTED}; font-size: 11px; }}
QLabel#donemore {{ color: {DIM}; font-size: 11px; letter-spacing: 1px; }}
QPushButton#side {{
    text-align: left; padding: 7px 10px; border: 0; border-radius: 7px;
    color: {MUTED}; background: transparent;
}}
QPushButton#side:hover {{ background: {CARD2}; color: {TEXT}; }}
QPushButton#side:checked {{ background: {CARD2}; color: {AMBER}; font-weight: 600; }}
QPushButton#new {{
    background: {AMBER}; color: #141414; border: 0; border-radius: 8px;
    font-weight: 700; padding: 8px 16px;
}}
QPushButton#new:hover {{ background: #f2b355; }}
QPushButton#ghost {{
    background: transparent; color: {MUTED}; border: 1px solid {LINE};
    border-radius: 7px; padding: 5px 10px;
}}
QPushButton#ghost:hover {{ color: {TEXT}; border-color: {DIM}; }}
QFrame#task {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#task:hover {{ background: {CARD2}; }}
QLabel#title {{ color: {TEXT}; font-size: 14px; }}
QLabel#titeldone {{ color: {DIM}; font-size: 14px; }}
QScrollArea {{ border: 0; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QDialog {{ background: {BG}; }}
QLineEdit, QTextEdit, QComboBox, QDateEdit, QTimeEdit {{
    background: #191919; border: 1px solid {LINE}; border-radius: 7px;
    padding: 6px 8px; selection-background-color: {AMBER}; selection-color: #141414;
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus {{ border-color: {AMBER}; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {LINE}; selection-background-color: {AMBER}; selection-color: #141414; }}
QCheckBox {{ color: {TEXT}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {DIM}; border-radius: 4px; background: #191919; }}
QCheckBox::indicator:checked {{ background: {AMBER}; border-color: {AMBER}; }}
QLabel#formhint {{ color: {DIM}; font-size: 11px; }}
QMenu {{ background: {CARD}; border: 1px solid {LINE}; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: {AMBER}; color: #141414; }}
"""


def client_config():
    cfg = {"server": DEFAULT_SERVER, "token": ""}
    try:
        with open(CLIENT_CFG, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in ("server", "token"):
            if data.get(k):
                cfg[k] = str(data[k])
    except (OSError, ValueError):
        pass
    if os.environ.get("FAMAGIC_SERVER"):
        cfg["server"] = os.environ["FAMAGIC_SERVER"]
    if os.environ.get("FAMAGIC_TOKEN"):
        cfg["token"] = os.environ["FAMAGIC_TOKEN"]
    return cfg


class Api:
    def __init__(self, cfg):
        self.cfg = cfg

    def request(self, method, path, body=None, timeout=10):
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.cfg.get("token"):
            headers["Authorization"] = "Bearer " + self.cfg["token"]
        req = urllib.request.Request(
            self.cfg["server"].rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as f:
                raw = f.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw
            raise RuntimeError("HTTP %d: %s" % (e.code, payload))
        except urllib.error.URLError as e:
            raise RuntimeError(str(e.reason))

    def snapshot(self):
        return self.request("GET", "/api/snapshot")

    def create_task(self, body):
        return self.request("POST", "/api/tasks", body)

    def update_task(self, task_id, body):
        return self.request("PATCH", "/api/tasks/" + task_id, body)

    def complete_task(self, task_id, completed):
        return self.request("POST", "/api/tasks/%s/complete" % task_id, {"completed": completed})

    def delete_task(self, task_id):
        return self.request("DELETE", "/api/tasks/" + task_id)

    def create_shopping_item(self, body):
        return self.request("POST", "/api/shopping/items", body)

    def update_shopping_item(self, item_id, body):
        return self.request("PATCH", "/api/shopping/items/" + item_id, body)

    def delete_shopping_item(self, item_id):
        return self.request("DELETE", "/api/shopping/items/" + item_id)


def repeat_key(rule):
    if not rule:
        return "none"
    freq = rule.get("freq")
    try:
        interval = int(rule.get("interval") or 1)
    except (TypeError, ValueError):
        interval = 1
    if freq == "weekly":
        return "weekly"
    if freq == "daily":
        return "weekly" if interval > 1 and interval % 7 == 0 else "daily"
    if freq == "monthly":
        return "monthly"
    if freq == "yearly":
        return "yearly"
    return "daily"


def repeat_rule(key):
    return {
        "none": None,
        "daily": {"freq": "daily", "interval": 1},
        "weekly": {"freq": "weekly", "interval": 1},
        "monthly": {"freq": "monthly", "interval": 1},
        "yearly": {"freq": "yearly", "interval": 1},
    }.get(key)


def member_name(m):
    prof = m.get("profile") or {}
    return prof.get("first_name") or m.get("first_name") or m.get("role") or "?"


def due_text(task, today=None):
    d = task.get("due_date")
    if not d:
        return ""
    today = today or date.today()
    try:
        y, mo, dd = (int(x) for x in d.split("-"))
        due = date(y, mo, dd)
    except (ValueError, TypeError):
        return str(d)
    delta = (due - today).days
    if delta == 0:
        s = "heute"
    elif delta == 1:
        s = "morgen"
    elif delta < 0:
        s = "%d Tage überfällig" % -delta
    else:
        s = "%02d-%02d-%04d" % (dd, mo, y)
    if task.get("due_time"):
        s += " · " + task["due_time"][:5]
    return s


class CheckCircle(QWidget):
    clicked = pyqtSignal()

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.checked = checked
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover = False

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(3, 3, 18, 18)
        if self.checked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(AMBER))
            p.drawEllipse(r)
            pen = QPen(QColor("#141414"), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(7.5, 12.5)
            path.lineTo(11, 16)
            path.lineTo(17, 9.5)
            p.drawPath(path)
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(AMBER if self.hover else "#555555"), 1.6))
            p.drawEllipse(r)

    def enterEvent(self, ev):
        self.hover = True
        self.update()

    def leaveEvent(self, ev):
        self.hover = False
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class TaskRow(QFrame):
    toggled = pyqtSignal(dict)
    activated = pyqtSignal(dict)
    context = pyqtSignal(dict, object)

    def __init__(self, task, members, done_style=False, parent=None):
        super().__init__(parent)
        self.task = task
        self.setObjectName("task")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        self.check = CheckCircle(bool(task.get("is_completed")))
        self.check.clicked.connect(lambda: self.toggled.emit(self.task))
        lay.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(task.get("title") or "")
        title.setObjectName("titeldone" if task.get("is_completed") else "title")
        title.setWordWrap(True)
        if task.get("is_completed"):
            f = title.font()
            f.setStrikeOut(True)
            title.setFont(f)
        col.addWidget(title)
        meta = []
        due = due_text(task)
        if due:
            meta.append(due)
        if task.get("priority") == "high":
            meta.append("wichtig")
        if task.get("recurrence_rule"):
            meta.append("Serie")
        names = [member_name(m) for m in members if m["id"] in (task.get("assignee_member_ids") or [])]
        if names:
            meta.append(", ".join(names))
        if meta:
            lab = QLabel("  ·  ".join(meta))
            lab.setObjectName("due")
            col.addWidget(lab)
        lay.addLayout(col, 1)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.task)
        elif ev.button() == Qt.MouseButton.RightButton:
            self.context.emit(self.task, ev.globalPosition().toPoint())


class ShoppingRow(QFrame):
    toggled = pyqtSignal(dict)
    activated = pyqtSignal(dict)
    context = pyqtSignal(dict, object)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("task")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        self.check = CheckCircle(bool(item.get("is_checked")))
        self.check.clicked.connect(lambda: self.toggled.emit(self.item))
        lay.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = item.get("name") or ""
        if item.get("quantity_text"):
            name += "  ·  " + item["quantity_text"]
        lab = QLabel(name)
        lab.setObjectName("titeldone" if item.get("is_checked") else "title")
        lab.setWordWrap(True)
        if item.get("is_checked"):
            f = lab.font()
            f.setStrikeOut(True)
            lab.setFont(f)
        col.addWidget(lab)
        if item.get("notes"):
            n = QLabel(item["notes"])
            n.setObjectName("due")
            n.setWordWrap(True)
            col.addWidget(n)
        lay.addLayout(col, 1)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.item)
        elif ev.button() == Qt.MouseButton.RightButton:
            self.context.emit(self.item, ev.globalPosition().toPoint())


class ComposeDialog(QDialog):
    submitted = pyqtSignal(dict)
    deleted = pyqtSignal(dict)

    def __init__(self, snap, kind="task", list_id=None, task=None, item=None, parent=None):
        super().__init__(parent)
        self.snap = snap
        self.task = task
        self.item = item
        self.member_boxes = {}
        editing = bool(task or item)
        self.show_repeat = item is None
        self.current_kind = kind
        if task:
            kind = "task"
        if item:
            kind = "shopping"
        self.setWindowTitle("Bearbeiten" if editing else "Neu")
        self.setModal(True)
        self.setMinimumWidth(430)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        head = QLabel("Eintrag bearbeiten" if editing else "Was möchtest du anlegen?")
        head.setObjectName("viewtitle")
        v.addWidget(head)

        self.type_combo = None
        if not editing:
            trow = QHBoxLayout()
            trow.addWidget(QLabel("Art"))
            self.type_combo = QComboBox()
            self.type_combo.addItem("Aufgabe", "task")
            self.type_combo.addItem("Einkaufsidee", "shopping")
            self.type_combo.setCurrentIndex(1 if kind == "shopping" else 0)
            self.type_combo.currentIndexChanged.connect(self.type_changed)
            trow.addWidget(self.type_combo, 1)
            v.addLayout(trow)

        self.title = QLineEdit(task.get("title") if task else item.get("name") if item else "")
        self.title.setPlaceholderText("Was ist zu tun?" if kind == "task" else "Was fehlt?")
        v.addWidget(self.title)

        self.list_combo = QComboBox()
        v.addWidget(self.list_combo)

        self.due_row = None
        self.due_check = QCheckBox("Fällig am")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MM-yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.time_check = QCheckBox("Uhrzeit")
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime.currentTime())
        due = QHBoxLayout()
        due.addWidget(self.due_check)
        due.addWidget(self.date_edit, 1)
        due.addWidget(self.time_check)
        due.addWidget(self.time_edit)
        self.due_row = QWidget()
        self.due_row.setLayout(due)
        v.addWidget(self.due_row)

        self.repeat_combo = QComboBox()
        self.repeat_combo.addItem("Keine", "none")
        self.repeat_combo.addItem("Täglich", "daily")
        self.repeat_combo.addItem("Wöchentlich", "weekly")
        self.repeat_combo.addItem("Monatlich", "monthly")
        self.repeat_combo.addItem("Jährlich", "yearly")
        self.repeat_combo.currentIndexChanged.connect(self.repeat_changed)
        rep = QHBoxLayout()
        rep.addWidget(QLabel("Wiederholung"))
        rep.addWidget(self.repeat_combo, 1)
        self.repeat_row = QWidget()
        self.repeat_row.setLayout(rep)
        v.addWidget(self.repeat_row)
        self.repeat_hint = QLabel("Serie: erscheint am Fälligkeitsdatum wieder")
        self.repeat_hint.setObjectName("formhint")
        v.addWidget(self.repeat_hint)

        self.prio = QComboBox()
        self.prio.addItem("Normal", "normal")
        self.prio.addItem("Wichtig", "high")
        self.prio_row = QWidget()
        prow = QHBoxLayout(self.prio_row)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(QLabel("Priorität"))
        prow.addWidget(self.prio, 1)
        v.addWidget(self.prio_row)

        self.assign_row = QWidget()
        al = QVBoxLayout(self.assign_row)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(QLabel("Zuweisen"))
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, m in enumerate(snap.get("members", [])):
            cb = QCheckBox(member_name(m))
            self.member_boxes[m["id"]] = cb
            grid.addWidget(cb, i // 3, i % 3)
        al.addLayout(grid)
        v.addWidget(self.assign_row)

        self.qty = QLineEdit(item.get("quantity_text") if item else "")
        self.qty.setPlaceholderText("Menge (z. B. 2 × oder 500 g)")
        self.qty_row = QWidget()
        ql = QHBoxLayout(self.qty_row)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(QLabel("Menge"))
        ql.addWidget(self.qty, 1)
        v.addWidget(self.qty_row)

        self.notes = QTextEdit(task.get("notes") if task else item.get("notes") if item else "")
        self.notes.setPlaceholderText("Notizen (optional)")
        self.notes.setFixedHeight(70)
        v.addWidget(self.notes)

        btns = QDialogButtonBox()
        self.save_btn = QPushButton("Speichern" if editing else "Anlegen")
        self.save_btn.setObjectName("new")
        self.save_btn.clicked.connect(self.accept)
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        btns.addButton(self.save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        if editing:
            dele = QPushButton("Löschen")
            dele.setObjectName("ghost")
            dele.clicked.connect(self.do_delete)
            btns.addButton(dele, QDialogButtonBox.ButtonRole.DestructiveRole)
        v.addWidget(btns)

        if task:
            self.title.setText(task.get("title") or "")
            if task.get("due_date"):
                self.due_check.setChecked(True)
                y, mo, d = (int(x) for x in task["due_date"].split("-"))
                self.date_edit.setDate(QDate(y, mo, d))
            if task.get("due_time"):
                self.time_check.setChecked(True)
                hh, mm = task["due_time"].split(":")[:2]
                self.time_edit.setTime(QTime(int(hh), int(mm)))
            self.prio.setCurrentIndex(1 if task.get("priority") == "high" else 0)
            idx = self.repeat_combo.findData(repeat_key(task.get("recurrence_rule")))
            if idx >= 0:
                self.repeat_combo.setCurrentIndex(idx)
            for mid in task.get("assignee_member_ids") or []:
                if mid in self.member_boxes:
                    self.member_boxes[mid].setChecked(True)
        if item:
            self.due_row.hide()
            self.prio_row.hide()
            self.assign_row.hide()
        self.current_kind = kind
        self.fill_lists(kind, list_id, task, item)
        self.apply_visibility()
        self.list_combo.currentIndexChanged.connect(self.apply_visibility)
        self.title.setFocus()

    def fill_lists(self, kind, list_id, task=None, item=None):
        self.list_combo.clear()
        if kind == "task":
            rows = [l for l in self.snap.get("lists", []) if not l.get("archived_at")]
            current = task.get("list_id") if task else list_id
            for l in rows:
                self.list_combo.addItem(l.get("title") + (" (privat)" if l.get("is_private") else ""), l["id"])
            if current:
                for i in range(self.list_combo.count()):
                    if self.list_combo.itemData(i) == current:
                        self.list_combo.setCurrentIndex(i)
                        break
        else:
            rows = self.snap.get("shopping_lists", [])
            current = item.get("list_id") if item else list_id
            for l in rows:
                self.list_combo.addItem(l.get("title") + (" (privat)" if l.get("is_private") else ""), l["id"])
            if current:
                for i in range(self.list_combo.count()):
                    if self.list_combo.itemData(i) == current:
                        self.list_combo.setCurrentIndex(i)
                        break

    def type_changed(self):
        if self.type_combo is None:
            return
        kind = self.type_combo.currentData()
        if kind == self.current_kind:
            return
        self.current_kind = kind
        self.fill_lists(kind, None)
        self.apply_visibility()

    def repeat_changed(self, idx):
        key = self.repeat_combo.currentData()
        if key != "none" and not self.due_check.isChecked():
            self.due_check.setChecked(True)
            if not self.date_edit.date().isValid():
                self.date_edit.setDate(QDate.currentDate())
        self.repeat_hint.setVisible(self.show_repeat and self.current_kind == "task" and key != "none")

    def selected_list_private(self):
        if self.current_kind != "task":
            return False
        lid = self.list_combo.currentData()
        for l in self.snap.get("lists", []):
            if l.get("id") == lid:
                return bool(l.get("is_private"))
        return False

    def apply_visibility(self):
        task = self.current_kind == "task"
        private = task and self.selected_list_private()
        self.due_row.setVisible(task)
        self.prio_row.setVisible(task)
        self.assign_row.setVisible(task and not private)
        self.qty_row.setVisible(not task)
        self.repeat_row.setVisible(task and self.show_repeat)
        self.repeat_hint.setVisible(task and self.show_repeat and self.repeat_combo.currentData() != "none")
        if private:
            for cb in self.member_boxes.values():
                cb.setChecked(False)
        self.title.setPlaceholderText("Was ist zu tun?" if task else "Was fehlt?")

    def values(self):
        kind = self.current_kind
        body = {"list_id": self.list_combo.currentData()}
        if kind == "task":
            body["title"] = self.title.text().strip()
            body["notes"] = self.notes.toPlainText().strip()
            body["priority"] = self.prio.currentData()
            if self.due_check.isChecked():
                body["due_date"] = self.date_edit.date().toString("yyyy-MM-dd")
            else:
                body["due_date"] = None
            if self.time_check.isChecked():
                body["due_time"] = self.time_edit.time().toString("HH:mm")
            else:
                body["due_time"] = None
            if not self.selected_list_private():
                body["assignee_member_ids"] = [mid for mid, cb in self.member_boxes.items() if cb.isChecked()]
            if self.show_repeat:
                body["recurrence_rule"] = repeat_rule(self.repeat_combo.currentData())
        else:
            body["name"] = self.title.text().strip()
            body["quantity_text"] = self.qty.text().strip()
            body["notes"] = self.notes.toPlainText().strip()
        body["_kind"] = kind
        return body

    def accept(self):
        if not self.title.text().strip():
            self.title.setFocus()
            return
        if self.show_repeat and self.repeat_combo.currentData() != "none":
            self.due_check.setChecked(True)
        self.submitted.emit(self.values())
        super().accept()

    def do_delete(self):
        self.deleted.emit({"task": self.task, "item": self.item})
        super().accept()


class FamagicWindow(QMainWindow):
    sig_snapshot = pyqtSignal(dict)
    sig_state = pyqtSignal(str)
    sig_note = pyqtSignal(str)

    def __init__(self, api, start_quick_add=False):
        super().__init__()
        self.api = api
        self.snap = None
        self.version = -1
        self.view = "task"
        self.list_id = None
        self.done_open = False
        self.setWindowTitle("Famagic")
        self.online = False
        self.filter_member = None
        self._filter_key = None
        self.cloud_offline = False
        self.pending = 0
        self.resize(760, 720)
        self.setStyleSheet(QSS)
        self.setWindowIcon(make_icon())

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 12, 18, 10)
        self.wordmark = QLabel("FAMAGIC")
        self.wordmark.setObjectName("wordmark")
        self.family = QLabel("")
        self.family.setObjectName("family")
        self.status = QLabel("verbinde …")
        self.status.setObjectName("status")
        hl.addWidget(self.wordmark)
        hl.addSpacing(8)
        hl.addWidget(self.family)
        hl.addStretch(1)
        hl.addWidget(self.status)
        outer.addWidget(head)

        body = QHBoxLayout()
        body.setContentsMargins(10, 0, 10, 10)
        body.setSpacing(10)
        self.side = QVBoxLayout()
        self.side.setSpacing(2)
        sidewrap = QWidget()
        sidewrap.setLayout(self.side)
        sidewrap.setFixedWidth(200)
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setWidget(sidewrap)
        self.side_scroll.setFixedWidth(208)
        self.side_scroll.setStyleSheet("QScrollArea { background: transparent; } QWidget { background: transparent; }")
        body.addWidget(self.side_scroll)

        main = QVBoxLayout()
        main.setSpacing(8)
        toolbar = QHBoxLayout()
        self.viewtitle = QLabel("Familienliste")
        self.viewtitle.setObjectName("viewtitle")
        self.new_btn = QPushButton("+  Neu")
        self.new_btn.setObjectName("new")
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(lambda: self.compose())
        self.filter_caption = QLabel("Zugewiesen")
        self.filter_caption.setObjectName("due")
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(130)
        self.filter_combo.setMaximumWidth(180)
        self.filter_combo.currentIndexChanged.connect(self.filter_changed)
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.setToolTip("Aktualisieren")
        self.refresh_btn.clicked.connect(self.fetch_now)
        toolbar.addWidget(self.viewtitle)
        toolbar.addStretch(1)
        toolbar.addWidget(self.filter_caption)
        toolbar.addWidget(self.filter_combo)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.new_btn)
        main.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.rows = QWidget()
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.rows)
        main.addWidget(self.scroll, 1)
        body.addLayout(main, 1)
        outer.addLayout(body, 1)

        self.sse_running = True
        self.sig_snapshot.connect(self.apply)
        self.sig_state.connect(self.set_online)
        self.sig_note.connect(self.show_note)
        threading.Thread(target=self.sse_loop, daemon=True).start()

        self.timer = QTimer(self)
        self.timer.setInterval(10000)
        self.timer.timeout.connect(self.fetch_now)
        self.timer.start()

        self.tray = None
        self.tray_hint_shown = False
        self.make_tray()
        self.fetch_now()
        if start_quick_add:
            QTimer.singleShot(300, self.quick_add)

    def make_tray(self):
        from PyQt6.QtWidgets import QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("Famagic")
        menu = QMenu()
        act_open = QAction("Öffnen", self)
        act_open.triggered.connect(self.show_window)
        act_task = QAction("Neue Aufgabe …", self)
        act_task.triggered.connect(lambda: self.quick_add("task"))
        act_shop = QAction("Neue Einkaufsidee …", self)
        act_shop.triggered.connect(lambda: self.quick_add("shopping"))
        act_refresh = QAction("Aktualisieren", self)
        act_refresh.triggered.connect(self.fetch_now)
        act_quit = QAction("Beenden", self)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(act_task)
        menu.addAction(act_shop)
        menu.addSeparator()
        menu.addAction(act_refresh)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_clicked)
        self.tray.show()

    def tray_clicked(self, reason):
        from PyQt6.QtWidgets import QSystemTrayIcon
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, ev):
        if self.tray is not None and not self.tray_hint_shown and QApplication.instance().property("quitting") is None:
            ev.ignore()
            self.hide()
            self.tray.showMessage("Famagic", "Läuft im Hintergrund weiter.", make_icon(), 2500)
            self.tray_hint_shown = True
            return
        super().closeEvent(ev)

    def sse_loop(self):
        delay = 1
        while self.sse_running:
            try:
                headers = {"Accept": "text/event-stream"}
                if self.api.cfg.get("token"):
                    headers["Authorization"] = "Bearer " + self.api.cfg["token"]
                url = self.api.cfg["server"].rstrip("/") + "/api/events"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=90) as f:
                    self.sig_state.emit("online")
                    buf = []
                    while self.sse_running:
                        line = f.readline()
                        if not line:
                            break
                        line = line.decode("utf-8", "replace").strip()
                        if not line:
                            if buf and any(x.startswith("data:") for x in buf):
                                try:
                                    self.sig_snapshot.emit(self.api.snapshot())
                                except Exception:
                                    pass
                            buf = []
                        else:
                            buf.append(line)
                delay = 1
            except Exception:
                self.sig_state.emit("offline")
            if not self.sse_running:
                break
            time.sleep(delay)
            delay = min(15, delay * 2)

    def stop_sse(self):
        self.sse_running = False

    def fetch_now(self):
        def work():
            try:
                snap = self.api.snapshot()
            except Exception:
                self.sig_state.emit("offline")
                return
            self.sig_snapshot.emit(snap)
        threading.Thread(target=work, daemon=True).start()

    def set_online(self, state):
        self.online = state == "online"
        self.update_status()

    def update_status(self):
        if not self.online:
            self.status.setText("VEGA nicht erreichbar")
            self.status.setStyleSheet("color: %s;" % RED)
            return
        if self.cloud_offline:
            self.status.setText("online · %d warten" % self.pending)
            self.status.setStyleSheet("color: %s;" % AMBER)
        elif self.pending:
            self.status.setText("online · %d werden gesendet" % self.pending)
            self.status.setStyleSheet("color: %s;" % AMBER)
        else:
            stamp = ((self.snap or {}).get("synced_at") or "")[11:16]
            self.status.setText("synchronisiert " + stamp if stamp else "synchronisiert")
            self.status.setStyleSheet("color: %s;" % DIM)

    def apply(self, snap):
        try:
            version = int(snap.get("version") or 0)
        except Exception:
            version = 0
        if self.snap is not None and version == self.version:
            return
        self.snap = snap
        self.version = version
        fam = snap.get("family") or {}
        self.family.setText((fam.get("name") or "").upper())
        self.cloud_offline = bool(snap.get("offline"))
        self.pending = int(snap.get("pending") or 0)
        self.update_status()
        self.rebuild_filter_combo()
        self.rebuild_sidebar()
        self.rebuild_rows()

    def rebuild_filter_combo(self):
        members = (self.snap or {}).get("members", [])
        key = (tuple(m.get("id") for m in members), self.filter_member)
        if key == self._filter_key:
            return
        self._filter_key = key
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem("Alle", None)
        self.filter_combo.addItem("Niemand", "none")
        for m in members:
            self.filter_combo.addItem(member_name(m), m["id"])
        idx = self.filter_combo.findData(self.filter_member) if self.filter_member is not None else 0
        if idx < 0:
            self.filter_member = None
            idx = 0
        self.filter_combo.setCurrentIndex(idx)
        self.filter_combo.blockSignals(False)

    def filter_changed(self, idx):
        self.filter_member = self.filter_combo.currentData()
        self.rebuild_rows()

    def update_filter_visibility(self):
        show = self.view == "task"
        self.filter_caption.setVisible(show)
        self.filter_combo.setVisible(show)

    def task_matches_filter(self, task):
        private = {l.get("id") for l in (self.snap or {}).get("lists", []) if l.get("is_private")}
        if task.get("list_id") in private:
            return True
        ids = task.get("assignee_member_ids") or []
        if self.filter_member is None:
            return True
        if self.filter_member == "none":
            return not ids
        return self.filter_member in ids

    def task_lists(self):
        return [l for l in (self.snap or {}).get("lists", []) if not l.get("archived_at")]

    def shopping_lists(self):
        return list((self.snap or {}).get("shopping_lists", []))

    def pick_list(self):
        if self.view == "task":
            lists = self.task_lists()
            if self.list_id and any(l["id"] == self.list_id for l in lists):
                return self.list_id
            default = [l for l in lists if l.get("is_default")] or lists
            return default[0]["id"] if default else None
        lists = self.shopping_lists()
        if self.list_id and any(l["id"] == self.list_id for l in lists):
            return self.list_id
        return lists[0]["id"] if lists else None

    def rebuild_sidebar(self):
        while self.side.count():
            item = self.side.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        counts = {}
        for t in (self.snap or {}).get("tasks", []):
            if not t.get("is_completed") and not t.get("parent_task_id"):
                counts[t.get("list_id")] = counts.get(t.get("list_id"), 0) + 1
        shopcounts = {}
        for sl in self.shopping_lists():
            shopcounts[sl["id"]] = sum(1 for i in sl.get("items", []) if not i.get("is_checked"))
        lab = QLabel("AUFGABEN")
        lab.setObjectName("section")
        self.side.addWidget(lab)
        active = self.pick_list()
        for l in self.task_lists():
            b = QPushButton(l.get("title") + ("  (%d)" % counts.get(l["id"], 0) if counts.get(l["id"]) else ""))
            b.setObjectName("side")
            b.setCheckable(True)
            b.setChecked(self.view == "task" and l["id"] == active)
            b.clicked.connect(lambda _=False, lid=l["id"]: self.open_list("task", lid))
            self.side.addWidget(b)
        lab2 = QLabel("EINKAUF")
        lab2.setObjectName("section")
        self.side.addWidget(lab2)
        for sl in self.shopping_lists():
            b = QPushButton(sl.get("title") + ("  (%d)" % shopcounts.get(sl["id"], 0) if shopcounts.get(sl["id"]) else ""))
            b.setObjectName("side")
            b.setCheckable(True)
            b.setChecked(self.view == "shopping" and sl["id"] == active)
            b.clicked.connect(lambda _=False, lid=sl["id"]: self.open_list("shopping", lid))
            self.side.addWidget(b)
        self.side.addStretch(1)

    def open_list(self, view, list_id):
        self.view = view
        self.list_id = list_id
        self.done_open = False
        self.update_filter_visibility()
        self.rebuild_sidebar()
        self.rebuild_rows()

    def clear_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def rebuild_rows(self):
        if not self.snap:
            return
        self.clear_rows()
        lid = self.pick_list()
        self.list_id = lid
        members = self.snap.get("members", [])
        if self.view == "task":
            lst = next((l for l in self.task_lists() if l["id"] == lid), None)
            self.viewtitle.setText(lst.get("title") if lst else "Aufgaben")
            tasks = [t for t in self.snap.get("tasks", [])
                     if t.get("list_id") == lid and not t.get("parent_task_id") and self.task_matches_filter(t)]
            open_t = [t for t in tasks if not t.get("is_completed")]
            done_t = [t for t in tasks if t.get("is_completed")]
            open_t.sort(key=lambda t: (t.get("due_date") or "9999-12-31", t.get("position") or 0))
            done_t.sort(key=lambda t: t.get("completed_at") or "", reverse=True)
            if not open_t:
                self.rows_layout.addWidget(self.empty_label("Nichts offen. Sehr gut."))
                self.rows_layout.addStretch(1)
            else:
                for t in open_t:
                    row = TaskRow(t, members)
                    row.toggled.connect(self.toggle_task)
                    row.activated.connect(self.edit_task)
                    row.context.connect(self.task_menu)
                    self.rows_layout.addWidget(row)
                self.rows_layout.addStretch(1)
            if done_t:
                more = QPushButton(("▾  " if self.done_open else "▸  ") + "Erledigt (%d)" % len(done_t))
                more.setObjectName("ghost")
                more.setCursor(Qt.CursorShape.PointingHandCursor)
                more.clicked.connect(self.toggle_done)
                self.rows_layout.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
                if self.done_open:
                    for t in done_t:
                        row = TaskRow(t, members, done_style=True)
                        row.toggled.connect(self.toggle_task)
                        row.activated.connect(self.edit_task)
                        row.context.connect(self.task_menu)
                        self.rows_layout.addWidget(row)
        else:
            sl = next((s for s in self.shopping_lists() if s["id"] == lid), None)
            self.viewtitle.setText(sl.get("title") if sl else "Einkauf")
            items = list(sl.get("items", [])) if sl else []
            open_i = [i for i in items if not i.get("is_checked")]
            done_i = [i for i in items if i.get("is_checked")]
            open_i.sort(key=lambda i: i.get("position") or 0)
            if not open_i:
                self.rows_layout.addWidget(self.empty_label("Liste leer."))
                self.rows_layout.addStretch(1)
            else:
                for it in open_i:
                    row = ShoppingRow(it)
                    row.toggled.connect(self.toggle_item)
                    row.activated.connect(self.edit_item)
                    row.context.connect(self.item_menu)
                    self.rows_layout.addWidget(row)
                self.rows_layout.addStretch(1)
            if done_i:
                more = QPushButton(("▾  " if self.done_open else "▸  ") + "Erledigt (%d)" % len(done_i))
                more.setObjectName("ghost")
                more.clicked.connect(self.toggle_done)
                self.rows_layout.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
                if self.done_open:
                    for it in done_i:
                        row = ShoppingRow(it)
                        row.toggled.connect(self.toggle_item)
                        row.activated.connect(self.edit_item)
                        row.context.connect(self.item_menu)
                        self.rows_layout.addWidget(row)

    def empty_label(self, text):
        lab = QLabel(text)
        lab.setObjectName("due")
        return lab

    def toggle_done(self):
        self.done_open = not self.done_open
        self.rebuild_rows()

    def toggle_task(self, task):
        target = not task.get("is_completed")
        task["is_completed"] = target
        self.rebuild_rows()

        def work():
            try:
                res = self.api.complete_task(task["id"], target)
                if isinstance(res, dict) and res.get("outcome") in ("completed_until", "rolled_over"):
                    self.sig_note.emit("Für dieses Mal erledigt · wieder am " + (res.get("next_due_date") or ""))
            except Exception as e:
                self.show_error(str(e))
            self.fetch_now()
        threading.Thread(target=work, daemon=True).start()

    def toggle_item(self, item):
        target = not item.get("is_checked")
        item["is_checked"] = target

        def work():
            try:
                self.api.update_shopping_item(item["id"], {"is_checked": target})
            except Exception as e:
                self.show_error(str(e))
            self.fetch_now()
        threading.Thread(target=work, daemon=True).start()
        self.rebuild_rows()

    def task_menu(self, task, pos):
        menu = QMenu(self)
        a1 = menu.addAction("Bearbeiten")
        a2 = menu.addAction("Wieder öffnen" if task.get("is_completed") else "Abhaken")
        a3 = menu.addAction("Löschen")
        act = menu.exec(pos)
        if act == a1:
            self.edit_task(task)
        elif act == a2:
            self.toggle_task(task)
        elif act == a3:
            self.confirm_delete(task)

    def item_menu(self, item, pos):
        menu = QMenu(self)
        a1 = menu.addAction("Bearbeiten")
        a2 = menu.addAction("Löschen")
        act = menu.exec(pos)
        if act == a1:
            self.edit_item(item)
        elif act == a2:
            self.confirm_delete_item(item)

    def confirm_delete(self, task):
        if QMessageBox.question(self, "Löschen", "„%s“ löschen?" % task.get("title")) != QMessageBox.StandardButton.Yes:
            return

        def work():
            try:
                self.api.delete_task(task["id"])
            except Exception as e:
                self.show_error(str(e))
            self.fetch_now()
        threading.Thread(target=work, daemon=True).start()

    def confirm_delete_item(self, item):
        if QMessageBox.question(self, "Löschen", "„%s“ löschen?" % item.get("name")) != QMessageBox.StandardButton.Yes:
            return
        self.delete_item(item)

    def delete_item(self, item):
        def work():
            try:
                self.api.delete_shopping_item(item["id"])
            except Exception as e:
                self.show_error(str(e))
            self.fetch_now()
        threading.Thread(target=work, daemon=True).start()

    def compose(self, kind=None):
        if not self.snap:
            self.fetch_now()
            return
        kind = kind or self.view
        list_id = self.pick_list()
        dlg = ComposeDialog(self.snap, kind=kind, list_id=list_id, parent=self)
        dlg.submitted.connect(self.create_entry)
        dlg.exec()

    def quick_add(self, kind=None):
        if not self.snap:
            self.fetch_now()
            QTimer.singleShot(600, lambda: self.quick_add(kind))
            return
        self.compose(kind)

    def create_entry(self, body):
        kind = body.pop("_kind", "task")

        def work():
            try:
                if kind == "task":
                    self.api.create_task(body)
                else:
                    self.api.create_shopping_item(body)
            except Exception as e:
                self.show_error(str(e))
            self.fetch_now()
        threading.Thread(target=work, daemon=True).start()

    def edit_task(self, task):
        dlg = ComposeDialog(self.snap, task=task, parent=self)
        dlg.submitted.connect(lambda body: self.save_task(task, body))
        dlg.deleted.connect(lambda _: self.confirm_delete(task))
        dlg.exec()

    def save_task(self, task, body):
        body.pop("_kind", None)

        def work():
            try:
                self.api.update_task(task["id"], body)
            except Exception as e:
                self.show_error(str(e))
            self.fetch_now()
        threading.Thread(target=work, daemon=True).start()

    def edit_item(self, item):
        dlg = ComposeDialog(self.snap, item=item, parent=self)
        dlg.submitted.connect(lambda body: self.save_item(item, body))
        dlg.deleted.connect(lambda _: self.delete_item(item))
        dlg.exec()

    def save_item(self, item, body):
        body.pop("_kind", None)
        body.pop("list_id", None)

        def work():
            try:
                self.api.update_shopping_item(item["id"], body)
            except Exception as e:
                self.show_error(str(e))
            self.fetch_now()
        threading.Thread(target=work, daemon=True).start()

    def show_note(self, text):
        if self.tray is not None:
            self.tray.showMessage("Famagic", text, make_icon(), 4000)
        self.status.setText(text)
        self.status.setStyleSheet("color: %s;" % AMBER)
        QTimer.singleShot(6000, lambda: self.set_online("online" if self.online else "offline"))

    def show_error(self, msg):
        self.status.setText("Fehler")
        self.status.setStyleSheet("color: %s;" % RED)
        self.status.setToolTip(msg)


def make_icon(size=64):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(AMBER))
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
    pen = QPen(QColor("#141414"), size * 0.09)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(size * 0.28, size * 0.52)
    path.lineTo(size * 0.44, size * 0.68)
    path.lineTo(size * 0.74, size * 0.34)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def write_icon(path):
    icon = make_icon(256)
    pm = icon.pixmap(256, 256)
    pm.save(path, "PNG")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick-add", nargs="?", const="auto", choices=["auto", "task", "shopping"])
    ap.add_argument("--hidden", action="store_true")
    ap.add_argument("--write-icon")
    ap.add_argument("--screenshot")
    args = ap.parse_args()
    if args.write_icon:
        app = QApplication(sys.argv[:1])
        write_icon(args.write_icon)
        return
    app = QApplication(sys.argv)
    app.setApplicationName("famagic")
    app.setDesktopFileName("famagic-desktop")
    app.setWindowIcon(make_icon())
    app.setStyleSheet(QSS)

    socket_name = APP_ID + "-" + str(os.getuid())
    sock = QLocalSocket()
    sock.connectToServer(socket_name)
    if sock.waitForConnected(200):
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(200)
        return
    server = QLocalServer()
    server.removeServer(socket_name)
    server.listen(socket_name)

    win = FamagicWindow(Api(client_config()), start_quick_add=args.quick_add is not None)
    server.newConnection.connect(lambda: handle_connection(server, win))
    app.aboutToQuit.connect(win.stop_sse)
    if args.quick_add:
        win.hide()
    elif args.hidden and win.tray is not None:
        win.hide()
    else:
        win.show()
    if args.screenshot:
        def grab():
            win.showNormal()
            win.resize(760, 720)
            QApplication.processEvents()
            win.grab().save(args.screenshot, "PNG")
            QApplication.quit()
        QTimer.singleShot(2500, grab)
    app.exec()


def handle_connection(server, win):
    conn = server.nextPendingConnection()
    if conn is None:
        return
    conn.waitForReadyRead(200)
    data = bytes(conn.readAll()).decode("utf-8", "replace")
    if "show" in data:
        win.show_window()
    conn.disconnectFromServer()


if __name__ == "__main__":
    main()
