"""Automatische Aktualisierung der Server (Systempakete und Sicherheitspatches), Etappe des Linux-Agenten ab 0.68.

Wer was tut:

* Der **Agent** liefert nur Tatsachen (Werkzeug ``update_candidates``: was ansteht, woher, ob es ein Sicherheitsupdate ist, ob etwas
  angehalten ist, was ein Trockenlauf entfernen würde) und führt am Ende über die gewohnte, geprüfte Paketaktion aus (Einstufung,
  Prüfsumme, lokale Richtlinie; ``auto_update=deny`` sperrt sie dort dauerhaft).
* Der **Hub** (dieses Modul) wendet die Regeln an, merkt sich die Einstellungen und Ausnahmen der Person, plant die Läufe und
  protokolliert. Die Regeln liegen hier und nicht im Agenten, damit sie sich mit dem Add-on ändern lassen, ohne alle Server zu
  aktualisieren.
* Die **KI im Chat** kann nichts davon einstellen: Es gibt dafür kein Werkzeug. Eingestellt wird nur in der Seite „Server“.

Grundsatz der Regeln: Was beim Einspielen Ärger machen kann (Kernel, Netzwerk, Datenbanken, Container, Server-Anwendungen, große
Versionssprünge, Drittquellen), wird nicht automatisch eingespielt, sondern mit Begründung zurückgehalten. Die Person kann jedes
zurückgehaltene Paket mit einem Schalter dazunehmen („nur diesmal“ oder „dauerhaft“) und jedes vorgesehene herausnehmen. Nicht
dazunehmen lässt sich, was technisch nicht geht (angehalten) oder etwas anderes entfernen würde.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .i18n import tr
from .server_updateplans import EVERY_DAY, GRACE_MAX_DAYS, MODES, UpdatePlans, _slot_time, _TIME, last_slot, next_slot, slot_key  # noqa: F401 (Namen bleiben hier erreichbar)
from .servers import ServerError, _json, _now, clean_text, parse_version

if TYPE_CHECKING:
    from .servers import ServerHub

log = logging.getLogger("copilot.autoupdate")

MIN_AGENT = (0, 68, 0)  # ab dieser Fassung kennt der Agent update_candidates und das Flag auto
CATCHUP_HOURS = 12  # so lange nach der geplanten Zeit wird ein verpasster Lauf noch nachgeholt (Server war aus, Add-on neu gestartet)
QUIET_RETRY_MINUTES = 30  # nach einer fehlgeschlagenen stillen Prüfung so lange nicht erneut versuchen
PREVIEW_MAX_AGE_HOURS = 12  # so alt darf die gespeicherte Prüfung werden, bevor sie im Hintergrund erneuert wird
DISK_MIN_MB = 1024  # darunter wird nicht automatisch aktualisiert
MAX_PACKAGES = 300
CANDIDATES_TIMEOUT = 150  # der Agent prüft je Paket per Trockenlauf (bis etwa 70 s)
RUNS_KEPT = 30
SETTLE_SECONDS = 20  # nach dem Einspielen kurz warten, bis Dienste neu gestartet sind, bevor verglichen wird
_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:\-]{0,99}$")
_FAILED_UNIT = re.compile(r"^\s*[●*×]?\s*([A-Za-z0-9:_.@\\-]+\.(?:service|socket|mount|automount|swap|timer|target|path|scope|slice))\b", re.M)

# ------------------------------------------------------------------------------------------------ Regeln

# (Kennung, Muster). Die Muster gelten für den ganzen Paketnamen. Reihenfolge = Reihenfolge der Gründe.
HOLD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("kernel", re.compile(
        r"^(linux-(image|headers|modules|modules-extra|signed|tools|cloud-tools|buildinfo)(-.+)?|linux-(generic|aws|azure|gcp|oem|hwe|kvm|lowlatency|raspi|virtual)(-.+)?"
        r"|kernel|kernel-(core|modules|modules-core|modules-extra|devel|headers|tools|uek.*|rt.*)|raspberrypi-kernel.*|proxmox-kernel.*|pve-kernel.*)$")),
    ("boot", re.compile(
        r"^(linux-firmware|firmware-.+|.+-firmware|.*microcode.*|dracut.*|initramfs-tools.*|grub.*|shim.*|systemd-boot.*|efibootmgr|u-boot.*|raspi-firmware|fwupd.*|dkms)$")),
    ("network", re.compile(
        r"^(network-manager.*|networkmanager.*|netplan.*|ifupdown.*|ifenslave|bridge-utils|systemd-networkd.*|wpasupplicant|wpa_supplicant|dhcpcd.*|isc-dhcp-client|dhclient|dhcp-client"
        r"|openvswitch.*|wireguard.*|openvpn|nftables|iptables.*|ufw|firewalld|keepalived|frr.*|bird.*|tailscale|zerotier-one)$")),
    ("database", re.compile(
        r"^(postgresql(-\d+)?|postgresql-server|mariadb-server.*|mysql-server.*|mysql-community-server.*|percona-server.*|mongodb-org.*|mongodb-server|redis(-server)?|valkey(-server)?"
        r"|influxdb2?|couchdb|elasticsearch|opensearch|clickhouse-server|cassandra|mssql-server)$")),
    ("container", re.compile(
        r"^(docker-ce.*|docker\.io|docker-compose-plugin|docker-buildx-plugin|docker-engine|containerd(\.io)?|runc|crun|podman|buildah|cri-o.*|kubelet|kubeadm|kubectl|kubernetes-.*|k3s.*|lxd|lxc.*|snapd)$")),
    ("virtual", re.compile(
        r"^(qemu-system.*|qemu-kvm|libvirt-daemon.*|virtualbox.*|proxmox-ve|pve-.+|xen-.+|zfs.*|zfsutils-linux|mdadm|ceph.*|glusterfs-server|drbd.*|open-iscsi|multipath-tools|nfs-kernel-server)$")),
    ("service", re.compile(
        r"^(nginx.*|apache2|apache2-bin|httpd|haproxy|traefik|caddy|squid|varnish|postfix|exim4.*|dovecot-.+|bind9|named|bind|unbound|dnsmasq|mosquitto|grafana|prometheus|zabbix-.+"
        r"|tomcat.*|php[0-9.]*-fpm|samba|smbd|nmbd|slapd|openldap-servers|sssd|freeipa-server|vsftpd|proftpd.*|nfs-utils|rsyslog|fail2ban|cups|jellyfin.*|plex.*)$")),
)
KERNEL_RE = HOLD_PATTERNS[0][1]
BOOT_RE = HOLD_PATTERNS[1][1]
_VERSION = re.compile(r"^(?:(\d+):)?(\d+)")


def version_parts(version: str) -> tuple[int, int] | None:
    match = _VERSION.match(version or "")
    return (int(match.group(1) or 0), int(match.group(2))) if match else None


def major_jump(old: str, new: str, *, ignore_epoch: bool = False) -> bool:
    """Springt die Hauptversion (oder die Epoche)? Datumsversionen wie 2024a oder 20240709 zählen nicht."""
    a, b = version_parts(old), version_parts(new)
    if a is None or b is None:
        return False
    if a[0] != b[0] and not ignore_epoch:
        return True
    if a[1] >= 1900 or b[1] >= 1900:
        return False
    return a[1] != b[1]


def reason(code: str, **values: Any) -> dict[str, str]:
    """Ein Grund mit Kennung (die Oberfläche kann danach gruppieren) und Text in der Sprache des Add-ons."""
    return {"code": code, "text": reason_text(code, **values)}


def reason_text(code: str, **v: Any) -> str:
    if code == "kernel":
        return tr("Kernel: wirkt erst nach einem Neustart")
    if code == "boot":
        return tr("Start-Komponente oder Firmware: nur mit Neustart sinnvoll")
    if code == "network":
        return tr("Netzwerk oder Firewall: ein Fehler kann den Server unerreichbar machen")
    if code == "database":
        return tr("Datenbank: wird beim Update neu gestartet")
    if code == "container":
        return tr("Container-Dienst: laufende Container können neu starten")
    if code == "virtual":
        return tr("Virtualisierung oder Speicher: braucht Planung")
    if code == "service":
        return tr("Server-Anwendung: wird beim Update neu gestartet, Verbindungen reißen kurz ab")
    if code == "major":
        return tr("Großer Versionssprung ({old} → {new})", old=v.get("old", ""), new=v.get("new", ""))
    if code == "third":
        return tr("Aus einer Drittquelle ({source}), nicht von der Distribution", source=v.get("source") or tr("Herkunft unbekannt"))
    if code == "pulls_kernel":
        return tr("Würde einen neuen Kernel mitinstallieren")
    if code == "held":
        return tr("Ist auf dem Server angehalten (apt-mark hold)")
    if code == "removes":
        return tr("Würde andere Pakete entfernen: {packages}", packages=v.get("packages", ""))
    if code == "scope":
        return tr("Kein Sicherheitsupdate (Einstellung: nur Sicherheit)")
    if code == "waiting":
        return tr("Wartet bis {date} (Karenzzeit)", date=v.get("date", ""))
    if code == "user_excluded":
        return tr("Von dir ausgenommen")
    if code == "user_included":
        return tr("Von dir dazugenommen")
    if code == "disk":
        return tr("Zu wenig freier Platz ({mb} MB)", mb=v.get("mb", 0))
    return code


def rule_hold(item: dict[str, Any], manager: str) -> list[dict[str, str]]:
    """Gründe, ein Paket nicht automatisch einzuspielen. Von der Person überstimmbar (nicht: angehalten, entfernt etwas)."""
    holds: list[dict[str, str]] = []
    name = item["name"]
    for code, pattern in HOLD_PATTERNS:
        if pattern.match(name):
            holds.append(reason(code))
            break
    if item.get("installed") and major_jump(item["installed"], item["candidate"], ignore_epoch=manager == "dnf"):
        holds.append(reason("major", old=item["installed"], new=item["candidate"]))
    if not item.get("official"):
        holds.append(reason("third", source=(item.get("origin") or item.get("archive") or "")[:60]))
    if any(KERNEL_RE.match(n) or BOOT_RE.match(n) for n in item.get("installs") or []) and not KERNEL_RE.match(name) and not BOOT_RE.match(name):
        holds.append(reason("pulls_kernel"))
    return holds


def rule_hard(item: dict[str, Any]) -> list[dict[str, str]]:
    """Gründe, die sich nicht überstimmen lassen."""
    hard: list[dict[str, str]] = []
    if item.get("held"):
        hard.append(reason("held"))
    removes = [n for n in item.get("removes") or [] if n]
    if removes:
        hard.append(reason("removes", packages=", ".join(removes[:5]) + (" …" if len(removes) > 5 else "")))
    return hard


def evaluate(report: dict[str, Any], settings: dict[str, Any], overrides: dict[str, dict[str, Any]], seen: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Aus den Tatsachen des Agenten, den Einstellungen und den Ausnahmen der Person die Liste „wird eingespielt / zurückgehalten“."""
    manager = str(report.get("manager") or "")
    items: list[dict[str, Any]] = []
    done: set[str] = set()
    for raw in report.get("updates") or []:
        name = str(raw.get("name") or "")
        if not _PACKAGE.match(name) or name in done:
            continue
        done.add(name)
        item = {
            "name": name, "arch": raw.get("arch") or "", "installed": raw.get("installed") or "", "candidate": raw.get("candidate") or "",
            "archive": raw.get("archive") or "", "origin": raw.get("origin") or "", "official": bool(raw.get("official")),
            "security": bool(raw.get("security")), "held": bool(raw.get("held")), "removes": list(raw.get("removes") or []),
            "installs": list(raw.get("installs") or []), "checked": bool(raw.get("checked")),
        }
        holds, hard = rule_hold(item, manager), rule_hard(item)
        over = overrides.get(name)
        waiting_until = ""
        grace = int(settings.get("grace_days") or 0)
        if grace > 0 and not item["security"]:
            first = _parse(seen.get(name, {}).get("first_seen"))
            if first is not None and seen.get(name, {}).get("candidate") == item["candidate"]:
                until = first + timedelta(days=grace)
                if until > now:
                    waiting_until = until.strftime("%Y-%m-%d")
        reasons: list[dict[str, str]] = []
        if over and over["decision"] == "exclude":
            status = "user_excluded"
            reasons = [reason("user_excluded")]
        elif hard:
            status, reasons = "hold", hard
        elif over and over["decision"] == "include":
            status, reasons = "include", [reason("user_included")]
        elif holds:
            status, reasons = "hold", holds
        elif settings.get("mode") != "all" and not item["security"]:
            status, reasons = "scope", [reason("scope")]
        elif waiting_until:
            status, reasons = "waiting", [reason("waiting", date=waiting_until)]
        else:
            status = "include"
        item.update(
            status=status, reasons=reasons, can_include=not hard, waiting_until=waiting_until,
            override=("once_" if over and over["once"] else "always_") + over["decision"] if over else "",
        )
        items.append(item)
    order = {"include": 0, "hold": 1, "waiting": 2, "scope": 3, "user_excluded": 4}
    items.sort(key=lambda i: (order.get(i["status"], 9), not i["security"], i["name"]))
    blocked: list[dict[str, str]] = []
    free = report.get("free_mb")
    if isinstance(free, int) and 0 <= free < DISK_MIN_MB:
        blocked.append(reason("disk", mb=free))
    return {
        "manager": manager, "items": items, "blocked": blocked, "more": int(report.get("more") or 0),
        "reboot_required": bool(report.get("reboot_required")), "free_mb": free if isinstance(free, int) else None,
        "counts": {k: sum(1 for i in items if i["status"] == k) for k in order},
        "note": str(report.get("note") or "")[:200],
    }


