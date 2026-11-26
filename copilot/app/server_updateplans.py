"""Updatepläne: ein Zeitplan für mehrere Server (ab 0.69.0).

Ein Plan legt Umfang, Wochentag, Zeitfenster (zum Beispiel 02:00 bis 03:00) und Karenzzeit für alle seine Server fest. Die Server
kommen **nacheinander** dran: der Hub verteilt sie gleichmäßig über das Fenster (zehn Server in 60 Minuten: alle 6 Minuten einer),
und es läuft immer nur ein Server des Plans gleichzeitig. Schafft ein Server sein Zeitfenster nicht, wird er nicht außerhalb davon
aktualisiert, sondern übersprungen und gemeldet.

Was dem Server gehört, bleibt bei ihm: die Ausnahmen je Paket und sein eigener Zeitplan. Solange ein Server in einem Plan ist,
ersetzt der Plan den eigenen Zeitplan (der bleibt gespeichert, pausiert). Ein Server gehört zu höchstens einem Plan und kann im Plan
pausiert werden. Dieses Modul kennt nur Plan und Zeit; Regeln, Läufe und Prüfung stehen in ``server_autoupdate.py``.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .i18n import tr
from .servers import ServerError, _json, _now, clean_text

if TYPE_CHECKING:
    from .server_autoupdate import AutoUpdate

MODES = ("security", "all")
EVERY_DAY = 7  # weekday: 0 = Montag … 6 = Sonntag, 7 = täglich
GRACE_MAX_DAYS = 14
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_PLAN_ID = re.compile(r"^[a-z0-9-]{1,40}$")

NAME_MAX = 60
PLANS_MAX = 20
SERVERS_MAX = 100
WINDOW_MIN = 10  # Minuten
WINDOW_MAX = 720


# ------------------------------------------------------------------------------------------------ Zeitrechnung


def _slot_time(day: datetime, at: str) -> datetime:
    hour, minute = int(at[:2]), int(at[3:])
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def minutes_of(at: str) -> int:
    return int(at[:2]) * 60 + int(at[3:])


def window_length(start: str, end: str) -> int:
    """Länge des Fensters in Minuten; ein Fenster darf über Mitternacht gehen (23:00 bis 01:00 = 120)."""
    return (minutes_of(end) - minutes_of(start)) % 1440


def last_slot(now: datetime, weekday: int, at: str, offset: int = 0) -> datetime:
    """Der letzte geplante Zeitpunkt, der nicht in der Zukunft liegt. ``offset``: Minuten nach dem Beginn des Fensters (Plan-Server)."""
    base = _slot_time(now, at)
    for back in range(9):
        start = base - timedelta(days=back)
        if weekday != EVERY_DAY and start.weekday() != weekday:
            continue
        candidate = start + timedelta(minutes=offset)
        if candidate <= now:
            return candidate
    return base + timedelta(minutes=offset)


def next_slot(now: datetime, weekday: int, at: str, offset: int = 0) -> datetime:
    base = _slot_time(now, at)
    for ahead in range(-1, 9):  # -1: ein Fenster von gestern kann mit seinem Versatz noch in der Zukunft liegen
        start = base + timedelta(days=ahead)
        if weekday != EVERY_DAY and start.weekday() != weekday:
            continue
        candidate = start + timedelta(minutes=offset)
        if candidate > now:
            return candidate
    return base + timedelta(days=7, minutes=offset)


def slot_key(moment: datetime) -> str:
    return moment.isoformat(timespec="minutes")


def offsets(plan: dict[str, Any], members: list[dict[str, Any]]) -> dict[str, int]:
    """Minuten nach Fensterbeginn je Server: gleichmäßig verteilt, in der Reihenfolge des Plans; pausierte Server zählen nicht mit."""
    active = [m for m in members if not m["paused"]]
    length = window_length(plan["window_start"], plan["window_end"])
    return {m["server_id"]: (length * i) // len(active) for i, m in enumerate(active)}


# ------------------------------------------------------------------------------------------------ Pläne


class UpdatePlans:
    """Pläne und ihre Server (Tabellen ab Schema 39)."""

    def __init__(self, auto: AutoUpdate) -> None:
        self.auto = auto
        self.hub = auto.hub

    def _q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return self.hub.repo._q(sql, args)

    def _x(self, sql: str, args: tuple = ()) -> int:
        return self.hub.repo._x(sql, args)

    # -- Lesen

    def get(self, plan_id: str) -> dict[str, Any] | None:
        if not isinstance(plan_id, str) or not _PLAN_ID.match(plan_id):
            return None
        rows = self._q("SELECT * FROM server_update_plans WHERE id = ?", (plan_id,))
        if not rows:
            return None
        rows[0]["enabled"] = bool(rows[0]["enabled"])
        return rows[0]

    def _need(self, plan_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan is None:
            raise ServerError(tr("Diesen Updateplan kenne ich nicht."), 404)
        return plan

    def all(self) -> list[dict[str, Any]]:
        rows = self._q("SELECT * FROM server_update_plans ORDER BY name COLLATE NOCASE, created_at")
        for row in rows:
            row["enabled"] = bool(row["enabled"])
        return rows

    def members(self, plan_id: str) -> list[dict[str, Any]]:
        rows = self._q("SELECT server_id, position, paused FROM server_update_plan_members WHERE plan_id = ? ORDER BY position, rowid", (plan_id,))
        for row in rows:
            row["paused"] = bool(row["paused"])
        return rows

    def membership(self, server_id: str) -> dict[str, Any] | None:
        """Zu welchem Plan gehört der Server, mit seinem Versatz im Fenster? ``None``, wenn er keinem angehört."""
        rows = self._q("SELECT plan_id, paused FROM server_update_plan_members WHERE server_id = ?", (server_id,))
        if not rows:
            return None
        plan = self.get(rows[0]["plan_id"])
        if plan is None:  # verwaiste Zeile (sollte es nicht geben)
            return None
        members = self.members(plan["id"])
        shifts = offsets(plan, members) if any(not m["paused"] for m in members) else {}
        active = [m for m in members if not m["paused"]]
        return {
            "plan": plan, "paused": bool(rows[0]["paused"]), "offset": shifts.get(server_id, 0),
            "position": next((i for i, m in enumerate(active) if m["server_id"] == server_id), -1), "count": len(active),
            "length": window_length(plan["window_start"], plan["window_end"]),
        }

    def scheduled_ids(self) -> list[str]:
        """Server, für die ein Lauf geplant ist: Plan-Server eingeschalteter Pläne (nicht pausiert) und Server mit eigenem Zeitplan außerhalb von Plänen."""
        ids = [r["server_id"] for r in self._q(
            "SELECT m.server_id FROM server_update_plan_members m JOIN server_update_plans p ON p.id = m.plan_id"
            " WHERE p.enabled = 1 AND m.paused = 0 ORDER BY m.plan_id, m.position, m.rowid")]
        ids += [r["server_id"] for r in self._q(
            "SELECT a.server_id FROM server_autoupdate a WHERE a.enabled = 1"
            " AND a.server_id NOT IN (SELECT server_id FROM server_update_plan_members)")]
        return ids

    def server_info(self, server_id: str) -> dict[str, Any] | None:
        """Kurzfassung für die Karte und das Fenster eines Servers."""
        found = self.membership(server_id)
        if found is None:
            return None
        plan = found["plan"]
        slot = (_slot_time(datetime(2000, 1, 1), plan["window_start"]) + timedelta(minutes=found["offset"])).strftime("%H:%M")
        return {
            "id": plan["id"], "name": plan["name"], "enabled": plan["enabled"], "paused": found["paused"], "mode": plan["mode"], "weekday": plan["weekday"],
            "window_start": plan["window_start"], "window_end": plan["window_end"], "grace_days": plan["grace_days"],
            "slot": slot, "position": found["position"], "count": found["count"],
        }

    def view(self, plan: dict[str, Any]) -> dict[str, Any]:
        now = self.auto.clock()
        members = self.members(plan["id"])
        shifts = offsets(plan, members) if any(not m["paused"] for m in members) else {}
        next_start = next_slot(now, plan["weekday"], plan["window_start"])
        out_members = []
        for m in members:
            row = self.hub.repo.server_get(m["server_id"])
            if row is None:
                continue
            offset = shifts.get(m["server_id"])
            slot = next_slot(now, plan["weekday"], plan["window_start"], offset) if offset is not None and plan["enabled"] else None
            out_members.append({
                "id": row["id"], "name": row["name"], "status": self.hub.status_of(row)[0], "paused": m["paused"],
                "slot": (_slot_time(datetime(2000, 1, 1), plan["window_start"]) + timedelta(minutes=offset)).strftime("%H:%M") if offset is not None else "",
                "next_run": slot_key(slot) if slot else "", "can_change": self.hub.can_change(row),
                "denied_locally": bool(_json(row["info"]).get("auto_update_denied")), "autoupdate": self.auto.brief(row["id"]),
            })
        length = window_length(plan["window_start"], plan["window_end"])
        active = sum(1 for m in out_members if not m["paused"])
        return {
            "id": plan["id"], "name": plan["name"], "enabled": plan["enabled"], "mode": plan["mode"], "weekday": plan["weekday"],
            "window_start": plan["window_start"], "window_end": plan["window_end"], "grace_days": plan["grace_days"], "length": length,
            "per_server": (length // active) if active else None,
            "next_start": slot_key(next_start) if plan["enabled"] else "", "skip_next": plan["skip_slot"] == slot_key(next_start),
            "members": out_members,
        }

    def listing(self) -> dict[str, Any]:
        """Alles für den Reiter „Automatische Updates“: die Pläne mit ihren Servern und die Server mit ihrem Stand."""
        member_of = {r["server_id"]: r for r in self._q("SELECT server_id, plan_id, paused FROM server_update_plan_members")}
        names = {p["id"]: p["name"] for p in self.all()}
        servers = []
        for row in self.hub.repo.server_list():
            if row["state"] != "active":
                continue
            link = member_of.get(row["id"])
            info = _json(row["info"])
            servers.append({
                "id": row["id"], "name": row["name"], "status": self.hub.status_of(row)[0], "can_change": self.hub.can_change(row),
                "denied_locally": bool(info.get("auto_update_denied")), "agent_version": info.get("agent_version") or "",
                "plan": {"id": link["plan_id"], "name": names.get(link["plan_id"], ""), "paused": bool(link["paused"])} if link else None,
                "autoupdate": self.auto.brief(row["id"]),
            })
        return {"plans": [self.view(p) for p in self.all()], "servers": servers, "limits": {"window_min": WINDOW_MIN, "window_max": WINDOW_MAX, "plans_max": PLANS_MAX}}

    # -- Prüfen

    @staticmethod
    def _clean(data: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if "name" in data:
            name = clean_text(data["name"], NAME_MAX)
            if not name:
                raise ServerError(tr("Der Plan braucht einen Namen."))
            values["name"] = name
        if "mode" in data:
            if data["mode"] not in MODES:
                raise ServerError(tr("Der Umfang muss „nur Sicherheit“ oder „alle“ sein."))
            values["mode"] = data["mode"]
        if "weekday" in data:
            if isinstance(data["weekday"], bool) or not isinstance(data["weekday"], int) or not 0 <= data["weekday"] <= EVERY_DAY:
                raise ServerError(tr("Der Wochentag ist ungültig."))
            values["weekday"] = data["weekday"]
        for key in ("window_start", "window_end"):
            if key in data:
                if not isinstance(data[key], str) or not _TIME.match(data[key]):
                    raise ServerError(tr("Die Uhrzeit muss im Format HH:MM angegeben werden."))
                values[key] = data[key]
        if "grace_days" in data:
            if isinstance(data["grace_days"], bool) or not isinstance(data["grace_days"], int) or not 0 <= data["grace_days"] <= GRACE_MAX_DAYS:
                raise ServerError(tr("Die Karenzzeit muss zwischen 0 und {n} Tagen liegen.", n=GRACE_MAX_DAYS))
            values["grace_days"] = data["grace_days"]
        if "enabled" in data:
            if not isinstance(data["enabled"], bool):
                raise ServerError(tr("Der Schalter muss ein/aus sein."))
            values["enabled"] = data["enabled"]
        merged = {**(current or {"window_start": "02:00", "window_end": "03:00"}), **values}
        length = window_length(merged["window_start"], merged["window_end"])
        if length < WINDOW_MIN or length > WINDOW_MAX:
            raise ServerError(tr("Das Zeitfenster muss zwischen {low} Minuten und {high} Stunden lang sein.", low=WINDOW_MIN, high=WINDOW_MAX // 60))
        return values

    def _server_ids(self, ids: Any) -> list[str]:
        if not isinstance(ids, list) or len(ids) > SERVERS_MAX:
            raise ServerError(tr("Die Serverliste ist ungültig."))
        out: list[str] = []
        for ref in ids:
            row = self.auto._row(str(ref))
            if row["id"] not in out:
                out.append(row["id"])
        return out

    # -- Ändern

    def _log(self, summary: str, actor: str, detail: str = "", row: dict[str, Any] | None = None) -> None:
        self.hub.repo.audit_add("event", summary, server_id=row["id"] if row else "", server_name=row["name"] if row else "", actor=actor, result="ok", detail=detail)

    def _reset_slots(self, plan_id: str, actor: str = "") -> None:
        """Nach einer Änderung von Zeit oder Servern: kein Lauf für einen Zeitpunkt, der schon vorbei ist."""
        plan = self.get(plan_id)
        if plan is None:
            return
        members = self.members(plan_id)
        shifts = offsets(plan, members) if any(not m["paused"] for m in members) else {}
        now = self.auto.clock()
        for m in members:
            if m["paused"]:
                continue
            key = slot_key(last_slot(now, plan["weekday"], plan["window_start"], shifts.get(m["server_id"], 0)))
            self.auto.repo.save(m["server_id"], {"last_slot": key, "skip_slot": ""}, actor)

    def _reset_own(self, server_id: str, actor: str) -> None:
        """Der Server kehrt zu seinem eigenen Zeitplan zurück: nichts nachholen, was inzwischen vorbei ist."""
        own = self.auto.repo.settings(server_id)
        self.auto.repo.save(server_id, {"last_slot": slot_key(last_slot(self.auto.clock(), own["weekday"], own["at_time"])), "skip_slot": ""}, actor)

    def _join_check(self, row: dict[str, Any]) -> None:
        if row["state"] != "active":
            raise ServerError(tr("Der Server {name} ist noch nicht bestätigt.", name=row["name"]), 409)
        self.auto._check_enable(row)
        self.auto._check_agent(row)

    def _put_members(self, plan_id: str, ids: list[str], actor: str, *, check_new: bool = True) -> None:
        """Die Server eines Plans setzen (Reihenfolge = Reihenfolge der Liste). Wer schon im Plan war, behält seinen Pausenzustand."""
        before = {m["server_id"]: m for m in self.members(plan_id)}
        touched = {plan_id}
        for sid in ids:
            if sid in before:
                continue
            row = self.hub.repo.server_get(sid)
            if row is None:
                continue
            if check_new:
                self._join_check(row)
            old = self._q("SELECT plan_id FROM server_update_plan_members WHERE server_id = ?", (sid,))
            if old:
                touched.add(old[0]["plan_id"])
            self._x("DELETE FROM server_update_plan_members WHERE server_id = ?", (sid,))
            self._x("INSERT INTO server_update_plan_members (server_id, plan_id, position, paused, added_at) VALUES (?, ?, ?, 0, ?)", (sid, plan_id, len(before) + 1000, _now()))
        for sid in set(before) - set(ids):
            self._x("DELETE FROM server_update_plan_members WHERE server_id = ?", (sid,))
            self._reset_own(sid, actor)
        for position, sid in enumerate(ids):
            self._x("UPDATE server_update_plan_members SET position = ? WHERE server_id = ? AND plan_id = ?", (position, sid, plan_id))
        for pid in touched:
            self._reset_slots(pid, actor)

    def create(self, data: dict[str, Any], actor: str) -> dict[str, Any]:
        if len(self.all()) >= PLANS_MAX:
            raise ServerError(tr("Es gibt schon {n} Updatepläne. Bitte erst einen löschen.", n=PLANS_MAX), 409)
        if "name" not in data:
            raise ServerError(tr("Der Plan braucht einen Namen."))
        values = self._clean(data, None)
        ids = self._server_ids(data["servers"]) if "servers" in data else []
        for sid in ids:
            row = self.hub.repo.server_get(sid)
            if row is not None:
                self._join_check(row)
        plan_id = "plan-" + uuid.uuid4().hex[:10]
        merged = {"name": "", "enabled": False, "mode": "security", "weekday": EVERY_DAY, "window_start": "02:00", "window_end": "03:00", "grace_days": 0, **values}
        self._x(
            "INSERT INTO server_update_plans (id, name, enabled, mode, weekday, window_start, window_end, grace_days, created_at, updated_at, updated_by)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plan_id, merged["name"], 1 if merged["enabled"] else 0, merged["mode"], merged["weekday"], merged["window_start"], merged["window_end"],
             merged["grace_days"], _now(), _now(), actor[:80]),
        )
        self._put_members(plan_id, ids, actor, check_new=False)
        self._log(tr("Updateplan angelegt: {name}", name=merged["name"]), actor, self.describe(self._need(plan_id)))
        return self.view(self._need(plan_id))

    def update(self, plan_id: str, data: dict[str, Any], actor: str) -> dict[str, Any]:
        plan = self._need(plan_id)
        values = self._clean(data, plan)
        ids = self._server_ids(data["servers"]) if "servers" in data else None
        sets = {**values}
        if sets:
            columns = ", ".join(f"{k} = ?" for k in sets)
            args = tuple((1 if v else 0) if k == "enabled" else v for k, v in sets.items())
            self._x(f"UPDATE server_update_plans SET {columns}, updated_at = ?, updated_by = ? WHERE id = ?", (*args, _now(), actor[:80], plan_id))  # noqa: S608 (feste Spaltennamen aus _clean)
        if ids is not None:
            self._put_members(plan_id, ids, actor)
        schedule_changed = ids is not None or any(k in values for k in ("weekday", "window_start", "window_end")) or (values.get("enabled") and not plan["enabled"])
        if schedule_changed:
            self._reset_slots(plan_id, actor)
            self._x("UPDATE server_update_plans SET skip_slot = '' WHERE id = ?", (plan_id,))
        if values or ids is not None:
            self._log(tr("Updateplan geändert: {name}", name=self._need(plan_id)["name"]), actor, self.describe(self._need(plan_id)))
        return self.view(self._need(plan_id))

    def delete(self, plan_id: str, actor: str) -> None:
        plan = self._need(plan_id)
        for m in self.members(plan_id):
            self._reset_own(m["server_id"], actor)
        self._x("DELETE FROM server_update_plan_members WHERE plan_id = ?", (plan_id,))
        self._x("DELETE FROM server_update_plans WHERE id = ?", (plan_id,))
        self._log(tr("Updateplan gelöscht: {name}", name=plan["name"]), actor)

    def set_skip(self, plan_id: str, skip: bool, actor: str) -> dict[str, Any]:
        plan = self._need(plan_id)
        if not plan["enabled"]:
            raise ServerError(tr("Der Updateplan ist nicht eingeschaltet."), 409)
        key = slot_key(next_slot(self.auto.clock(), plan["weekday"], plan["window_start"]))
        self._x("UPDATE server_update_plans SET skip_slot = ? WHERE id = ?", (key if skip else "", plan_id))
        self._log(tr("Nächsten Lauf des Plans {name} überspringen", name=plan["name"]) if skip else tr("Nächsten Lauf des Plans {name} wieder einplanen", name=plan["name"]), actor, key)
        return self.view(self._need(plan_id))

    # -- Ein Server

    def join(self, ref: str, plan_id: str, actor: str) -> dict[str, Any]:
        row = self.auto._row(ref)
        plan = self._need(plan_id)
        self._join_check(row)
        members = [m["server_id"] for m in self.members(plan_id)]
        if row["id"] not in members:
            self._put_members(plan_id, [*members, row["id"]], actor)
            self._log(tr("Server zum Updateplan {name} hinzugefügt", name=plan["name"]), actor, "", row)
        return self.auto.view(row["id"])

    def leave(self, ref: str, use_own: bool, actor: str) -> dict[str, Any]:
        """Den Server aus seinem Plan nehmen. Mit ``use_own`` schaltet er danach seinen eigenen Zeitplan ein, sonst bleibt dieser, wie er war."""
        row = self.auto._row(ref)
        found = self.membership(row["id"])
        if found is None:
            raise ServerError(tr("Der Server {name} gehört zu keinem Updateplan.", name=row["name"]), 409)
        if use_own:
            self.auto._check_enable(row)
        plan = found["plan"]
        self._x("DELETE FROM server_update_plan_members WHERE server_id = ?", (row["id"],))
        self._reset_own(row["id"], actor)
        self._reset_slots(plan["id"], actor)
        if use_own:
            self.auto.save_settings(row["id"], {"enabled": True}, actor)
        self._log(tr("Server aus dem Updateplan {name} genommen", name=plan["name"]), actor, tr("eigener Zeitplan eingeschaltet") if use_own else "", row)
        return self.auto.view(row["id"])

    def pause(self, ref: str, paused: bool, actor: str) -> dict[str, Any]:
        row = self.auto._row(ref)
        found = self.membership(row["id"])
        if found is None:
            raise ServerError(tr("Der Server {name} gehört zu keinem Updateplan.", name=row["name"]), 409)
        if not paused:
            self._join_check(row)
        self._x("UPDATE server_update_plan_members SET paused = ? WHERE server_id = ?", (1 if paused else 0, row["id"]))
        self._reset_slots(found["plan"]["id"], actor)
        plan = found["plan"]
        self._log(tr("Server im Updateplan {name} pausiert", name=plan["name"]) if paused else tr("Server im Updateplan {name} wieder aktiv", name=plan["name"]), actor, "", row)
        return self.auto.view(row["id"])

    def forget(self, server_id: str) -> None:
        """Ein Server wurde entfernt: raus aus seinem Plan, die übrigen verteilen sich neu."""
        rows = self._q("SELECT plan_id FROM server_update_plan_members WHERE server_id = ?", (server_id,))
        self._x("DELETE FROM server_update_plan_members WHERE server_id = ?", (server_id,))
        for row in rows:
            self._reset_slots(row["plan_id"])

    @staticmethod
    def describe(plan: dict[str, Any]) -> str:
        days = [tr("Montag"), tr("Dienstag"), tr("Mittwoch"), tr("Donnerstag"), tr("Freitag"), tr("Samstag"), tr("Sonntag"), tr("täglich")]
        scope = tr("alle Updates") if plan["mode"] == "all" else tr("nur Sicherheitsupdates")
        state = tr("an") if plan["enabled"] else tr("aus")
        return f"{state}, {scope}, {days[plan['weekday']]} {plan['window_start']}–{plan['window_end']}" + (tr(", Karenzzeit {n} Tage", n=plan["grace_days"]) if plan["grace_days"] else "")
