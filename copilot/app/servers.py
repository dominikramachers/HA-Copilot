"""Linux-Server: ein zentraler Hub im Add-on, bei dem sich die Agenten der Server melden.

Aufbau (siehe Projektdokument „Server-Agent“):

* Das Add-on ist der **Hub**. Die Agenten verbinden sich von sich aus (ausgehend) per WebSocket über TLS mit gegenseitiger
  Zertifikatsprüfung (mTLS). Auf den Servern muss nichts lauschen.
* Das Add-on betreibt eine kleine eigene Zertifizierungsstelle (``Pki``). Die **Identität eines Servers ist sein Zertifikat**; der
  Hostname ist nur ein Anzeigename.
* Neue Server melden sich mit einem **Registrierungsschlüssel** (``ck_…``, begrenzt nach Zeit und Anzahl, nur als Hash gespeichert)
  und erscheinen als „Ausstehend“, bis jemand sie in der App bestätigt. Erst dann darf die KI sie benutzen.
* Der Hub nimmt von den Agenten nur **feste Nachrichtenarten** mit streng geprüften Feldern an (``clean_heartbeat``). Alles, was ein
  Agent liefert (Hostname, Protokollzeilen, Dienstnamen), ist **fremder Inhalt** und wird nie als Anweisung behandelt.
* Es gibt keine Befehlswarteschlange: ein Aufruf geht nur an einen verbundenen, bestätigten Server und wartet auf dessen Antwort.

Dieses Modul enthält die Zertifizierungsstelle, die Schlüsselverwaltung, die Server-Tabelle, das Protokoll und den Hub selbst
(``ServerHub``). Die Werkzeuge der KI stehen in ``server_tools.py``, die Schnittstelle in ``server_routes.py``.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import ssl
import time
import weakref
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .config import Settings
from .db import Store
from .i18n import tr
from .ratelimit import RateLimiter
from .server_messages import clean_msgs

log = logging.getLogger("ki.servers")

HUB_PORT = 8101  # Port im Add-on (Host-Port unter „Netzwerk“ des Add-ons eintragen)
HEARTBEAT_SECONDS = 30  # so oft meldet sich ein Agent
OFFLINE_AFTER = 90  # Sekunden ohne Meldung bis „offline“
MAX_MESSAGE_BYTES = 512 * 1024  # größte Nachricht eines Agenten (Ergebnisse sind zusätzlich auf MAX_RESULT_CHARS gekürzt)
MAX_RESULT_CHARS = 60_000
CALL_TIMEOUT = 45  # Sekunden, die ein Aufruf an einen Server höchstens dauert
KEY_PREFIX = "ck_"
KEY_MAX_HOURS = 24 * 14
KEY_MAX_USES = 100
CERT_DAYS = 365  # Zertifikat eines Servers; der Agent erneuert es von selbst, sobald weniger als 120 Tage übrig sind
PREV_CERT_HOURS = 24 * 7  # so lange gilt das alte Zertifikat nach einer Erneuerung noch (falls der Agent das neue nicht mehr ablegen konnte)
RENEW_MIN_SECONDS = 300  # frühester Abstand zweier Erneuerungsanfragen einer Verbindung
CA_DAYS = 20 * 365
AUDIT_KEEP_DAYS = 90
AUDIT_MAX_ROWS = 20_000
STATES = ("pending", "active", "blocked")  # Zustand in der Datenbank; online/offline wird aus den Meldungen abgeleitet
DISK_WARN_PERCENT = 90
CERT_WARN_DAYS = 30  # so lange vor dem Ablauf des Zertifikats zeigt die Übersicht einen Hinweis (der Agent erneuert schon viel früher)
AGENT_UPDATE_TIMEOUT = 30

# Was der Hub einem Agenten überhaupt auftragen darf (der Agent prüft noch einmal selbst, siehe agent/internal/tools)
READ_TOOLS = (
    "system", "disks", "memory", "load", "processes", "services_failed", "service", "journal", "network", "updates", "users",
    "metrics", "file_read", "package_info", "docker",
)

# Ändernde Aufträge (Etappe 2): nur nach Einstufung durch den Agenten und Freigabe in der App
CHANGE_TOOLS = ("service_action", "package", "run_command", "file_write")
EXECUTE_GRACE = 60  # Sekunden über dem Zeitlimit des Plans, bis der Hub eine Ausführung als verloren ansieht
PREPARE_TIMEOUT = 120  # der Trockenlauf von apt kann dauern

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f  ]")
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")


class ServerError(Exception):
    """Meldung, die die Oberfläche oder die KI sieht (Server nicht erreichbar, nicht bestätigt …)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _within(stamp: Any, hours: int) -> bool:
    """Liegt der Zeitpunkt (ISO, UTC) höchstens ``hours`` Stunden zurück?"""
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return False
    return moment.tzinfo is not None and datetime.now(timezone.utc) - moment <= timedelta(hours=hours)


def _sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def clean_text(value: Any, limit: int, *, default: str = "") -> str:
    """Text eines Agenten: nur Zeichenkette, ohne Steuerzeichen, gekürzt."""
    if not isinstance(value, str):
        return default
    return " ".join(_CTRL.sub(" ", value).split())[:limit] or default


