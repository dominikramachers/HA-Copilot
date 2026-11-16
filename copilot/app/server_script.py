"""Installationsskript für den Server-Agenten.

Das Skript wird für jede Anfrage frisch erzeugt und enthält schon alle Angaben (Adresse des Hubs, Registrierungsschlüssel,
Fingerabdruck der Zertifizierungsstelle, Prüfsummen der Programmdateien, Name des Servers). Man kopiert es auf den Server und führt es
dort als root aus, oder lädt es herunter. Es ist bewusst lesbar gehalten: wer es vor dem Ausführen prüfen will, kann das.

Was es tut: Programmdatei vom Hub laden (Prüfsumme wird gegen den Wert im Skript geprüft), Benutzer ``copilot-agent`` ohne Anmeldung
anlegen, den Server beim Hub anmelden (der Schlüssel wird dabei verbraucht), einen systemd-Dienst mit scharfen Einschränkungen einrichten
und starten. Mit ``--uninstall`` wird alles wieder entfernt.
"""
from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone

from .servers import HUB_PORT

_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,60}[A-Za-z0-9])?$")


def hub_with_port(address: str) -> str:
    """Hub-Adresse mit Port (ohne Angabe gilt 8101)."""
    address = address.strip()
    if re.search(r"(?<!:):[0-9]{1,5}$", address) or re.search(r"\]:[0-9]{1,5}$", address):
        return address
    return f"{address}:{HUB_PORT}"


def render_script(*, hub: str, key: str, ca_fingerprint: str, hub_pin: str, hashes: dict[str, str], expires: str, max_uses: int, name: str = "") -> str:
    """Das fertige Skript als Text. Alle Werte werden für die Shell maskiert."""
    if name and not _NAME_RE.match(name):
        name = ""
    q = shlex.quote
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = f"""#!/usr/bin/env bash
# HA Copilot: Server-Agent installieren
# Erzeugt am {stamp}. Der Registrierungsschlüssel gilt bis {expires} und für höchstens {max_uses} Server.
# Ausführen als root auf dem Linux-Server (Debian oder Ubuntu):  sudo bash install-copilot-agent.sh
# Entfernen:  sudo bash install-copilot-agent.sh --uninstall
set -euo pipefail

HUB={q(hub)}
KEY={q(key)}
CA_FINGERPRINT={q(ca_fingerprint)}
HUB_PIN={q(hub_pin)}
SHA256_AMD64={q(hashes.get("amd64", ""))}
SHA256_ARM64={q(hashes.get("arm64", ""))}
SERVER_NAME={q(name)}
"""
    return head + _BODY


_BODY = r'''
BIN=/usr/local/bin/copilot-agent
USER_NAME=copilot-agent
STATE_DIR=/var/lib/copilot-agent
UNIT=/etc/systemd/system/copilot-agent.service

say() { printf '%s\n' "$*"; }
die() { printf 'Fehler: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Bitte als root ausführen (sudo bash $0)."
command -v systemctl >/dev/null 2>&1 || die "Dieses Skript braucht systemd."

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now copilot-agent.service >/dev/null 2>&1 || true
    rm -f "$UNIT" "$BIN"
    systemctl daemon-reload
    rm -rf "$STATE_DIR"
    id "$USER_NAME" >/dev/null 2>&1 && userdel "$USER_NAME" >/dev/null 2>&1 || true
    say "Der Agent wurde entfernt. Den Eintrag in der Seite Server bitte dort löschen."
    exit 0
fi

command -v curl >/dev/null 2>&1 || die "curl fehlt (apt install curl)."
command -v sha256sum >/dev/null 2>&1 || die "sha256sum fehlt (Paket coreutils)."
command -v runuser >/dev/null 2>&1 || die "runuser fehlt (Paket util-linux)."
if ! command -v apt-get >/dev/null 2>&1; then
    say "Hinweis: apt wurde nicht gefunden. Der Agent ist für Debian und Ubuntu gedacht; Updates werden hier nicht angezeigt."
fi

case "$(uname -m)" in
    x86_64|amd64) ARCH=amd64; EXPECTED=$SHA256_AMD64 ;;
    aarch64|arm64) ARCH=arm64; EXPECTED=$SHA256_ARM64 ;;
    *) die "Nicht unterstützte Architektur: $(uname -m)" ;;
esac
[ -n "$EXPECTED" ] || die "Dieser Hub liefert keinen Agenten für $ARCH."

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
say "Lade den Agenten vom Hub ($HUB) …"
# Den Hub erkennt curl am angehefteten Schlüssel (HUB_PIN, so verlässt der Registrierungsschlüssel den Server nur zum echten Hub);
# die Datei selbst sichert zusätzlich die Prüfsumme aus diesem Skript.
curl --fail --silent --show-error --insecure --pinnedpubkey "$HUB_PIN" --max-time 180 "https://$HUB/download/copilot-agent-linux-$ARCH?key=$KEY" -o "$TMP" \
    || die "Der Hub ist nicht erreichbar oder der Schlüssel ist abgelaufen ($HUB). Firewall: dieser Server muss TCP $HUB erreichen."
ACTUAL=$(sha256sum "$TMP" | cut -d' ' -f1)
[ "$ACTUAL" = "$EXPECTED" ] || die "Die Prüfsumme der heruntergeladenen Datei stimmt nicht. Es wurde nichts installiert."
install -m 0755 -o root -g root "$TMP" "$BIN"

if ! id "$USER_NAME" >/dev/null 2>&1; then
    useradd --system --home-dir "$STATE_DIR" --no-create-home --shell /usr/sbin/nologin "$USER_NAME"
fi
GROUPS_EXTRA=""
for g in systemd-journal adm; do
    if getent group "$g" >/dev/null 2>&1; then GROUPS_EXTRA="$GROUPS_EXTRA $g"; fi
done
install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$STATE_DIR"

if [ ! -f "$STATE_DIR/agent.crt" ]; then
    say "Melde diesen Server beim Hub an …"
    ENROLL=("$BIN" enroll --hub "$HUB" --ca-fingerprint "$CA_FINGERPRINT" --state-dir "$STATE_DIR")
    if [ -n "$SERVER_NAME" ]; then ENROLL+=(--name "$SERVER_NAME"); fi
    # der Schlüssel geht über die Umgebung, damit er nicht in der Prozessliste steht
    runuser -u "$USER_NAME" -- env "COPILOT_AGENT_KEY=$KEY" "${ENROLL[@]}" || die "Die Anmeldung beim Hub ist fehlgeschlagen."
else
    say "Dieser Server ist schon angemeldet, die Anmeldung wird übersprungen."
fi

cat > "$UNIT" <<EOF
[Unit]
Description=HA Copilot Server-Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
Group=$USER_NAME
SupplementaryGroups=$GROUPS_EXTRA
ExecStart=$BIN run --state-dir $STATE_DIR
Restart=always
RestartSec=10
NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=no
ProtectControlGroups=yes
ProtectClock=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
ReadWritePaths=$STATE_DIR

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$UNIT"
systemctl daemon-reload
systemctl enable --now copilot-agent.service
sleep 2
if systemctl is-active --quiet copilot-agent.service; then
    say ""
    say "Fertig. Der Agent läuft."
    say "Dieser Server erscheint jetzt im HA Copilot unter Server als „Ausstehend“. Bitte dort bestätigen."
else
    systemctl --no-pager status copilot-agent.service || true
    die "Der Dienst läuft nicht. Siehe journalctl -u copilot-agent"
fi
'''
