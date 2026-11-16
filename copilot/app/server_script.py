"""Installationsskript für den Server-Agenten.

Das Skript wird für jede Anfrage frisch erzeugt und enthält schon alle Angaben (Adresse des Hubs, Registrierungsschlüssel,
Fingerabdruck der Zertifizierungsstelle, Prüfsummen der Programmdateien, Name des Servers). Man kopiert es auf den Server und führt es
dort als root aus, oder lädt es herunter. Es ist bewusst lesbar gehalten: wer es vor dem Ausführen prüfen will, kann das.

Was es tut: Programmdatei vom Hub laden (Prüfsumme wird gegen den Wert im Skript geprüft), Benutzer ``copilot-agent`` ohne Anmeldung
anlegen, den Server beim Hub anmelden (der Schlüssel wird dabei verbraucht), einen systemd-Dienst mit scharfen Einschränkungen einrichten
und starten. Seit 0.60.7 kommt ein zweiter, kleiner Dienst dazu (``copilot-helper``, läuft als root und führt nur freigegebene Änderungen
aus) sowie die **lokale Richtlinie** ``/etc/copilot-agent/policy``: Sie entscheidet auf dem Server selbst, ob die KI dort ändern darf
(``ki_access=operate``) oder nur lesen (``read``). Eine vorhandene Richtlinie wird nie überschrieben. Mit ``--uninstall`` wird alles
wieder entfernt.

Seit 0.61 ist **alles, was das Skript auf dem Server ausgibt oder ablegt, englisch** (Meldungen, Kommentare in der Richtlinie, Beschreibung
der Dienste); die Sprache der App gilt nur in der Oberfläche. Die Richtlinie kennt zusätzlich ``write_paths`` (wo die KI nach Freigabe
Dateien schreiben darf) und ``update`` (``off``, ``manual`` oder ``auto``: ob und wie sich der Agent selbst aktualisiert); darum
braucht ein bestehender Server für neue Fassungen kein neues Skript mehr.
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


def render_script(
    *, hub: str, key: str, ca_fingerprint: str, hub_pin: str, hashes: dict[str, str], expires: str, max_uses: int, name: str = "",
    changes: bool = True, auto_update: bool = True,
) -> str:
    """Das fertige Skript als Text. Alle Werte werden für die Shell maskiert. Das Skript selbst und alles, was es auf dem Server
    ausgibt oder ablegt, ist englisch (die Sprache der Oberfläche gilt nur in der App)."""
    if name and not _NAME_RE.match(name):
        name = ""
    q = shlex.quote
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = f"""#!/usr/bin/env bash
# HA Copilot: install the server agent
# Generated {stamp}. The registration key is valid until {expires} and for at most {max_uses} server(s).
# Run as root on the Linux server (Debian or Ubuntu):  sudo bash install-copilot-agent.sh
# Remove again:  sudo bash install-copilot-agent.sh --uninstall
set -euo pipefail