def _number(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value < low or value > high:  # NaN oder außerhalb
        return None
    return float(value)


def clean_host(value: Any) -> str:
    text = clean_text(value, 253)
    return text if _HOST_RE.match(text) else ""


def _iso_time(value: Any) -> str:
    """Zeitangabe eines Agenten als UTC-Zeichenkette. Der Agent sendet Unix-Sekunden; auch RFC 3339 mit Zeitzone wird gelesen.
    Unbrauchbares ergibt einen leeren Text."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        if value != value or not 0 < value < 4_102_444_800:  # bis zum Jahr 2100
            return ""
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
    if not isinstance(value, str) or len(value) > 40:
        return ""
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return ""
    if moment.tzinfo is None:
        return ""
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def cert_days_left(info: dict[str, Any]) -> int | None:
    """Wie viele Tage das Zertifikat des Servers noch gilt (nach seiner letzten Meldung); ``None`` = unbekannt."""
    try:
        moment = datetime.fromisoformat(str(info.get("cert_expires") or ""))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return (moment - datetime.now(timezone.utc)).days


def parse_version(value: str) -> tuple[int, int, int] | None:
    """„0.61.0“ (auch mit führendem v) als Zahlen; alles andere (etwa „dev“) ist keine Fassung."""
    parts = value.strip().removeprefix("v").split(".")
    if len(parts) != 3 or not all(p.isdigit() and str(int(p)) == p and int(p) <= 1_000_000 for p in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def version_newer(offered: str, current: str) -> bool:
    a, b = parse_version(offered), parse_version(current)
    return a is not None and b is not None and a > b


def clean_heartbeat(data: Any) -> dict[str, Any] | None:
    """Die Meldung eines Agenten streng prüfen und auf bekannte Felder mit Grenzen zurückführen.

    Unbekannte Felder werden verworfen, Texte gekürzt und von Steuerzeichen befreit, Zahlen auf sinnvolle Bereiche begrenzt.
    ``None`` = die Nachricht ist unbrauchbar (kein Hostname).
    """
    if not isinstance(data, dict):
        return None
    hostname = clean_host(data.get("hostname"))
    if not hostname:
        return None
    ips: list[str] = []
    raw_ips = data.get("ips")
    for item in (raw_ips if isinstance(raw_ips, list) else [])[:16]:
        if isinstance(item, str):
            try:
                ips.append(str(ipaddress.ip_address(item.strip())))
            except ValueError:
                continue
    out: dict[str, Any] = {
        "hostname": hostname,
        "fqdn": clean_host(data.get("fqdn")),
        "ips": ips,
        "os": clean_text(data.get("os"), 80),
        "kernel": clean_text(data.get("kernel"), 80),
        "arch": clean_text(data.get("arch"), 16),
        "agent_version": clean_text(data.get("agent_version"), 20),
        "reboot_required": data.get("reboot_required") is True,
        # Etappe 2: was die lokale Richtlinie des Servers erlaubt (der Hub kann das nicht erweitern)
        "operate": data.get("operate") is True,
        "helper": data.get("helper") is True,
        # 0.61: Ablauf des Zertifikats, Richtlinie zur Selbstaktualisierung und ein zurückgesetztes Update
        "cert_expires": _iso_time(data.get("cert_expires")),
        "update_mode": data.get("update_mode") if data.get("update_mode") in ("off", "manual", "auto") else "",
        "update_failed": clean_text(data.get("update_failed"), 20),
        "update_reason": clean_text(data.get("update_reason"), 300),
    }
    max_class = _number(data.get("max_class"), 0, 3)
    out["max_class"] = min(2, max(0, int(max_class))) if max_class is not None else 0
    for key, low, high in (
        ("uptime_s", 0, 10**9), ("load1", 0, 100000), ("load5", 0, 100000), ("load15", 0, 100000), ("cpus", 1, 100000),
        ("mem_total_mb", 0, 10**8), ("mem_used_pct", 0, 100), ("disk_worst_pct", 0, 100), ("failed_units", 0, 100000), ("updates", 0, 100000),
    ):
        number = _number(data.get(key), low, high)
        out[key] = None if number is None else (int(number) if key in ("uptime_s", "cpus", "mem_total_mb", "failed_units", "updates") else round(number, 2))
    out["disk_worst_mount"] = clean_text(data.get("disk_worst_mount"), 120)
    names = data.get("failed_unit_names")
    out["failed_unit_names"] = [clean_text(n, 100) for n in (names if isinstance(names, list) else [])[:20] if isinstance(n, str) and clean_text(n, 100)]
    return out


PREVIEW_CHARS = 6000  # Vorschau eines Plans (bei Dateiänderungen der Vergleich)
_PLAN_ID = re.compile(r"^[0-9a-f]{24}$")
_PLAN_HASH = re.compile(r"^[0-9a-f]{64}$")


def clean_plan(data: Any) -> dict[str, Any] | None:
    """Den Plan eines Agenten streng prüfen. Er geht in die Freigabekarte: Texte sind fremder Inhalt und werden gekürzt."""
    if not isinstance(data, dict):
        return None
    plan_id, plan_hash = data.get("id"), data.get("hash")
    if not isinstance(plan_id, str) or not _PLAN_ID.match(plan_id) or not isinstance(plan_hash, str) or not _PLAN_HASH.match(plan_hash):
        return None
    tool = data.get("tool")
    klass = data.get("class")
    if tool not in CHANGE_TOOLS or isinstance(klass, bool) or klass not in (1, 2):
        return None  # Stufe 3 führt kein Agent aus; ein Plan mit Stufe 3 ist ein Fehler
    command = clean_text_block(data.get("command"), 4300)
    if not command:
        return None
    timeout = _number(data.get("timeout_s"), 1, 1800)
    return {
        "id": plan_id, "hash": plan_hash, "tool": tool, "class": int(klass),
        "reason": clean_text(data.get("reason"), 300), "summary": clean_text(data.get("summary"), 200),
        "command": command, "runner": "root" if data.get("runner") == "root" else "agent",
        "preview": clean_text_block(data.get("preview"), PREVIEW_CHARS), "undo": clean_text(data.get("undo"), 300),
        "timeout_s": int(timeout) if timeout is not None else 60,
        # dieselben Texte mit Code und Werten, damit die Freigabekarte in der Sprache der Person erscheint (server_messages.py)
        "msgs": clean_msgs(data.get("msgs")),
    }


_CTRL_BLOCK = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text_block(value: Any, limit: int) -> str:
    """Mehrzeiliger Text eines Agenten (Befehl, Vorschau): Zeilenumbrüche bleiben, Steuerzeichen nicht."""
    if not isinstance(value, str):
        return ""
    return _CTRL_BLOCK.sub(" ", value.replace("\r\n", "\n")).strip()[:limit]


# ------------------------------------------------------------------------------------------------ Zertifizierungsstelle


class Pki:
    """Kleine eigene Zertifizierungsstelle des Hubs. Schlüssel liegen im Datenordner (nur für den Add-on-Benutzer lesbar)."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self._ca_key_path = directory / "ca.key"
        self._ca_path = directory / "ca.pem"
        self._hub_key_path = directory / "hub.key"
        self._hub_path = directory / "hub.pem"
        self._hosts_path = directory / "hub.hosts"
        self._ca_key: ec.EllipticCurvePrivateKey | None = None
        self._ca: x509.Certificate | None = None

    # -- Dateien

    @staticmethod
    def _write_private(path: Path, data: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)

    def ensure_ca(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.dir, 0o700)
        if self._ca_key_path.exists() and self._ca_path.exists():
            self._ca_key = serialization.load_pem_private_key(self._ca_key_path.read_bytes(), None)  # type: ignore[assignment]
            self._ca = x509.load_pem_x509_certificate(self._ca_path.read_bytes())
            return
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HA Copilot"),
            x509.NameAttribute(NameOID.COMMON_NAME, "HA Copilot Server-CA"),
        ])
        now = datetime.now(timezone.utc) - timedelta(minutes=5)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256())
        )
        self._write_private(self._ca_key_path, key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self._ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self._ca_key, self._ca = key, cert
        log.info("Server-Hub: neue Zertifizierungsstelle angelegt")

    @property
    def ca(self) -> x509.Certificate:
        if self._ca is None:
            self.ensure_ca()
        assert self._ca is not None
        return self._ca

    @property
    def ca_pem(self) -> str:
        return self.ca.public_bytes(serialization.Encoding.PEM).decode()

    @property
    def ca_fingerprint(self) -> str:
        """``sha256:<hex>`` des CA-Zertifikats. Der Agent prüft den Hub dagegen (ohne Namen, die CA ist ja privat)."""
        return "sha256:" + hashlib.sha256(self.ca.public_bytes(serialization.Encoding.DER)).hexdigest()

    # -- Zertifikat des Hubs

    def hub_pin(self, hosts: list[str]) -> str:
        """Angehefteter Schlüssel des Hub-Zertifikats im Format von curl (``sha256//<base64>``)."""
        import base64

        self.ensure_hub_cert(hosts)
        leaf = x509.load_pem_x509_certificate(self._hub_path.read_bytes())
        spki = leaf.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        return "sha256//" + base64.b64encode(hashlib.sha256(spki).digest()).decode()

    def ensure_hub_cert(self, hosts: list[str]) -> None:
        """Zertifikat des Hubs (vom CA unterschrieben); wird neu erstellt, wenn sich die Adressen ändern oder es bald abläuft."""
        self.ensure_ca()
        wanted = ",".join(sorted(set(hosts)))
        if self._hub_key_path.exists() and self._hub_path.exists() and self._hosts_path.exists() and self._hosts_path.read_text() == wanted:
            current = x509.load_pem_x509_certificate(self._hub_path.read_bytes())
            if current.not_valid_after_utc - datetime.now(timezone.utc) > timedelta(days=30):
                return
        key = ec.generate_private_key(ec.SECP256R1())
        names: list[x509.GeneralName] = [x509.DNSName("localhost")]
        for host in sorted(set(hosts)):
            try:
                names.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                if _HOST_RE.match(host):
                    names.append(x509.DNSName(host))
        now = datetime.now(timezone.utc) - timedelta(minutes=5)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HA Copilot Server-Hub")]))
            .issuer_name(self.ca.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + timedelta(days=5 * 365))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(self._ca_key, hashes.SHA256())  # type: ignore[arg-type]
        )
        self._write_private(self._hub_key_path, key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        # Kette: Zertifikat des Hubs, dann das CA-Zertifikat (der Agent erkennt daran seine angeheftete CA)
        self._hub_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + self.ca.public_bytes(serialization.Encoding.PEM))
        self._hosts_path.write_text(wanted)

    def ssl_context(self, hosts: list[str]) -> ssl.SSLContext:
        self.ensure_hub_cert(hosts)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(self._hub_path, self._hub_key_path)
        context.load_verify_locations(cadata=self.ca_pem)
        context.verify_mode = ssl.CERT_OPTIONAL  # ohne Zertifikat ist nur die Anmeldung („/enroll“) und der Download möglich
        return context

    # -- Zertifikate der Server

    @staticmethod
    def parse_csr(pem: Any) -> x509.CertificateSigningRequest:
        if not isinstance(pem, str) or not 100 < len(pem) < 4000:
            raise ServerError(tr("Ungültige Zertifikatsanfrage."))
        try:
            csr = x509.load_pem_x509_csr(pem.encode())
            key = csr.public_key()
        except ValueError:
            raise ServerError(tr("Ungültige Zertifikatsanfrage.")) from None
        if not csr.is_signature_valid or not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
            raise ServerError(tr("Ungültige Zertifikatsanfrage."))
        return csr

    def sign_csr(self, csr: x509.CertificateSigningRequest, server_id: str) -> tuple[str, str]:
        """Zertifikat für den Server ausstellen. Aus der Anfrage wird nur der öffentliche Schlüssel übernommen
        (Name und Erweiterungen bestimmt allein der Hub). Gibt (PEM, SHA-256 des Zertifikats) zurück."""
        now = datetime.now(timezone.utc) - timedelta(minutes=5)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HA Copilot Server"),
                x509.NameAttribute(NameOID.COMMON_NAME, server_id),
            ]))
            .issuer_name(self.ca.subject).public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + timedelta(days=CERT_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .sign(self._ca_key, hashes.SHA256())  # type: ignore[arg-type]
        )
        return cert.public_bytes(serialization.Encoding.PEM).decode(), _sha256(cert.public_bytes(serialization.Encoding.DER))