def selected(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in result["items"] if i["status"] == "include"][:MAX_PACKAGES]


# ------------------------------------------------------------------------------------------------ Zeitplan


def _parse(value: Any) -> datetime | None:
    """Ein gespeicherter Zeitpunkt (UTC mit Zeitzone) als lokale Zeit ohne Zeitzone, wie sie der Zeitplan benutzt."""
    try:
        moment = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    if moment is not None and moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


def failed_units(text: str) -> set[str]:
    return set(_FAILED_UNIT.findall(text or ""))


def run_failed(text: str) -> bool:
    return "== Result: failed" in text or "== Ergebnis: fehlgeschlagen" in text


# ------------------------------------------------------------------------------------------------ Ablage


class AutoUpdateRepo:
    """Einstellungen, Ausnahmen, „seit wann steht es an“ und Läufe in der Datenbank (Tabellen ab Schema 38)."""

    def __init__(self, hub: ServerHub) -> None:
        self._hub = hub

    def _q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return self._hub.repo._q(sql, args)

    def _x(self, sql: str, args: tuple = ()) -> int:
        return self._hub.repo._x(sql, args)

    def settings(self, server_id: str) -> dict[str, Any]:
        rows = self._q("SELECT * FROM server_autoupdate WHERE server_id = ?", (server_id,))
        row = rows[0] if rows else {
            "server_id": server_id, "enabled": 0, "mode": "security", "weekday": EVERY_DAY, "at_time": "03:30", "grace_days": 0,
            "last_slot": "", "skip_slot": "", "preview": "", "preview_at": None, "updated_at": None, "updated_by": "",
        }
        row["enabled"] = bool(row["enabled"])
        return row

    def save(self, server_id: str, values: dict[str, Any], actor: str) -> None:
        current = self.settings(server_id)
        merged = {**current, **values}
        self._x(
            "INSERT INTO server_autoupdate (server_id, enabled, mode, weekday, at_time, grace_days, last_slot, skip_slot, preview, preview_at, updated_at, updated_by)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(server_id) DO UPDATE SET enabled = excluded.enabled, mode = excluded.mode,"
            " weekday = excluded.weekday, at_time = excluded.at_time, grace_days = excluded.grace_days, last_slot = excluded.last_slot,"
            " skip_slot = excluded.skip_slot, preview = excluded.preview, preview_at = excluded.preview_at, updated_at = excluded.updated_at,"
            " updated_by = excluded.updated_by",
            (server_id, 1 if merged["enabled"] else 0, merged["mode"], merged["weekday"], merged["at_time"], merged["grace_days"], merged["last_slot"],
             merged["skip_slot"], merged["preview"], merged["preview_at"], _now(), actor[:80]),
        )

    def enabled_ids(self) -> list[str]:
        return [r["server_id"] for r in self._q("SELECT server_id FROM server_autoupdate WHERE enabled = 1")]

    def overrides(self, server_id: str) -> dict[str, dict[str, Any]]:
        return {r["package"]: {"decision": r["decision"], "once": bool(r["once"])}
                for r in self._q("SELECT package, decision, once FROM server_autoupdate_overrides WHERE server_id = ?", (server_id,))}

    def set_override(self, server_id: str, package: str, decision: str, once: bool) -> None:
        self._x(
            "INSERT INTO server_autoupdate_overrides (server_id, package, decision, once, created_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(server_id, package) DO UPDATE SET decision = excluded.decision, once = excluded.once, created_at = excluded.created_at",
            (server_id, package, decision, 1 if once else 0, _now()),
        )

    def clear_override(self, server_id: str, package: str) -> None:
        self._x("DELETE FROM server_autoupdate_overrides WHERE server_id = ? AND package = ?", (server_id, package))

    def clear_once(self, server_id: str) -> None:
        self._x("DELETE FROM server_autoupdate_overrides WHERE server_id = ? AND once = 1", (server_id,))

    def seen(self, server_id: str) -> dict[str, dict[str, Any]]:
        return {r["package"]: r for r in self._q("SELECT package, candidate, first_seen FROM server_autoupdate_seen WHERE server_id = ?", (server_id,))}

    def update_seen(self, server_id: str, candidates: dict[str, str]) -> None:
        """Was jetzt ansteht, mit der Fassung; Neues oder eine neuere Fassung beginnt die Karenzzeit von vorn, Erledigtes verschwindet."""
        known = self.seen(server_id)
        for name, version in candidates.items():
            if name not in known or known[name]["candidate"] != version:
                self._x(
                    "INSERT INTO server_autoupdate_seen (server_id, package, candidate, first_seen) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(server_id, package) DO UPDATE SET candidate = excluded.candidate, first_seen = excluded.first_seen",
                    (server_id, name, version, _now()),
                )
        for name in set(known) - set(candidates):
            self._x("DELETE FROM server_autoupdate_seen WHERE server_id = ? AND package = ?", (server_id, name))

    def run_start(self, server_id: str, trigger: str, actor: str) -> int:
        with self._hub.repo._store._lock, self._hub.repo._store._conn:
            cur = self._hub.repo._store._conn.execute(
                "INSERT INTO server_autoupdate_runs (server_id, started_at, trigger, actor) VALUES (?, ?, ?, ?)", (server_id, _now(), trigger, actor[:80]))
            return int(cur.lastrowid or 0)

    def run_finish(self, run_id: int, status: str, summary: str, detail: str = "", installed: list[dict[str, str]] | None = None,
                   held_back: int = 0, new_failed: list[str] | None = None, reboot: bool = False) -> None:
        self._x(
            "UPDATE server_autoupdate_runs SET finished_at = ?, status = ?, summary = ?, detail = ?, installed = ?, held_back = ?, new_failed = ?, reboot = ? WHERE id = ?",
            (_now(), status, summary[:300], detail[:1500], json.dumps(installed or [], ensure_ascii=False), held_back,
             json.dumps(new_failed or [], ensure_ascii=False), 1 if reboot else 0, run_id),
        )
        row = self._q("SELECT server_id FROM server_autoupdate_runs WHERE id = ?", (run_id,))
        if row:
            self._x("DELETE FROM server_autoupdate_runs WHERE server_id = ? AND id NOT IN (SELECT id FROM server_autoupdate_runs WHERE server_id = ? ORDER BY id DESC LIMIT ?)",
                    (row[0]["server_id"], row[0]["server_id"], RUNS_KEPT))

    def runs(self, server_id: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._q("SELECT * FROM server_autoupdate_runs WHERE server_id = ? ORDER BY id DESC LIMIT ?", (server_id, max(1, min(limit, RUNS_KEPT))))
        for row in rows:
            row["installed"] = json.loads(row["installed"] or "[]")
            row["new_failed"] = json.loads(row["new_failed"] or "[]")
            row["reboot"] = bool(row["reboot"])
        return rows

    def drop_server(self, server_id: str) -> None:
        for table in ("server_autoupdate", "server_autoupdate_overrides", "server_autoupdate_seen", "server_autoupdate_runs"):
            self._x(f"DELETE FROM {table} WHERE server_id = ?", (server_id,))  # noqa: S608 (feste Tabellennamen)


# ------------------------------------------------------------------------------------------------ Ablauf

Notifier = Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]