HUB={q(hub)}
KEY={q(key)}
CA_FINGERPRINT={q(ca_fingerprint)}
HUB_PIN={q(hub_pin)}
SHA256_AMD64={q(hashes.get("amd64", ""))}
SHA256_ARM64={q(hashes.get("arm64", ""))}
SERVER_NAME={q(name)}
ALLOW_CHANGES={1 if changes else 0}
AUTO_UPDATE={1 if auto_update else 0}
"""
    return head + _BODY


_BODY = r'''
BIN=/usr/local/bin/copilot-agent
USER_NAME=copilot-agent
STATE_DIR=/var/lib/copilot-agent
UNIT=/etc/systemd/system/copilot-agent.service
HELPER_UNIT=/etc/systemd/system/copilot-helper.service
POLICY_DIR=/etc/copilot-agent
POLICY=$POLICY_DIR/policy

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Please run as root (sudo bash $0)."
command -v systemctl >/dev/null 2>&1 || die "This script needs systemd."

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now copilot-agent.service copilot-helper.service >/dev/null 2>&1 || true
    systemctl stop copilot-agent-rollback.timer copilot-agent-rollback.service >/dev/null 2>&1 || true
    rm -f "$UNIT" "$HELPER_UNIT" "$BIN" "$BIN.prev" "$BIN.new"
    systemctl daemon-reload
    rm -rf "$STATE_DIR" "$POLICY_DIR"
    id "$USER_NAME" >/dev/null 2>&1 && userdel "$USER_NAME" >/dev/null 2>&1 || true
    say "The agent has been removed. Please also delete the entry on the Servers page."
    exit 0
fi

command -v curl >/dev/null 2>&1 || die "curl is missing (apt install curl)."
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is missing (package coreutils)."
command -v runuser >/dev/null 2>&1 || die "runuser is missing (package util-linux)."
if ! command -v apt-get >/dev/null 2>&1; then
    say "Note: apt was not found. The agent is meant for Debian and Ubuntu; package updates are not shown here."
fi

case "$(uname -m)" in
    x86_64|amd64) ARCH=amd64; EXPECTED=$SHA256_AMD64 ;;
    aarch64|arm64) ARCH=arm64; EXPECTED=$SHA256_ARM64 ;;
    *) die "Unsupported architecture: $(uname -m)" ;;
esac
[ -n "$EXPECTED" ] || die "This hub does not provide an agent for $ARCH."

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
say "Downloading the agent from the hub ($HUB) ..."
# curl recognises the hub by its pinned key (HUB_PIN), so the registration key only leaves this server towards the real hub;
# the file itself is protected by the checksum in this script as well.
curl --fail --silent --show-error --insecure --pinnedpubkey "$HUB_PIN" --max-time 180 "https://$HUB/download/copilot-agent-linux-$ARCH?key=$KEY" -o "$TMP" \
    || die "The hub is not reachable or the key has expired ($HUB). Firewall: this server must be able to reach TCP $HUB."
ACTUAL=$(sha256sum "$TMP" | cut -d' ' -f1)
[ "$ACTUAL" = "$EXPECTED" ] || die "The checksum of the downloaded file does not match. Nothing was installed."
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
    say "Registering this server with the hub ..."
    ENROLL=("$BIN" enroll --hub "$HUB" --ca-fingerprint "$CA_FINGERPRINT" --state-dir "$STATE_DIR")
    if [ -n "$SERVER_NAME" ]; then ENROLL+=(--name "$SERVER_NAME"); fi
    # the key is passed through the environment so that it does not show up in the process list
    runuser -u "$USER_NAME" -- env "COPILOT_AGENT_KEY=$KEY" "${ENROLL[@]}" || die "Registering with the hub failed."
else
    say "This server is already registered, registration is skipped."
fi

# Local policy: this server decides on its own what the AI may do. Neither the hub nor the AI can change it.
# An existing file is left unchanged (also when this script is run again).
install -d -m 0755 -o root -g root "$POLICY_DIR"
if [ ! -f "$POLICY" ]; then
    if [ "$ALLOW_CHANGES" = "1" ]; then ACCESS=operate; else ACCESS=read; fi
    if [ "$AUTO_UPDATE" = "1" ]; then UPDATE=auto; else UPDATE=manual; fi
    cat > "$POLICY" <<EOF
# HA Copilot: what the AI may do on this server. Takes effect immediately, no restart needed.
# Only root on this server can change it.
#
# ki_access     read     = read only (nothing is changed)
#               operate  = changes are possible, but only after the person approves them in the chat
ki_access=$ACCESS
# max_class     1 = only reversible changes (restart a service, install a package)
#               2 = also far-reaching ones (remove or upgrade all packages, root commands, scripts)
max_class=2
# allow free commands (server_run): on or off
run_command=on
# allow commands with root rights: on or off (off also blocks services and apt)
root=on
# write_paths   directories in which the AI may write files (after approval), separated by commas. Empty = nowhere.
#               Login, boot and system files (for example /etc/ssh, /etc/passwd) are never written, whatever is set here.
write_paths=/etc,/opt,/srv,/var/www,/home,/usr/local/etc
# update        how this agent is updated to the version shipped with the hub:
#               off     = never
#               manual  = only when someone presses the button on the Servers page
#               auto    = as soon as the hub offers a newer version (a version that does not start is rolled back)
update=$UPDATE
# update_key    optional: public ed25519 key (base64). If set, only agent files signed with the matching key are installed.
#update_key=
EOF
    chmod 0644 "$POLICY"
    say "Local policy created: $POLICY (ki_access=$ACCESS, update=$UPDATE)."
else
    say "Local policy is left unchanged: $POLICY"
    say "Note: a policy from an older version has no write_paths and update lines. Defaults then apply (writing below /etc, /opt, /srv, /var/www, /home; update=manual)."
fi

# Root helper: only accepts requests from the agent, classifies them again itself and runs only what was approved (the policy applies).
cat > "$HELPER_UNIT" <<EOF
[Unit]
Description=HA Copilot root helper (only after approval)
Before=copilot-agent.service

[Service]
Type=simple
User=root
ExecStart=$BIN helper --policy $POLICY --socket /run/copilot-agent/helper.sock --agent-user $USER_NAME --state-dir $STATE_DIR --bin $BIN
RuntimeDirectory=copilot-agent
RuntimeDirectoryMode=0755
RuntimeDirectoryPreserve=yes
Restart=always
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectClock=yes
RestrictRealtime=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
LockPersonality=yes
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$HELPER_UNIT"

cat > "$UNIT" <<EOF
[Unit]
Description=HA Copilot server agent
After=network-online.target copilot-helper.service
Wants=network-online.target copilot-helper.service

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
# "restart" instead of only "--now": when this script is run again (update of the agent), the new program file must run
systemctl enable copilot-helper.service copilot-agent.service >/dev/null 2>&1
systemctl restart copilot-helper.service copilot-agent.service
sleep 2
if systemctl is-active --quiet copilot-agent.service; then
    say ""
    say "Done. The agent is running."
    if [ "$(sed -n 's/^ki_access=//p' "$POLICY" | head -n1)" = "operate" ]; then
        say "The AI may propose changes on this server; only what you approve in the chat is executed ($POLICY)."
    else
        say "The AI may only read on this server ($POLICY)."
    fi
    say "This server now shows up in HA Copilot under Servers as \"Pending\". Please confirm it there."
    say "Later updates of the agent do not need this script: use the update button on the Servers page (or update=auto in the policy)."
else
    systemctl --no-pager status copilot-agent.service || true
    die "The service is not running. See: journalctl -u copilot-agent"
fi
'''