# ------------------------------------------------------------------------------------------------ Datenhaltung


class ServerRepo:
    """Server, Registrierungsschlüssel und Protokoll in der Datenbank (Tabellen ab Schema 36)."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def _q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._store._lock:
            return [dict(r) for r in self._store._conn.execute(sql, args).fetchall()]

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._store._lock, self._store._conn:
            return self._store._conn.execute(sql, args).rowcount

    # -- Server

    def server_get(self, server_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM servers WHERE id = ?", (server_id,))
        return rows[0] if rows else None

    def server_by_cert(self, cert_hash: str) -> tuple[dict[str, Any], bool] | None:
        """Der Server zu einem Zertifikat und ob es das **alte** Zertifikat nach einer Erneuerung ist (gilt nur kurz, siehe
        ``PREV_CERT_HOURS``: so geht ein Agent nicht verloren, der das neue Zertifikat nicht mehr ablegen konnte)."""
        rows = self._q("SELECT * FROM servers WHERE cert_hash = ?", (cert_hash,))
        if rows:
            return rows[0], False
        rows = self._q("SELECT * FROM servers WHERE prev_cert_hash = ? AND prev_cert_hash != ''", (cert_hash,))
        if rows and _within(rows[0].get("cert_renewed_at"), PREV_CERT_HOURS):
            return rows[0], True
        return None

    def server_renewed(self, server_id: str, cert_hash: str) -> bool:
        """Das erneuerte Zertifikat gilt ab jetzt; das bisherige bleibt noch kurz gültig."""
        return self._x("UPDATE servers SET prev_cert_hash = cert_hash, cert_hash = ?, cert_renewed_at = ? WHERE id = ?", (cert_hash, _now(), server_id)) > 0

    def server_cert_settled(self, server_id: str) -> None:
        """Der Agent hat sich mit dem neuen Zertifikat gemeldet: das alte gilt nicht mehr."""
        self._x("UPDATE servers SET prev_cert_hash = '' WHERE id = ? AND prev_cert_hash != ''", (server_id,))

    def server_list(self) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM servers ORDER BY name COLLATE NOCASE, id")

    def server_create(self, server_id: str, name: str, cert_hash: str, key_id: str) -> None:
        self._x("INSERT INTO servers (id, name, state, cert_hash, created_at, key_id) VALUES (?, ?, 'pending', ?, ?, ?)",
                (server_id, name, cert_hash, _now(), key_id))

    def server_seen(self, server_id: str, ip: str, info: dict[str, Any]) -> None:
        self._x("UPDATE servers SET last_seen_at = ?, last_ip = ?, info = ? WHERE id = ?", (_now(), ip[:64], json.dumps(info, ensure_ascii=False), server_id))

    def server_state(self, server_id: str, state: str) -> bool:
        confirmed = ", confirmed_at = ?" if state == "active" else ""
        args: tuple = (state, _now(), server_id) if confirmed else (state, server_id)
        return self._x(f"UPDATE servers SET state = ?{confirmed} WHERE id = ?", args) > 0

    def server_rename(self, server_id: str, name: str) -> bool:
        return self._x("UPDATE servers SET name = ? WHERE id = ?", (name, server_id)) > 0

    def server_delete(self, server_id: str) -> bool:
        return self._x("DELETE FROM servers WHERE id = ?", (server_id,)) > 0

    # -- Registrierungsschlüssel

    def key_create(self, created_by: str, label: str, hours: int, max_uses: int) -> tuple[str, str, str]:
        """Neuer Schlüssel. Gibt (Kennung, Schlüssel im Klartext, Ablauf) zurück; gespeichert wird nur der Hash."""
        key_id = secrets.token_hex(6)
        key = KEY_PREFIX + secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
        self._x("INSERT INTO server_keys (id, key_hash, label, created_by, created_at, expires_at, max_uses) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key_id, _sha256(key), label, created_by, now.isoformat(timespec="seconds"), expires, max_uses))
        self._x("DELETE FROM server_keys WHERE expires_at < ?", ((now - timedelta(days=30)).isoformat(timespec="seconds"),))
        return key_id, key, expires

    @staticmethod
    def _key_valid(row: dict[str, Any]) -> bool:
        return not row["revoked_at"] and row["expires_at"] > _now() and row["uses"] < row["max_uses"]

    def key_check(self, key: Any) -> dict[str, Any] | None:
        """Gültigen Schlüssel prüfen, ohne ihn zu verbrauchen (für den Download des Agenten)."""
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX) or len(key) > 100:
            return None
        rows = self._q("SELECT * FROM server_keys WHERE key_hash = ?", (_sha256(key),))
        return rows[0] if rows and self._key_valid(rows[0]) else None

    def key_consume(self, key: Any) -> dict[str, Any] | None:
        """Schlüssel einmal verbrauchen (atomar). ``None`` = ungültig, abgelaufen, widerrufen oder aufgebraucht."""
        row = self.key_check(key)
        if row is None:
            return None
        used = self._x("UPDATE server_keys SET uses = uses + 1 WHERE id = ? AND uses < max_uses AND revoked_at IS NULL AND expires_at > ?", (row["id"], _now()))
        return row if used else None

    def key_list(self) -> list[dict[str, Any]]:
        rows = self._q("SELECT id, label, created_by, created_at, expires_at, max_uses, uses, revoked_at FROM server_keys ORDER BY created_at DESC LIMIT 50")
        for row in rows:
            row["active"] = self._key_valid(row)
        return rows

    def key_revoke(self, key_id: str) -> bool:
        return self._x("UPDATE server_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (_now(), key_id)) > 0

    # -- Protokoll

    def audit_add(self, kind: str, summary: str, *, server_id: str = "", server_name: str = "", actor: str = "", command: str = "",
                  result: str = "", detail: str = "") -> None:
        self._x(
            "INSERT INTO server_audit (ts, server_id, server_name, actor, kind, summary, command, result, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), server_id, server_name[:120], actor[:80], kind, summary[:400], command[:600], result[:40], detail[:1000]),
        )

    def audit_prune(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=AUDIT_KEEP_DAYS)).isoformat(timespec="seconds")
        self._x("DELETE FROM server_audit WHERE ts < ?", (cutoff,))
        self._x("DELETE FROM server_audit WHERE id <= (SELECT COALESCE(MAX(id), 0) - ? FROM server_audit)", (AUDIT_MAX_ROWS,))

    def audit_list(self, *, server_id: str = "", kind: str = "", days: int = 1, limit: int = 200) -> list[dict[str, Any]]:
        where, args = ["ts >= ?"], [(datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat(timespec="seconds")]
        if server_id:
            where.append("server_id = ?")
            args.append(server_id)
        if kind:
            where.append("kind = ?")
            args.append(kind)
        return self._q(f"SELECT * FROM server_audit WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?", (*args, max(1, min(limit, 500))))


# ------------------------------------------------------------------------------------------------ Hub


class AgentConn:
    """Eine offene Verbindung eines Agenten (nur im Arbeitsspeicher)."""

    def __init__(self, ws: Any, server_id: str, ip: str) -> None:
        self.ws = ws
        self.server_id = server_id
        self.ip = ip
        self.seen = time.monotonic()
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 0
        self.violations = 0
        self.rate = RateLimiter(60, 10)  # höchstens 60 Nachrichten in 10 Sekunden
        self.last_renew = 0.0  # Zeitpunkt (monotonic) der letzten Anfrage nach einem neuen Zertifikat


Notify = Callable[[str, str], Awaitable[None]]  # (Titel, Text) -> Meldung in Home Assistant


class ServerHub:
    """Nimmt die Verbindungen der Agenten an, führt Buch über Zustand und Aufrufe und beantwortet die Schnittstelle."""

    def __init__(self, store: Store, settings: Settings, directory: Path, agent_dir: Path | None = None, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self.repo = ServerRepo(store)
        self.pki = Pki(directory)
        self.agent_dir = agent_dir
        self._clock = clock
        self._conns: dict[str, AgentConn] = {}
        self._loop: asyncio.AbstractEventLoop | None = None  # Ereignisschleife des Hubs (gesetzt in serve)
        self._online: dict[str, bool] = {}  # zuletzt gemeldeter Zustand je bestätigtem Server (für „ging offline“)
        self._enroll_limit = RateLimiter(10, 600)  # Anmeldeversuche je Adresse in zehn Minuten
        self._download_limit = RateLimiter(30, 600)
        self._offers: dict[str, tuple[tuple[int, int, int, int], dict[str, Any]]] = {}
        self.notify: Notify | None = None
        self._server: Any = None
        self.port = 0

    # -- Zustand

    @property
    def enabled(self) -> bool:
        return self.settings.servers_enabled

    def hosts(self) -> list[str]:
        host = self.settings.server_hub_address.rsplit(":", 1)[0] if self.settings.server_hub_address else ""
        return [host.strip("[]")] if host else []

    def status_of(self, row: dict[str, Any]) -> tuple[str, list[str]]:
        """(Status, Gründe). Status: pending | online | degraded | offline | blocked."""
        if row["state"] == "blocked":
            return "blocked", []
        conn = self._conns.get(row["id"])
        fresh = conn is not None and self._clock() - conn.seen <= OFFLINE_AFTER
        if row["state"] == "pending":
            return "pending", []
        if not fresh:
            return "offline", []
        info = _json(row["info"])
        reasons: list[str] = []
        if (info.get("disk_worst_pct") or 0) >= DISK_WARN_PERCENT:
            reasons.append(tr("Datenträger zu {n} % voll", n=int(info["disk_worst_pct"])))
        return ("degraded" if reasons else "online"), reasons

    @staticmethod
    def hints_of(info: dict[str, Any]) -> list[str]:
        """Hinweise, die den Status nicht ändern: Der Server ist erreichbar und arbeitet, aber etwas verdient einen Blick."""
        hints: list[str] = []
        failed = info.get("failed_units") or 0
        if failed > 0:
            hints.append(tr("{n} Dienst fehlgeschlagen", n=failed) if failed == 1 else tr("{n} Dienste fehlgeschlagen", n=failed))
        if info.get("reboot_required"):
            hints.append(tr("Neustart erforderlich"))
        days = cert_days_left(info)
        if days is not None and days < CERT_WARN_DAYS:
            hints.append(tr("Zertifikat läuft in {n} Tagen ab", n=max(days, 0)) if days != 1 else tr("Zertifikat läuft morgen ab"))
        if info.get("update_failed"):
            hints.append(tr("Aktualisierung auf {version} wurde zurückgenommen", version=info["update_failed"]))
        return hints

    def view(self, row: dict[str, Any]) -> dict[str, Any]:
        status, reasons = self.status_of(row)
        info = _json(row["info"])
        conn = self._conns.get(row["id"])
        return {
            "id": row["id"], "name": row["name"], "state": row["state"], "status": status, "reasons": reasons,
            "hints": self.hints_of(info) if status in ("online", "degraded") else [],
            "created_at": row["created_at"], "confirmed_at": row["confirmed_at"], "last_seen_at": row["last_seen_at"],
            "ip": (info.get("ips") or [row["last_ip"]])[0] if (info.get("ips") or row["last_ip"]) else "",
            "peer": row["last_ip"], "connected": conn is not None, "info": info,
            # Aktualisierung des Agenten: neuere Fassung im Add-on, lokale Richtlinie (off | manual | auto), zurückgesetzte Fassung
            "update": {
                "available": self.update_available(info), "mode": info.get("update_mode") or "",
                "failed": info.get("update_failed") or "", "reason": info.get("update_reason") or "",
            },
            "cert_days": cert_days_left(info),
        }

    def listing(self) -> list[dict[str, Any]]:
        return [self.view(r) for r in self.repo.server_list()]

    def summary(self) -> dict[str, int]:
        counts = {"online": 0, "degraded": 0, "offline": 0, "pending": 0, "blocked": 0}
        for item in self.listing():
            counts[item["status"]] += 1
        return counts

    def get(self, ref: str) -> dict[str, Any] | None:
        """Server nach Kennung oder (eindeutigem, groß-/kleinschreibungsfreiem) Namen."""
        row = self.repo.server_get(ref)
        if row is not None:
            return row
        matches = [r for r in self.repo.server_list() if r["name"].lower() == str(ref).lower()]
        return matches[0] if len(matches) == 1 else None

    # -- Verwaltung (von der Oberfläche)

    def confirm(self, server_id: str, actor: str) -> dict[str, Any]:
        row = self.repo.server_get(server_id)
        if row is None:
            raise ServerError(tr("Dieser Server ist nicht bekannt."), 404)
        if row["state"] != "pending":
            raise ServerError(tr("Dieser Server ist schon bestätigt."), 409)
        self.repo.server_state(server_id, "active")
        self.repo.audit_add("event", tr("Server bestätigt"), server_id=server_id, server_name=row["name"], actor=actor, result="ok")
        self._push_state(server_id, "active")
        return self.repo.server_get(server_id) or row

    def block(self, server_id: str, actor: str) -> None:
        row = self.repo.server_get(server_id)
        if row is None:
            raise ServerError(tr("Dieser Server ist nicht bekannt."), 404)
        self.repo.server_state(server_id, "blocked")
        self.repo.audit_add("event", tr("Server gesperrt"), server_id=server_id, server_name=row["name"], actor=actor, result="ok")
        self._drop(server_id)

    def unblock(self, server_id: str, actor: str) -> None:
        row = self.repo.server_get(server_id)
        if row is None or row["state"] != "blocked":
            raise ServerError(tr("Dieser Server ist nicht gesperrt."), 409)
        self.repo.server_state(server_id, "active")
        self.repo.audit_add("event", tr("Server entsperrt"), server_id=server_id, server_name=row["name"], actor=actor, result="ok")

    def remove(self, server_id: str, actor: str) -> None:
        row = self.repo.server_get(server_id)
        if row is None:
            raise ServerError(tr("Dieser Server ist nicht bekannt."), 404)
        self.repo.server_delete(server_id)
        self._online.pop(server_id, None)
        self.repo.audit_add("event", tr("Server entfernt"), server_id=server_id, server_name=row["name"], actor=actor, result="ok")
        self._drop(server_id)

    def rename(self, server_id: str, name: str) -> None:
        name = clean_text(name, 60)
        if not name or not self.repo.server_rename(server_id, name):
            raise ServerError(tr("Der Name ist ungültig."), 422)

    # -- Zertifikat und Aktualisierung des Agenten

    def renew_now(self, server_id: str, actor: str) -> None:
        """Den Agenten auffordern, sofort ein neues Zertifikat anzufragen (sonst macht er das von selbst, sobald es fällig ist)."""
        row = self.repo.server_get(server_id)
        if row is None:
            raise ServerError(tr("Dieser Server ist nicht bekannt."), 404)
        conn = self._conns.get(server_id)
        if conn is None or self._clock() - conn.seen > OFFLINE_AFTER:
            raise ServerError(tr("Der Server {name} ist gerade offline.", name=row["name"]), 503)
        self.repo.audit_add("event", tr("Zertifikatserneuerung angestoßen"), server_id=server_id, server_name=row["name"], actor=actor, result="ok")
        self._on_loop(lambda: asyncio.ensure_future(self._send(conn.ws, {"t": "renew_now"})))

    def agent_version(self) -> str:
        """Fassung der mitgelieferten Agenten (Datei VERSION neben den Programmen); leer bei Entwicklungsständen."""
        if not self.agent_dir:
            return ""
        try:
            text = (self.agent_dir / "VERSION").read_text(encoding="utf-8").strip()[:20]
        except OSError:
            return ""
        return text if parse_version(text) else ""

    def update_offer(self, arch: str, current: str = "") -> dict[str, Any] | None:
        """Das Angebot einer neueren Fassung für eine Architektur: Fassung, SHA-256, Größe und (falls vorhanden) Signatur.
        ``current`` ist die Fassung des Agenten; ohne eine neuere gibt es kein Angebot."""
        version = self.agent_version()
        binary = self.agent_binaries().get(arch)
        if not version or binary is None or not version_newer(version, current):
            return None
        try:
            stat = binary.stat()
            sig_path = binary.with_name(binary.name + ".sig")
            sig_stat = sig_path.stat() if sig_path.is_file() else None
            stamp = (stat.st_mtime_ns, stat.st_size, sig_stat.st_mtime_ns if sig_stat else 0, sig_stat.st_size if sig_stat else 0)
            cached = self._offers.get(arch)
            if cached is None or cached[0] != stamp:
                digest = hashlib.sha256(binary.read_bytes()).hexdigest()
                sig = sig_path.read_text(encoding="ascii").strip()[:200] if sig_stat else ""
                cached = (stamp, {"sha256": digest, "size": stat.st_size, "sig": sig})
                self._offers[arch] = cached
        except (OSError, UnicodeDecodeError):
            return None
        offer: dict[str, Any] = {"version": version, "sha256": cached[1]["sha256"], "size": cached[1]["size"]}
        if cached[1]["sig"]:
            offer["sig"] = cached[1]["sig"]
        return offer

    def update_available(self, info: dict[str, Any]) -> str:
        offer = self.update_offer(str(info.get("arch") or ""), str(info.get("agent_version") or ""))
        return offer["version"] if offer else ""

    async def update_agent(self, server_id: str, actor: str) -> str:
        """Dem Agenten die neuere Fassung anbieten und ihn bitten, sie jetzt einzuspielen. Ob er das tut, bestimmt seine lokale
        Richtlinie (``update=off`` lehnt ab); der Agent prüft die Datei selbst (Prüfsumme, Signatur, Probelauf) und setzt bei einem
        Fehlstart auf die alte Fassung zurück."""
        row, conn = self._connection(server_id)
        info = _json(row["info"])
        offer = self.update_offer(str(info.get("arch") or ""), str(info.get("agent_version") or ""))
        if offer is None:
            raise ServerError(tr("Für diesen Server gibt es keine neuere Fassung des Agenten."), 409)
        try:
            text = await self._request(row, conn, {"t": "update", "offer": offer}, AGENT_UPDATE_TIMEOUT)
        except ServerError as exc:
            self.repo.audit_add("event", tr("Aktualisierung des Agenten abgelehnt"), server_id=server_id, server_name=row["name"], actor=actor, result="denied", detail=str(exc))
            raise ServerError(tr("Der Agent hat die Aktualisierung nicht gestartet: {reason}", reason=str(exc)), exc.status) from None
        self.repo.audit_add("event", tr("Aktualisierung des Agenten auf {version} angestoßen", version=offer["version"]), server_id=server_id, server_name=row["name"], actor=actor, result="ok")
        return text

    def _on_loop(self, func: Callable[[], None]) -> None:
        """Führt ``func`` in der Ereignisschleife des Hubs aus. Die Schnittstelle der Seite ruft Bestätigen, Sperren und Entfernen
        aus Worker-Threads auf, dort gibt es keine Schleife (``ensure_future`` würde scheitern) und die Verbindungen dürfen nur
        von der Schleife angefasst werden."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            inside = asyncio.get_running_loop() is loop
        except RuntimeError:
            inside = False
        if inside:
            func()
        else:
            loop.call_soon_threadsafe(func)

    def _drop(self, server_id: str) -> None:
        conn = self._conns.pop(server_id, None)
        if conn is None:
            return

        def close() -> None:
            for future in conn.pending.values():
                if not future.done():
                    future.set_exception(ServerError(tr("Die Verbindung zum Server wurde beendet.")))
            asyncio.ensure_future(self._close(conn.ws, 1008, "closed"))

        self._on_loop(close)

    def _push_state(self, server_id: str, state: str) -> None:
        conn = self._conns.get(server_id)
        if conn is not None:
            row = self.repo.server_get(server_id)
            message = self._ack(row) if row is not None else {"t": "ack", "state": state, "interval": HEARTBEAT_SECONDS}
            self._on_loop(lambda: asyncio.ensure_future(self._send(conn.ws, message)))

    @staticmethod
    async def _send(ws: Any, message: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            await ws.send(json.dumps(message, ensure_ascii=False))

    @staticmethod
    async def _close(ws: Any, code: int, reason: str) -> None:
        with contextlib.suppress(Exception):
            await ws.close(code, reason)

    # -- Aufrufe (von der KI)

    def _connection(self, server_ref: str) -> tuple[dict[str, Any], AgentConn]:
        """Den bestätigten, verbundenen Server zu einem Namen oder einer Kennung finden (sonst eine verständliche Meldung)."""
        row = self.get(server_ref)
        if row is None:
            raise ServerError(tr("Diesen Server kenne ich nicht. Frag mit server_list nach den bekannten Servern."), 404)
        if row["state"] == "pending":
            raise ServerError(tr("Der Server {name} ist noch nicht bestätigt. Bitte in der Seite „Server“ bestätigen.", name=row["name"]), 403)
        if row["state"] == "blocked":
            raise ServerError(tr("Der Server {name} ist gesperrt.", name=row["name"]), 403)
        conn = self._conns.get(row["id"])
        if conn is None or self._clock() - conn.seen > OFFLINE_AFTER:
            raise ServerError(tr("Der Server {name} ist gerade offline.", name=row["name"]), 503)
        return row, conn

    async def _request(self, row: dict[str, Any], conn: AgentConn, message: dict[str, Any], timeout: float) -> str:
        """Eine Nachricht an den Agenten schicken und auf seine Antwort warten."""
        conn.next_id += 1
        call_id = conn.next_id
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.pending[call_id] = future
        try:
            await conn.ws.send(json.dumps({**message, "id": call_id}, ensure_ascii=False))
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            raise ServerError(tr("Der Server {name} hat nicht rechtzeitig geantwortet.", name=row["name"]), 504) from None
        except ServerError:
            raise
        except Exception:
            raise ServerError(tr("Die Verbindung zum Server {name} ist abgebrochen.", name=row["name"]), 503) from None
        finally:
            conn.pending.pop(call_id, None)

    async def call(self, server_ref: str, tool: str, args: dict[str, Any] | None = None) -> str:
        """Einen lesenden Aufruf an einen bestätigten, verbundenen Server schicken und auf die Antwort warten."""
        if tool not in READ_TOOLS:
            raise ServerError(tr("Dieses Werkzeug gibt es nicht."))
        row, conn = self._connection(server_ref)
        return await self._request(row, conn, {"t": "call", "tool": tool, "args": args or {}}, CALL_TIMEOUT)

    # -- Änderungen (Etappe 2): vorbereiten (der Agent stuft ein, nichts passiert) und nach Freigabe ausführen

    def can_change(self, row: dict[str, Any]) -> bool:
        """Erlaubt die lokale Richtlinie des Servers Änderungen? (Meldung des Agenten, nicht verhandelbar.)"""
        return _json(row["info"]).get("operate") is True

    async def prepare(self, server_ref: str, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Einen ändernden Auftrag vom Agenten einstufen lassen. Verändert nichts; liefert den Plan zur Freigabe."""
        if tool not in CHANGE_TOOLS:
            raise ServerError(tr("Dieses Werkzeug gibt es nicht."))
        row, conn = self._connection(server_ref)
        if not self.can_change(row):
            raise ServerError(tr("Auf dem Server {name} sind Änderungen durch die KI nicht erlaubt (lokale Richtlinie). Ich kann dort nur lesen.", name=row["name"]), 403)
        text = await self._request(row, conn, {"t": "prepare", "tool": tool, "args": args or {}}, PREPARE_TIMEOUT)
        plan = clean_plan(_json(text))
        if plan is None:
            raise ServerError(tr("Der Server hat keinen gültigen Plan geliefert."), 502)
        return plan

    async def execute(self, server_ref: str, plan: dict[str, Any]) -> str:
        """Einen freigegebenen Plan ausführen lassen. Der Agent prüft Hash, Ablauf und seine Richtlinie noch einmal."""
        row, conn = self._connection(server_ref)
        if not self.can_change(row):
            raise ServerError(tr("Auf dem Server {name} sind Änderungen durch die KI nicht erlaubt (lokale Richtlinie). Ich kann dort nur lesen.", name=row["name"]), 403)
        message = {"t": "execute", "plan_id": plan["id"], "plan_hash": plan["hash"]}
        return await self._request(row, conn, message, int(plan.get("timeout_s") or 60) + EXECUTE_GRACE)

    # -- Verbindungen der Agenten

    async def _handle(self, ws: Any) -> None:
        path = ws.request.path.split("?", 1)[0]
        peer = (ws.remote_address or ("", 0))[0]
        try:
            if path == "/enroll":
                await self._enroll(ws, peer)
            elif path == "/agent":
                await self._agent(ws, peer)
            else:
                await ws.close(1008, "unknown path")
        except Exception as exc:  # eine kaputte Verbindung darf den Hub nie stören
            if type(exc).__name__ not in ("ConnectionClosedOK", "ConnectionClosedError", "ConnectionClosed"):
                log.warning("Server-Hub: Verbindung von %s abgebrochen: %s", peer, exc)

    async def _receive(self, ws: Any, timeout: float) -> dict[str, Any]:
        """Nächste Nachricht als Wörterbuch; eine unbrauchbare Nachricht ergibt ein leeres Wörterbuch, Stille löst ``TimeoutError`` aus."""
        raw = await asyncio.wait_for(ws.recv(), timeout)
        if not isinstance(raw, str):
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def _enroll(self, ws: Any, peer: str) -> None:
        if not self._enroll_limit.allow(peer):
            await self._send(ws, {"t": "error", "msg": "too many attempts"})
            await ws.close(1008, "rate limit")
            return
        try:
            data = await self._receive(ws, 15)
        except TimeoutError:
            await ws.close(1008, "timeout")
            return
        if data.get("t") != "enroll":
            await ws.close(1008, "bad request")
            return
        try:
            csr = self.pki.parse_csr(data.get("csr"))
        except ServerError:
            await self._send(ws, {"t": "error", "msg": "invalid certificate request"})
            await ws.close(1008, "bad request")
            return
        key = self.repo.key_consume(data.get("key"))
        if key is None:
            log.warning("Server-Hub: Anmeldung von %s mit ungültigem Schlüssel abgelehnt", peer)
            self.repo.audit_add("event", tr("Anmeldung mit ungültigem Schlüssel abgelehnt"), detail=peer, result="denied")
            await self._send(ws, {"t": "error", "msg": "invalid or expired key"})
            await ws.close(1008, "invalid key")
            return
        server_id = "srv-" + secrets.token_hex(5)
        name = clean_host(data.get("hostname")) or server_id
        cert_pem, cert_hash = self.pki.sign_csr(csr, server_id)
        self.repo.server_create(server_id, name, cert_hash, key["id"])
        self.repo.audit_add("event", tr("Neuer Server gemeldet, wartet auf Bestätigung"), server_id=server_id, server_name=name, result="pending", detail=peer)
        log.info("Server-Hub: %s (%s) hat sich angemeldet und wartet auf Bestätigung", name, peer)
        await self._send(ws, {"t": "enrolled", "server_id": server_id, "cert": cert_pem, "ca": self.pki.ca_pem})
        await ws.close(1000, "enrolled")

    async def _agent(self, ws: Any, peer: str) -> None:
        ssl_object = ws.transport.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object is not None else None
        if not der:
            await ws.close(1008, "certificate required")
            return
        found = self.repo.server_by_cert(_sha256(der))
        if found is None or found[0]["state"] == "blocked":
            await ws.close(1008, "not allowed")
            return
        row, with_old_cert = found
        server_id = row["id"]
        if not with_old_cert:
            self.repo.server_cert_settled(server_id)
        conn = AgentConn(ws, server_id, peer)
        previous = self._conns.get(server_id)
        self._conns[server_id] = conn
        if previous is not None:
            await self._close(previous.ws, 1000, "replaced")
        try:
            while True:
                try:
                    data = await self._receive(ws, OFFLINE_AFTER + 30)
                except TimeoutError:
                    break  # ein Agent, der sich so lange nicht meldet, ist weg
                if not conn.rate.allow("m"):
                    break
                kind = data.get("t")
                if kind == "heartbeat":
                    info = clean_heartbeat(data)
                    if info is None:
                        conn.violations += 1
                        if conn.violations >= 5:
                            break
                        continue
                    conn.seen = self._clock()
                    self.repo.server_seen(server_id, peer, info)
                    current = self.repo.server_get(server_id)
                    if current is None or current["state"] == "blocked":
                        break
                    await self._send(ws, self._ack(current, info))
                elif kind == "renew":
                    if not await self._renew(conn, data):
                        break
                elif kind == "result":
                    self._result(conn, data)
                else:
                    conn.violations += 1
                    if conn.violations >= 5:
                        break
        finally:
            if self._conns.get(server_id) is conn:
                del self._conns[server_id]
            for future in conn.pending.values():
                if not future.done():
                    future.set_exception(ServerError(tr("Die Verbindung zum Server wurde beendet.")))

    def _ack(self, row: dict[str, Any], info: dict[str, Any] | None = None) -> dict[str, Any]:
        """Antwort auf eine Meldung. Bei bestätigten Servern liegt eine neuere Fassung des Agenten als Angebot bei; ob der Agent sie
        nimmt, entscheidet allein seine lokale Richtlinie (update=off, manual, auto)."""
        message: dict[str, Any] = {"t": "ack", "state": row["state"], "interval": HEARTBEAT_SECONDS}
        if row["state"] == "active":
            info = info if info is not None else _json(row["info"])
            offer = self.update_offer(str(info.get("arch") or ""), str(info.get("agent_version") or ""))
            if offer is not None:
                message["offer"] = offer
        return message

    async def _renew(self, conn: AgentConn, data: dict[str, Any]) -> bool:
        """Ein Agent bittet um ein neues Zertifikat (sein altes läuft bald ab). Gibt False zurück, wenn die Verbindung enden soll."""
        now = self._clock()
        if conn.last_renew and now - conn.last_renew < RENEW_MIN_SECONDS:
            conn.violations += 1
            return conn.violations < 5
        conn.last_renew = now
        row = self.repo.server_get(conn.server_id)
        if row is None or row["state"] == "blocked":
            return False
        try:
            csr = self.pki.parse_csr(data.get("csr"))
        except ServerError:
            conn.violations += 1
            return conn.violations < 5
        cert_pem, cert_hash = self.pki.sign_csr(csr, conn.server_id)
        if not self.repo.server_renewed(conn.server_id, cert_hash):
            return False
        self.repo.audit_add("event", tr("Zertifikat erneuert"), server_id=conn.server_id, server_name=row["name"], result="ok")
        log.info("Server-Hub: Zertifikat von %s erneuert", row["name"])
        await self._send(conn.ws, {"t": "renewed", "cert": cert_pem})
        return True

    @staticmethod
    def _result(conn: AgentConn, data: dict[str, Any]) -> None:
        call_id = data.get("id")
        future = conn.pending.get(call_id) if isinstance(call_id, int) else None
        if future is None or future.done():
            return
        if data.get("ok") is True:
            future.set_result(str(data.get("text") or "")[:MAX_RESULT_CHARS])
        else:
            future.set_exception(ServerError(clean_text(data.get("error"), 600, default=tr("Der Server hat den Aufruf abgelehnt."))))

    # -- HTTP: Download des Agenten (gleicher Port, gleiche TLS-Verbindung)

    def agent_binaries(self) -> dict[str, Path]:
        """Mitgelieferte Agenten je Architektur (``amd64``, ``arm64``)."""
        found: dict[str, Path] = {}
        if self.agent_dir and self.agent_dir.is_dir():
            for arch in ("amd64", "arm64"):
                path = self.agent_dir / f"copilot-agent-linux-{arch}"
                if path.is_file():
                    found[arch] = path
        return found

    def agent_hashes(self) -> dict[str, str]:
        return {arch: hashlib.sha256(path.read_bytes()).hexdigest() for arch, path in self.agent_binaries().items()}

    def _process_request(self, connection: Any, request: Any) -> Any:
        """Gewöhnliche HTTP-Anfragen (kein WebSocket) beantworten: nur der Download des Agenten, mit gültigem Schlüssel."""
        path, _, query = request.path.partition("?")
        if path in ("/enroll", "/agent"):
            return None
        peer = (connection.remote_address or ("", 0))[0]
        if not path.startswith(("/download/", "/agent-update/")):
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        if not self._download_limit.allow(peer):
            return connection.respond(HTTPStatus.TOO_MANY_REQUESTS, "Too many requests\n")
        if path.startswith("/agent-update/"):
            # Aktualisierung: nur für einen bestätigten Server, der sich mit seinem Zertifikat ausweist (kein Schlüssel nötig)
            ssl_object = connection.transport.get_extra_info("ssl_object")
            der = ssl_object.getpeercert(binary_form=True) if ssl_object is not None else None
            found = self.repo.server_by_cert(_sha256(der)) if der else None
            if found is None or found[0]["state"] != "active":
                return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
            binary = self.agent_binaries().get(path.removeprefix("/agent-update/"))
        else:
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if self.repo.key_check(params.get("key")) is None:
                return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
            binary = self.agent_binaries().get(path.removeprefix("/download/copilot-agent-linux-"))
        if binary is None:
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        body = binary.read_bytes()
        headers = Headers([("Content-Type", "application/octet-stream"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
        return Response(200, "OK", headers, body)

    # -- Betrieb

    async def serve(self, port: int = HUB_PORT, host: str = "0.0.0.0") -> None:
        """Listener auf ``HUB_PORT`` bis zum Abbruch der Aufgabe (``port`` und ``host`` nur für Tests)."""
        from websockets.asyncio.server import serve

        self._loop = asyncio.get_running_loop()
        context = await asyncio.to_thread(self.pki.ssl_context, self.hosts())
        self._server = await serve(
            self._handle, host, port, ssl=context, max_size=MAX_MESSAGE_BYTES, process_request=self._process_request,
            ping_interval=20, ping_timeout=20, server_header=None, compression=None,
        )
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("Server-Hub aktiv auf Port %d (%s)", self.port, self.pki.ca_fingerprint)
        try:
            await asyncio.gather(self._server.serve_forever(), self.watch())
        finally:
            self._server.close()
            await self._server.wait_closed()

    async def watch(self) -> None:
        """Alle paar Sekunden prüfen, ob ein bestätigter Server verschwunden oder wieder da ist; das Protokoll aufräumen."""
        ticks = 0
        while True:
            await asyncio.sleep(15)
            ticks += 1
            try:
                await self.check_online()
                if ticks % 240 == 0:
                    self.repo.audit_prune()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("Server-Hub: Prüfung fehlgeschlagen", exc_info=True)

    async def check_online(self) -> None:
        for row in self.repo.server_list():
            if row["state"] != "active":
                self._online.pop(row["id"], None)
                continue
            status, _ = self.status_of(row)
            online = status in ("online", "degraded")
            before = self._online.get(row["id"])
            self._online[row["id"]] = online
            if before is None:  # erste Beobachtung (z. B. nach einem Neustart des Add-ons): nichts melden
                continue
            if before and not online:
                self.repo.audit_add("event", tr("Server offline (keine Meldung seit {n} Sekunden)", n=OFFLINE_AFTER), server_id=row["id"], server_name=row["name"], result="offline")
                if self.notify is not None:
                    await self.notify(tr("Server {name} ist offline", name=row["name"]), tr("Der Server {name} hat sich seit mehr als {n} Sekunden nicht gemeldet.", name=row["name"], n=OFFLINE_AFTER))
            elif online and not before:
                self.repo.audit_add("event", tr("Server wieder online"), server_id=row["id"], server_name=row["name"], result="ok")


def _json(text: Any) -> dict[str, Any]:
    try:
        value = json.loads(text) if isinstance(text, str) else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


_HUBS: "weakref.WeakKeyDictionary[Store, ServerHub]" = weakref.WeakKeyDictionary()


def hub_for(store: Store, settings: Settings, directory: Path | None = None, agent_dir: Path | None = None) -> ServerHub:
    """Ein Hub je Datenbank, gemeinsam für Ingress, Domain und den Listener (alle im selben Prozess)."""
    hub = _HUBS.get(store)
    if hub is None or hub.settings is not settings:
        if directory is None:
            raise ValueError("directory fehlt")
        hub = _HUBS[store] = ServerHub(store, settings, directory, agent_dir)
    return hub