class AutoUpdate:
    """Einstellungen, Vorschau („was würde beim nächsten Lauf installiert“), Läufe und Zeitplan."""

    def __init__(self, hub: ServerHub, clock: Callable[[], datetime] = datetime.now) -> None:
        self.hub = hub
        self.repo = AutoUpdateRepo(hub)
        self.clock = clock
        self.settle = SETTLE_SECONDS
        self.on_result: Notifier | None = None  # Meldung nach einem Lauf (gesetzt von main.py)
        self._locks: dict[str, asyncio.Lock] = {}
        self._running: dict[str, dict[str, str]] = {}
        self._errors: dict[str, str] = {}  # letzte Fehlermeldung einer Prüfung im Hintergrund, bis zur nächsten Aktion (nur Arbeitsspeicher)
        self._tasks: set[asyncio.Task] = set()
        self._quiet_retry: dict[str, datetime] = {}  # frühester nächster Versuch der stillen Prüfung je Server
        self.plans = UpdatePlans(self)  # Updatepläne: ein Zeitplan für mehrere Server (ab 0.69.0)

    # -- Ansicht und Einstellungen

    def _lock(self, server_id: str) -> asyncio.Lock:
        return self._locks.setdefault(server_id, asyncio.Lock())

    def _row(self, ref: str) -> dict[str, Any]:
        row = self.hub.get(ref)
        if row is None:
            raise ServerError(tr("Diesen Server kenne ich nicht. Frag mit server_list nach den bekannten Servern."), 404)
        return row

    def effective(self, server_id: str) -> dict[str, Any]:
        """Was für diesen Server gilt: sein eigener Zeitplan oder, wenn er in einem Plan ist, der Plan (Umfang, Tag, Zeit im Fenster, Karenzzeit).
        ``enabled`` heißt hier: es ist ein Lauf geplant. Gespeichert bleiben immer beide; der eigene ruht, solange der Server im Plan ist."""
        own = self.repo.settings(server_id)
        found = self.plans.membership(server_id)
        if found is None:
            return {**own, "source": "own", "offset": 0, "length": 0, "plan": None}
        plan = found["plan"]
        return {
            **own, "source": "plan", "mode": plan["mode"], "weekday": plan["weekday"], "at_time": plan["window_start"], "grace_days": plan["grace_days"],
            "enabled": plan["enabled"] and not found["paused"], "offset": found["offset"], "length": found["length"], "plan": plan,
            "paused": found["paused"],
        }

    def _slot(self, eff: dict[str, Any], *, ahead: bool) -> datetime:
        fn = next_slot if ahead else last_slot
        return fn(self.clock(), eff["weekday"], eff["at_time"], eff["offset"])

    @staticmethod
    def _plan_skipped(eff: dict[str, Any], slot: datetime) -> bool:
        """Gilt „diesen Lauf überspringen“ für diesen Zeitpunkt (für den Server oder für den ganzen Plan)?"""
        if eff["skip_slot"] == slot_key(slot):
            return True
        return bool(eff["plan"]) and eff["plan"]["skip_slot"] == slot_key(slot - timedelta(minutes=eff["offset"]))

    def evaluated(self, server_id: str) -> dict[str, Any] | None:
        """Die zuletzt geprüfte Lage, mit den heutigen Einstellungen und Ausnahmen neu bewertet (Schalter wirken sofort, ohne den Server zu fragen)."""
        settings = self.effective(server_id)
        try:
            report = json.loads(settings["preview"]) if settings["preview"] else None
        except ValueError:
            report = None
        if not isinstance(report, dict):
            return None
        return evaluate(report, settings, self.repo.overrides(server_id), self.repo.seen(server_id), self.clock())

    def view(self, ref: str) -> dict[str, Any]:
        row = self._row(ref)
        sid = row["id"]
        settings = self.repo.settings(sid)
        eff = self.effective(sid)
        info = _json(row["info"])
        slot = self._slot(eff, ahead=True)
        skipped = self._plan_skipped(eff, slot)
        return {
            "server": {"id": sid, "name": row["name"]},
            "settings": {k: settings[k] for k in ("enabled", "mode", "weekday", "at_time", "grace_days")},  # die eigenen, auch wenn ein Plan gilt
            "plan": self.plans.server_info(sid), "plans": [{"id": p["id"], "name": p["name"]} for p in self.plans.all()],
            "effective": {k: eff[k] for k in ("enabled", "mode", "weekday", "at_time", "grace_days", "source")},
            "can_change": self.hub.can_change(row), "denied_locally": bool(info.get("auto_update_denied")),
            "supported": bool(info.get("os")),
            "next_run": slot_key(slot) if eff["enabled"] else "", "skip_next": skipped,
            "checked_at": settings["preview_at"], "preview": self.evaluated(sid),
            "running": self._running.get(sid), "error": self._errors.get(sid, ""), "runs": self.repo.runs(sid),
        }

    def brief(self, server_id: str) -> dict[str, Any]:
        """Kurzfassung für die Übersicht der Server (eine Zeile auf der Karte)."""
        eff = self.effective(server_id)
        result = self.evaluated(server_id) if eff["enabled"] else None
        last = self.repo.runs(server_id, 1)
        slot = self._slot(eff, ahead=True) if eff["enabled"] else None
        return {
            "enabled": eff["enabled"], "mode": eff["mode"], "next_run": slot_key(slot) if slot else "",
            "skip_next": bool(slot) and self._plan_skipped(eff, slot),
            "own_enabled": bool(eff["enabled"]) if eff["source"] == "own" else bool(self.repo.settings(server_id)["enabled"]),
            "plan": ({"id": eff["plan"]["id"], "name": eff["plan"]["name"], "paused": eff["paused"], "enabled": eff["plan"]["enabled"],
                      "slot": (self.plans.server_info(server_id) or {}).get("slot", "")} if eff["plan"] else None),
            "include": result["counts"]["include"] if result else None, "held": result["counts"]["hold"] if result else None,
            "last": {"status": last[0]["status"], "summary": last[0]["summary"], "at": last[0]["finished_at"] or last[0]["started_at"]} if last else None,
            "running": self._running.get(server_id),
        }

    def save_settings(self, ref: str, data: dict[str, Any], actor: str) -> dict[str, Any]:
        row = self._row(ref)
        sid = row["id"]
        current = self.repo.settings(sid)
        found = self.plans.membership(sid)
        if found is not None and any(k in data for k in ("enabled", "mode", "weekday", "at_time", "grace_days")):
            raise ServerError(tr("Der Server {name} folgt dem Updateplan {plan}. Ändere den Plan oder nimm den Server zuerst aus dem Plan.", name=row["name"], plan=found["plan"]["name"]), 409)
        values: dict[str, Any] = {}
        if "mode" in data:
            if data["mode"] not in MODES:
                raise ServerError(tr("Der Umfang muss „nur Sicherheit“ oder „alle“ sein."))
            values["mode"] = data["mode"]
        if "weekday" in data:
            if isinstance(data["weekday"], bool) or not isinstance(data["weekday"], int) or not 0 <= data["weekday"] <= EVERY_DAY:
                raise ServerError(tr("Der Wochentag ist ungültig."))
            values["weekday"] = data["weekday"]
        if "at_time" in data:
            if not isinstance(data["at_time"], str) or not _TIME.match(data["at_time"]):
                raise ServerError(tr("Die Uhrzeit muss im Format HH:MM angegeben werden."))
            values["at_time"] = data["at_time"]
        if "grace_days" in data:
            if isinstance(data["grace_days"], bool) or not isinstance(data["grace_days"], int) or not 0 <= data["grace_days"] <= GRACE_MAX_DAYS:
                raise ServerError(tr("Die Karenzzeit muss zwischen 0 und {n} Tagen liegen.", n=GRACE_MAX_DAYS))
            values["grace_days"] = data["grace_days"]
        enable = data.get("enabled")
        if enable is not None and not isinstance(enable, bool):
            raise ServerError(tr("Der Schalter muss ein/aus sein."))
        if enable:
            self._check_enable(row)
        if enable is not None:
            values["enabled"] = enable
        merged = {**current, **values}
        schedule_changed = any(k in values for k in ("weekday", "at_time")) or (enable and not current["enabled"])
        if schedule_changed:
            # Kein Lauf für einen Zeitpunkt, der schon vorbei ist; ein gemerktes „überspringen“ gilt nicht mehr für den neuen Zeitplan
            values["last_slot"] = slot_key(last_slot(self.clock(), merged["weekday"], merged["at_time"]))
            values["skip_slot"] = ""
        self.repo.save(sid, values, actor)
        if values:
            self._log(row, tr("Automatische Aktualisierung eingestellt"), actor, "ok", self._describe(self.repo.settings(sid)))
        return self.view(sid)

    def _check_enable(self, row: dict[str, Any]) -> None:
        """Darf für diesen Server überhaupt automatisch aktualisiert werden (lokale Richtlinie)?"""
        if _json(row["info"]).get("auto_update_denied"):
            raise ServerError(tr("Auf dem Server {name} ist die automatische Aktualisierung lokal gesperrt (auto_update=deny).", name=row["name"]), 403)
        if not self.hub.can_change(row):
            raise ServerError(tr("Auf dem Server {name} sind Änderungen nicht erlaubt (lokale Richtlinie ki_access). Ohne das kann ich dort nichts aktualisieren.", name=row["name"]), 403)

    @staticmethod
    def _describe(settings: dict[str, Any]) -> str:
        days = [tr("Montag"), tr("Dienstag"), tr("Mittwoch"), tr("Donnerstag"), tr("Freitag"), tr("Samstag"), tr("Sonntag"), tr("täglich")]
        scope = tr("alle Updates") if settings["mode"] == "all" else tr("nur Sicherheitsupdates")
        state = tr("an") if settings["enabled"] else tr("aus")
        return f"{state}, {scope}, {days[settings['weekday']]} {settings['at_time']}" + (tr(", Karenzzeit {n} Tage", n=settings["grace_days"]) if settings["grace_days"] else "")

    def set_package(self, ref: str, package: str, decision: str, once: bool, actor: str) -> dict[str, Any]:
        row = self._row(ref)
        if not _PACKAGE.match(package or ""):
            raise ServerError(tr("Das ist kein gültiger Paketname."))
        if decision == "clear":
            self.repo.clear_override(row["id"], package)
        elif decision in ("include", "exclude"):
            result = self.evaluated(row["id"])
            item = next((i for i in (result or {"items": []})["items"] if i["name"] == package), None)
            if decision == "include" and item is not None and not item["can_include"]:
                raise ServerError(tr("{package} lässt sich nicht automatisch einspielen: {why}", package=package, why=item["reasons"][0]["text"]), 409)
            self.repo.set_override(row["id"], package, decision, once)
        else:
            raise ServerError(tr("Die Entscheidung muss include, exclude oder clear sein."))
        self._log(row, tr("Automatische Aktualisierung: {package}", package=package), actor, "ok", f"{decision}{' (nur diesmal)' if once else ''}")
        return self.view(row["id"])

    def set_skip(self, ref: str, skip: bool, actor: str) -> dict[str, Any]:
        row = self._row(ref)
        eff = self.effective(row["id"])
        if not eff["enabled"]:
            raise ServerError(tr("Die automatische Aktualisierung ist für diesen Server nicht eingeschaltet."), 409)
        slot = slot_key(self._slot(eff, ahead=True))
        self.repo.save(row["id"], {"skip_slot": slot if skip else ""}, actor)
        self._log(row, tr("Nächsten Lauf überspringen") if skip else tr("Nächsten Lauf wieder einplanen"), actor, "ok", slot)
        return self.view(row["id"])

    def _log(self, row: dict[str, Any], summary: str, actor: str, result: str, detail: str = "", kind: str = "event") -> None:
        self.hub.repo.audit_add(kind, summary, server_id=row["id"], server_name=row["name"], actor=actor, result=result, detail=detail)

    # -- Prüfen

    async def _fetch(self, row: dict[str, Any], *, refresh_lists: bool, simulate: bool = True) -> dict[str, Any]:
        ref = row["id"]
        if refresh_lists:
            plan = await self.hub.prepare(ref, "package", {"action": "update"})
            text = await self.hub.execute(ref, plan)
            if run_failed(text):
                raise ServerError(tr("Die Paketlisten ließen sich nicht aktualisieren."), 502)
        text = await self.hub.call(ref, "update_candidates", {"simulate": simulate}, timeout=CANDIDATES_TIMEOUT)
        report = _json(text)
        if not isinstance(report.get("updates"), list):
            raise ServerError(tr("Der Server hat keine brauchbare Liste der Updates geliefert."), 502)
        return report

    def start_refresh(self, ref: str, actor: str) -> dict[str, Any]:
        """„Neu prüfen“ im Hintergrund starten (Paketlisten erneuern und alle Kandidaten per Trockenlauf prüfen dauert Minuten)."""
        row = self._row(ref)
        sid = row["id"]
        self.hub._connection(sid)
        self._check_agent(row)
        if not self.hub.can_change(row):
            raise ServerError(tr("Auf dem Server {name} sind Änderungen nicht erlaubt (lokale Richtlinie ki_access). Ohne das kann ich dort nichts aktualisieren.", name=row["name"]), 403)
        if self._lock(sid).locked() or sid in self._running:
            raise ServerError(tr("Auf diesem Server läuft gerade eine automatische Aktualisierung."), 409)
        self._errors.pop(sid, None)
        self._quiet_retry.pop(sid, None)
        self._running[sid] = {"phase": "check", "since": _now()}
        self._spawn(self.refresh(sid, actor, report_errors=True))
        return {"started": True}

    def _spawn(self, coroutine: Awaitable[Any]) -> None:
        task = asyncio.get_running_loop().create_task(coroutine)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def refresh(self, ref: str, actor: str, *, report_errors: bool = False) -> None:
        """Paketlisten aktualisieren, Kandidaten prüfen, Ergebnis merken (installiert nichts)."""
        row = self._row(ref)
        sid = row["id"]
        if self._lock(sid).locked():
            raise ServerError(tr("Auf diesem Server läuft gerade eine automatische Aktualisierung."), 409)
        async with self._lock(sid):
            self._running[sid] = {"phase": "check", "since": self._running.get(sid, {}).get("since") or _now()}
            try:
                report = await self._fetch(row, refresh_lists=True)
                self._store_report(sid, report, actor)
            except ServerError as exc:
                if not report_errors:
                    raise
                self._errors[sid] = str(exc)
            except Exception:  # noqa: BLE001
                if not report_errors:
                    raise
                log.warning("Prüfung der Updates von %s fehlgeschlagen", row["name"], exc_info=True)
                self._errors[sid] = tr("Unerwarteter Fehler beim Aktualisieren.")
            finally:
                self._running.pop(sid, None)

    def _store_report(self, server_id: str, report: dict[str, Any], actor: str = "") -> None:
        candidates = {str(u.get("name")): str(u.get("candidate")) for u in report.get("updates") or [] if u.get("name")}
        self.repo.update_seen(server_id, candidates)
        self.repo.save(server_id, {"preview": json.dumps(report, ensure_ascii=False, separators=(",", ":")), "preview_at": _now()}, actor or self.repo.settings(server_id)["updated_by"])

    # -- Lauf

    def start(self, ref: str, actor: str, trigger: str = "manual") -> dict[str, Any]:
        """Einen Lauf im Hintergrund starten („Jetzt installieren“); die Oberfläche fragt den Stand ab."""
        row = self._row(ref)
        sid = row["id"]
        self._check_runnable(row)
        if self._lock(sid).locked() or sid in self._running:
            raise ServerError(tr("Auf diesem Server läuft gerade eine automatische Aktualisierung."), 409)
        self._errors.pop(sid, None)
        self._running[sid] = {"phase": "start", "since": _now()}
        self._spawn(self._guarded(row, actor, trigger))
        return {"started": True}

    def _check_agent(self, row: dict[str, Any]) -> None:
        """Ein Agent vor 0.68.0 kennt weder die Prüfung noch das Flag ``auto``: verständlich abbrechen, statt einen rohen Fehler zu zeigen."""
        info = _json(row["info"])
        have = parse_version(str(info.get("agent_version") or ""))
        if have is not None and have < MIN_AGENT:
            raise ServerError(tr("Der Agent auf {name} ({version}) ist zu alt für automatische Updates. Bitte zuerst den Agenten aktualisieren.", name=row["name"], version=info.get("agent_version")), 409)

    def _check_runnable(self, row: dict[str, Any]) -> None:
        info = _json(row["info"])
        self.hub._connection(row["id"])  # offline / gesperrt / unbestätigt → verständliche Meldung
        self._check_agent(row)
        if info.get("auto_update_denied"):
            raise ServerError(tr("Auf dem Server {name} ist die automatische Aktualisierung lokal gesperrt (auto_update=deny).", name=row["name"]), 403)
        if not self.hub.can_change(row):
            raise ServerError(tr("Auf dem Server {name} sind Änderungen nicht erlaubt (lokale Richtlinie ki_access). Ohne das kann ich dort nichts aktualisieren.", name=row["name"]), 403)

    async def _guarded(self, row: dict[str, Any], actor: str, trigger: str) -> None:
        sid = row["id"]
        try:
            async with self._lock(sid):
                await self.run(row, actor, trigger)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Automatische Aktualisierung von %s ist abgestürzt", row["name"])
        finally:
            self._running.pop(sid, None)

    def _phase(self, server_id: str, phase: str) -> None:
        self._running[server_id] = {"phase": phase, "since": self._running.get(server_id, {}).get("since") or _now()}

    async def run(self, row: dict[str, Any], actor: str, trigger: str) -> dict[str, Any]:
        """Ein Lauf: Paketlisten erneuern, prüfen, die vorgesehenen Pakete einspielen, Dienste vorher/nachher vergleichen, protokollieren."""
        sid, name = row["id"], row["name"]
        who = actor or tr("Automatische Aktualisierung")
        run_id = self.repo.run_start(sid, trigger, who)
        status, summary, detail = "failed", "", ""
        installed: list[dict[str, str]] = []
        new_failed: list[str] = []
        held_back = 0
        reboot = False
        command = ""
        try:
            self._phase(sid, "check")
            report = await self._fetch(row, refresh_lists=True)
            self._store_report(sid, report)
            result = self.evaluated(sid) or evaluate(report, self.effective(sid), {}, {}, self.clock())
            chosen = selected(result)
            held_back = len(result["items"]) - len(chosen)
            reboot = result["reboot_required"]
            if result["blocked"]:
                status, summary = "attention", tr("Nicht gestartet: {why}", why=result["blocked"][0]["text"])
            elif not chosen:
                status, summary = "ok", tr("Nichts zu aktualisieren") if not result["items"] else tr("Nichts Passendes zu aktualisieren")
                self.repo.clear_once(sid)
            else:
                before = failed_units(await self._safe_call(sid, "services_failed"))
                names = [i["name"] for i in chosen]
                self._phase(sid, "prepare")
                plan = await self.hub.prepare(sid, "package", {"action": "upgrade", "packages": names, "auto": True})
                command = plan["command"]
                if plan["class"] != 1:
                    # Der Agent hat mehr gefunden als die Vorprüfung (etwa Pakete, die entfernt würden): nichts einspielen
                    status = "attention"
                    summary = tr("Nicht eingespielt: Der Trockenlauf des Servers meldet mehr als erwartet. Bitte im Chat oder auf dem Server prüfen.")
                    detail = plan.get("preview") or plan.get("reason") or ""
                else:
                    self._phase(sid, "install")
                    text = await self.hub.execute(sid, plan)
                    self.repo.clear_once(sid)
                    if run_failed(text):
                        status, summary, detail = "failed", tr("Das Einspielen ist fehlgeschlagen."), text[-1200:]
                    else:
                        self._phase(sid, "verify")
                        if self.settle:
                            await asyncio.sleep(self.settle)
                        after_report = await self._fetch(row, refresh_lists=False, simulate=False)
                        self._store_report(sid, after_report)
                        still = {str(u.get("name")): str(u.get("candidate")) for u in after_report.get("updates") or []}
                        installed = [{"name": i["name"], "from": i["installed"], "to": i["candidate"]} for i in chosen if still.get(i["name"]) != i["candidate"]]
                        reboot = bool(after_report.get("reboot_required"))
                        after = failed_units(await self._safe_call(sid, "services_failed"))
                        new_failed = sorted(after - before)
                        left = len(chosen) - len(installed)
                        if new_failed:
                            status = "attention"
                            summary = tr("{n} Paket(e) aktualisiert, aber neu fehlgeschlagen: {units}", n=len(installed), units=", ".join(new_failed[:5]))
                        elif left:
                            status = "partial"
                            summary = tr("{n} Paket(e) aktualisiert, {m} ließen sich nicht einspielen", n=len(installed), m=left)
                        else:
                            status = "ok"
                            summary = tr("{n} Paket aktualisiert", n=len(installed)) if len(installed) == 1 else tr("{n} Pakete aktualisiert", n=len(installed))
        except ServerError as exc:
            status, summary, detail = "failed", tr("Nicht ausgeführt: {why}", why=str(exc)), ""
        except Exception as exc:  # noqa: BLE001 (der Lauf muss immer protokolliert werden)
            log.exception("Automatische Aktualisierung von %s fehlgeschlagen", name)
            status, summary, detail = "failed", tr("Unerwarteter Fehler beim Aktualisieren."), type(exc).__name__
        self.repo.run_finish(run_id, status, summary, detail, installed, held_back, new_failed, reboot)
        run = self.repo.runs(sid, 1)[0]
        audit_result = {"ok": "ok", "partial": "failed", "failed": "failed", "attention": "failed"}.get(status, status)
        self.hub.repo.audit_add(
            "change", tr("Automatische Aktualisierung: {summary}", summary=summary), server_id=sid, server_name=name, actor=who, command=command,
            result=audit_result, detail=(", ".join(f"{i['name']} {i['from']} → {i['to']}" for i in installed) or detail)[:1000],
        )
        if self.on_result is not None and (installed or status != "ok"):
            try:
                await self.on_result(row, run)
            except Exception:  # noqa: BLE001
                log.warning("Meldung zur automatischen Aktualisierung fehlgeschlagen", exc_info=True)
        return run

    async def _safe_call(self, server_id: str, tool: str) -> str:
        try:
            return await self.hub.call(server_id, tool, {})
        except ServerError:
            return ""

    # -- Zeitplan

    def _plan_busy(self, server_id: str, plan_id: str) -> bool:
        """Läuft gerade ein anderer Server desselben Plans? (Pläne aktualisieren ihre Server nacheinander.)"""
        for member in self.plans.members(plan_id):
            other = member["server_id"]
            running = self._running.get(other)
            if other != server_id and running and running.get("phase") != "check":
                return True
        return False

    async def tick(self) -> None:
        """Etwa jede Minute: fällige Läufe starten, verpasste nachholen oder melden, die Prüfung auffrischen."""
        now = self.clock()
        for sid in self.plans.scheduled_ids():
            row = self.hub.repo.server_get(sid)
            if row is None or row["state"] != "active":
                continue
            eff = self.effective(sid)
            plan = eff["plan"]
            slot = self._slot(eff, ahead=False)
            key = slot_key(slot)
            online = self.hub.status_of(row)[0] in ("online", "degraded")
            if key > (eff["last_slot"] or ""):
                if self._plan_skipped(eff, slot):
                    self.repo.save(sid, {"last_slot": key, "skip_slot": ""}, eff["updated_by"])
                    self._log(row, tr("Automatische Aktualisierung: Lauf übersprungen (auf Wunsch)"), "", "skipped", key)
                    continue
                # Ein eigener Zeitplan holt einen verpassten Lauf bis 12 Stunden später nach; ein Plan nur innerhalb seines Zeitfensters
                deadline = slot - timedelta(minutes=eff["offset"]) + timedelta(minutes=eff["length"]) if plan else slot + timedelta(hours=CATCHUP_HOURS)
                if now > deadline:
                    self.repo.save(sid, {"last_slot": key}, eff["updated_by"])
                    why = tr("Das Zeitfenster des Plans {name} war vorbei, bevor der Server an der Reihe war", name=plan["name"]) if plan else tr("Server war zur geplanten Zeit nicht erreichbar")
                    run_id = self.repo.run_start(sid, "schedule", "")
                    self.repo.run_finish(run_id, "skipped", tr("Übersprungen: {why}", why=why))
                    self._log(row, tr("Automatische Aktualisierung: Lauf ausgefallen"), "", "skipped", why)
                    if self.on_result is not None:
                        await self.on_result(row, self.repo.runs(sid, 1)[0])
                    continue
                if online and not self._lock(sid).locked() and sid not in self._running and not (plan and self._plan_busy(sid, plan["id"])):
                    self.repo.save(sid, {"last_slot": key}, eff["updated_by"])
                    try:
                        self._check_runnable(row)
                    except ServerError as exc:
                        run_id = self.repo.run_start(sid, "schedule", "")
                        self.repo.run_finish(run_id, "attention", tr("Nicht gestartet: {why}", why=str(exc)))
                        if self.on_result is not None:
                            await self.on_result(row, self.repo.runs(sid, 1)[0])
                        continue
                    self._running[sid] = {"phase": "start", "since": _now()}
                    self._spawn(self._guarded(row, "", "schedule"))
                continue
            # Prüfung auffrischen, damit „Nächster Lauf“ in der Oberfläche aktuell ist
            age = _parse(eff["preview_at"])
            stale = age is None or (now - age) > timedelta(hours=PREVIEW_MAX_AGE_HOURS)
            retry_at = self._quiet_retry.get(sid)
            if stale and online and not self._lock(sid).locked() and sid not in self._running and self.hub.can_change(row) and (retry_at is None or now >= retry_at):
                try:
                    self._check_agent(row)
                except ServerError:
                    self._quiet_retry[sid] = now + timedelta(minutes=QUIET_RETRY_MINUTES)
                    continue
                self._quiet_retry[sid] = now + timedelta(minutes=QUIET_RETRY_MINUTES)  # bei Erfolg wird preview_at frisch, die Wartezeit schadet dann nicht
                self._spawn(self._refresh_quiet(row))

    async def _refresh_quiet(self, row: dict[str, Any]) -> None:
        try:
            await self.refresh(row["id"], "")
        except ServerError as exc:
            log.info("Prüfung der Updates von %s nicht möglich: %s", row["name"], exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Prüfung der Updates von %s fehlgeschlagen", row["name"], exc_info=True)


def result_title(row: dict[str, Any], run: dict[str, Any]) -> tuple[str, str]:
    """Titel und Text der Meldung aufs Handy."""
    status = run["status"]
    name = row["name"]
    if status == "ok":
        title = tr("{name}: Updates eingespielt", name=name)
    elif status == "skipped":
        title = tr("{name}: Update-Lauf ausgefallen", name=name)
    else:
        title = tr("{name}: Update braucht Aufmerksamkeit", name=name)
    text = clean_text(run["summary"], 200)
    if run.get("reboot"):
        text += " " + tr("Neustart erforderlich.")
    return title, text.strip()
