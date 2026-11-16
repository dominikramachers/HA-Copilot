// Package plan ist der ändernde Teil des Agenten (Etappe 2): Aus einem Auftrag der KI wird eine **Einstufung** (Risikostufe,
// exakter Befehl, Vorschau, Rückweg), erst nach Freigabe in der App wird genau diese Einstufung ausgeführt.
//
// Die Einstufung berechnet der Agent selbst, nicht die KI und nicht der Hub. Stufen:
//
//	1  Ändern, umkehrbar (Dienst neu starten, Paket aus der Standardquelle installieren, lesender Befehl)
//	2  Ändern, weitreichend (alle Pakete aktualisieren, Paket entfernen, unbekannter Befehl, Befehl als root, Shell-Skript)
//	3  zerstörerisch oder Aussperrgefahr (Datenträger, Benutzer, Neustart, SSH oder Netz stoppen): wird nie ausgeführt
//
// Die Einstufung von freien Befehlen ist eine Annäherung und nie vollständig. Deshalb ist alles Unbekannte mindestens Stufe 2, und
// jeder Befehl braucht ohnehin die Freigabe mit dem exakten Wortlaut.
package plan

import (
	"errors"
	"fmt"
	"path"
	"regexp"
	"strings"
	"time"
)

// Werkzeuge, die der Hub zum Ändern anfragen darf.
const (
	ToolService = "service_action"
	ToolPackage = "package"
	ToolRun     = "run_command"
)

// Names sind die ändernden Werkzeuge (CHANGE_TOOLS in app/servers.py).
var Names = []string{ToolService, ToolPackage, ToolRun}

// Args sind die Argumente eines Auftrags.
type Args map[string]any

func (a Args) text(key string) string {
	s, _ := a[key].(string)
	return strings.TrimSpace(s)
}

func (a Args) flag(key string) bool {
	b, _ := a[key].(bool)
	return b
}

func (a Args) list(key string, maxItems, maxLen int) ([]string, error) {
	raw, ok := a[key]
	if !ok || raw == nil {
		return nil, nil
	}
	items, ok := raw.([]any)
	if !ok {
		if strs, ok2 := raw.([]string); ok2 {
			for _, s := range strs {
				items = append(items, s)
			}
		} else {
			return nil, fmt.Errorf("%s muss eine Liste sein", key)
		}
	}
	if len(items) > maxItems {
		return nil, fmt.Errorf("%s hat zu viele Einträge (höchstens %d)", key, maxItems)
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		s, ok := item.(string)
		if !ok || len(s) > maxLen || strings.ContainsRune(s, 0) {
			return nil, fmt.Errorf("%s enthält einen ungültigen Eintrag", key)
		}
		out = append(out, s)
	}
	return out, nil
}

func (a Args) seconds(key string, def, low, high int) (int, error) {
	v, ok := a[key]
	if !ok || v == nil {
		return def, nil
	}
	f, ok := v.(float64)
	if !ok || f != float64(int(f)) {
		return 0, fmt.Errorf("%s muss eine ganze Zahl sein", key)
	}
	n := int(f)
	if n < low {
		n = low
	}
	if n > high {
		n = high
	}
	return n, nil
}

// Action ist ein eingestufter Auftrag: genau das, was ausgeführt wird.
type Action struct {
	Tool    string
	Class   int
	Reason  string   // warum diese Stufe
	Summary string   // ein Satz für die Freigabekarte
	Command string   // der Befehl im Klartext (Anzeige)
	Root    bool     // läuft über den Helfer als root
	Argv    []string // exakt auszuführen, ohne Shell
	Env     []string // zusätzliches Umfeld
	Timeout time.Duration
	Undo    string
	Check   []string // lesender Befehl für die Nachprüfung (läuft ohne Rechte)
	Args    Args     // normalisierte Argumente (gehen in den Hash)
}

// Classify bildet einen Auftrag auf eine Action ab. Ungültige Angaben ergeben einen Fehler; Stufe 3 ist eine gültige Antwort
// (der Aufrufer lehnt sie ab).
func Classify(tool string, args Args) (Action, error) {
	switch tool {
	case ToolService:
		return classifyService(args)
	case ToolPackage:
		return classifyPackage(args)
	case ToolRun:
		return classifyRun(args)
	}
	return Action{}, errors.New("unbekanntes Werkzeug")
}

// ------------------------------------------------------------------------------------------------ Dienste

var (
	unitRe      = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9:_.@\-]{0,99}$`)
	unitSuffix  = map[string]bool{"service": true, "timer": true, "socket": true, "path": true}
	serviceActs = map[string]string{"start": "starten", "stop": "stoppen", "restart": "neu starten", "reload": "neu laden", "enable": "beim Start aktivieren", "disable": "beim Start deaktivieren"}
	// niemals anfassen
	neverUnits = []string{"copilot-agent", "copilot-helper"}
	// Aussperrgefahr: nur starten, neu starten oder neu laden (Stufe 2), Stoppen und Deaktivieren sind gesperrt
	lockoutUnits = []string{"ssh", "sshd", "dbus", "dbus-broker", "networking", "networkmanager", "network-manager", "polkit", "getty", "user", "systemd-", "wpa_supplicant", "netplan", "init"}
	// weitreichende Wirkung: Stufe 2
	wideUnits = []string{"ufw", "nftables", "iptables", "firewalld", "fail2ban", "docker", "containerd", "apparmor", "auditd", "cron", "crond", "libvirtd", "lxd", "snapd"}
)

func unitBase(unit string) string {
	base := strings.ToLower(unit)
	if i := strings.LastIndex(base, "."); i > 0 {
		base = base[:i]
	}
	if i := strings.Index(base, "@"); i > 0 {
		base = base[:i]
	}
	return base
}

func matchesUnit(base string, list []string) bool {
	for _, item := range list {
		if base == item || (strings.HasSuffix(item, "-") && strings.HasPrefix(base, item)) {
			return true
		}
	}
	return false
}

func classifyService(args Args) (Action, error) {
	unit := args.text("unit")
	action := strings.ToLower(args.text("action"))
	if _, ok := serviceActs[action]; !ok {
		return Action{}, errors.New("action muss start, stop, restart, reload, enable oder disable sein")
	}
	if !strings.Contains(unit, ".") {
		unit += ".service"
	}
	if !unitRe.MatchString(unit) || !unitSuffix[unit[strings.LastIndex(unit, ".")+1:]] {
		return Action{}, errors.New("unit fehlt oder ist ungültig (erlaubt sind Dienste, Timer, Sockets und Pfade, z. B. nginx.service)")
	}
	base := unitBase(unit)
	a := Action{
		Tool: ToolService, Class: 1, Root: true, Timeout: 120 * time.Second,
		Argv:  []string{"systemctl", action, "--", unit},
		Check: []string{"systemctl", "status", "--no-pager", "-n", "8", "--", unit},
		Args:  Args{"unit": unit, "action": action},
	}
	a.Command = "systemctl " + action + " " + unit
	a.Summary = fmt.Sprintf("%s %s", unit, serviceActs[action])
	switch {
	case matchesUnit(base, neverUnits):
		a.Class, a.Reason = 3, "Der Agent selbst und sein Helfer werden nie über die KI verändert."
	case matchesUnit(base, lockoutUnits) && (action == "stop" || action == "disable"):
		a.Class, a.Reason = 3, "Aussperrgefahr: Anmeldung, Netzwerk oder Systemdienst dürfen nicht gestoppt oder deaktiviert werden."
	case matchesUnit(base, lockoutUnits):
		a.Class, a.Reason = 2, "Dieser Dienst kann beim Neustart kurz die Verbindung unterbrechen (Anmeldung, Netzwerk oder Systemdienst)."
	case matchesUnit(base, wideUnits):
		a.Class, a.Reason = 2, "Dieser Dienst hat weitreichende Wirkung (Firewall, Container, Zeitplan oder Sicherheit)."
	default:
		a.Reason = "Ein einzelner Dienst, jederzeit wieder umkehrbar."
	}
	switch action {
	case "start":
		a.Undo = "systemctl stop " + unit
	case "stop":
		a.Undo = "systemctl start " + unit
	case "restart", "reload":
		a.Undo = "Nicht nötig: der Dienst läuft danach wie zuvor weiter."
	case "enable":
		a.Undo = "systemctl disable " + unit
	case "disable":
		a.Undo = "systemctl enable " + unit
	}
	return a, nil
}

// ------------------------------------------------------------------------------------------------ Pakete

var (
	packageRe = regexp.MustCompile(`^[a-z0-9][a-z0-9+.\-]{0,99}(:[a-z0-9]{2,10})?$`)
	// Pakete, die nicht entfernt werden (der Server würde unbrauchbar oder unerreichbar)
	protectedPackages = []string{
		"openssh-server", "openssh-client", "ssh", "systemd", "systemd-sysv", "libc6", "apt", "dpkg", "sudo", "bash", "coreutils", "login",
		"init", "util-linux", "netplan.io", "network-manager", "ifupdown", "networkd-dispatcher", "dbus", "ubuntu-minimal", "ubuntu-standard",
		"ubuntu-server", "debian-archive-keyring", "ubuntu-keyring", "linux-image-", "linux-generic", "linux-base", "grub", "libpam",
	}
	packageActs = map[string]string{"update": "Paketlisten aktualisieren", "install": "installieren", "remove": "entfernen", "upgrade": "aktualisieren"}
)

func isProtectedPackage(name string) bool {
	name = strings.ToLower(name)
	if i := strings.Index(name, ":"); i > 0 {
		name = name[:i]
	}
	for _, p := range protectedPackages {
		if name == p || (strings.HasSuffix(p, "-") && strings.HasPrefix(name, p)) || (p == "grub" && strings.HasPrefix(name, "grub")) || (p == "libpam" && strings.HasPrefix(name, "libpam")) {
			return true
		}
	}
	return false
}

// AptBase sind die gemeinsamen Optionen aller apt-Aufrufe (nicht interaktiv, alte Konfiguration behalten, auf die dpkg-Sperre warten).
func aptBase() []string {
	return []string{"apt-get", "-y", "-q", "-o", "DPkg::Lock::Timeout=120", "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"}
}

func classifyPackage(args Args) (Action, error) {
	action := strings.ToLower(args.text("action"))
	if _, ok := packageActs[action]; !ok {
		return Action{}, errors.New("action muss update, install, remove oder upgrade sein")
	}
	pkgs, err := args.list("packages", 20, 100)
	if err != nil {
		return Action{}, err
	}
	for _, p := range pkgs {
		if !packageRe.MatchString(p) {
			return Action{}, fmt.Errorf("ungültiger Paketname: %q (erlaubt sind kleingeschriebene Namen ohne Versionsangabe)", p)
		}
	}
	if (action == "install" || action == "remove") && len(pkgs) == 0 {
		return Action{}, errors.New("packages muss mindestens ein Paket nennen")
	}
	if action == "update" && len(pkgs) > 0 {
		return Action{}, errors.New("update braucht keine Pakete")
	}
	a := Action{
		Tool: ToolPackage, Class: 1, Root: true, Timeout: 15 * time.Minute,
		Env:  []string{"DEBIAN_FRONTEND=noninteractive", "APT_LISTCHANGES_FRONTEND=none", "NEEDRESTART_MODE=l"},
		Args: Args{"action": action, "packages": toAny(pkgs)},
	}
	argv := aptBase()
	switch action {
	case "update":
		a.Timeout = 5 * time.Minute
		argv = append(argv, "update")
		a.Summary = "Paketlisten aktualisieren (apt-get update)"
		a.Reason = "Lädt nur die Paketlisten, installiert nichts."
		a.Undo = "Nicht nötig."
	case "install":
		argv = append(argv, "install", "--")
		argv = append(argv, pkgs...)
		a.Summary = "Installieren: " + strings.Join(pkgs, ", ")
		a.Reason = "Pakete aus den eingerichteten Quellen installieren."
		a.Undo = "apt-get remove " + strings.Join(pkgs, " ")
		a.Check = append([]string{"dpkg-query", "-W", "-f=${Package} ${Version} ${db:Status-Abbrev}\\n"}, pkgs...)
	case "remove":
		argv = append(argv, "remove", "--")
		argv = append(argv, pkgs...)
		a.Class = 2
		a.Summary = "Entfernen: " + strings.Join(pkgs, ", ")
		a.Reason = "Das Entfernen von Paketen kann Dienste und Abhängigkeiten betreffen."
		a.Undo = "apt-get install " + strings.Join(pkgs, " ")
		a.Check = append([]string{"dpkg-query", "-W", "-f=${Package} ${Version} ${db:Status-Abbrev}\\n"}, pkgs...)
		for _, p := range pkgs {
			if isProtectedPackage(p) {
				a.Class, a.Reason = 3, fmt.Sprintf("%s gehört zum Grundsystem oder zur Anmeldung und wird nie über die KI entfernt.", p)
			}
		}
	case "upgrade":
		if len(pkgs) == 0 {
			argv = append(argv, "upgrade")
			a.Class = 2
			a.Summary = "Alle Pakete aktualisieren (apt-get upgrade)"
			a.Reason = "Viele Pakete können sich gleichzeitig ändern, auch Dienste werden dabei neu gestartet."
			a.Undo = "Nicht einfach umkehrbar (alte Versionen müssten einzeln neu installiert werden)."
		} else {
			argv = append(argv, "install", "--only-upgrade", "--")
			argv = append(argv, pkgs...)
			a.Summary = "Aktualisieren: " + strings.Join(pkgs, ", ")
			a.Reason = "Nur die genannten Pakete werden auf die neueste Version gebracht."
			a.Undo = "Nicht einfach umkehrbar (die alte Version müsste gezielt neu installiert werden)."
			a.Check = append([]string{"dpkg-query", "-W", "-f=${Package} ${Version} ${db:Status-Abbrev}\\n"}, pkgs...)
		}
	}
	a.Argv = argv
	a.Command = strings.Join(argv, " ")
	return a, nil
}

func toAny(items []string) []any {
	out := make([]any, len(items))
	for i, s := range items {
		out[i] = s
	}
	return out
}

// SimulationArgv ist der Trockenlauf zu einer Paketaktion (ohne -y, ohne Sperre; läuft ohne Rechte).
func SimulationArgv(a Action) []string {
	var out []string
	for i := 0; i < len(a.Argv); i++ {
		switch a.Argv[i] {
		case "-y":
			continue
		case "-o":
			if i+1 < len(a.Argv) && strings.HasPrefix(a.Argv[i+1], "DPkg::Lock") {
				i++
				continue
			}
		}
		out = append(out, a.Argv[i])
	}
	// nach „apt-get“ die Simulation und ohne Sperre
	return append([]string{out[0], "-s", "-o", "Debug::NoLocking=1"}, out[1:]...)
}

// ------------------------------------------------------------------------------------------------ Freie Befehle

var (
	argv0Re      = regexp.MustCompile(`^[A-Za-z0-9._+/\-]{1,200}$`)
	shellNames   = map[string]bool{"sh": true, "bash": true, "dash": true, "zsh": true, "ksh": true, "fish": true, "ash": true}
	destructive  = regexp.MustCompile(`^(mkfs(\..+)?|mke2fs|mkswap|fdisk|sfdisk|cfdisk|parted|gdisk|sgdisk|wipefs|blkdiscard|shred|passwd|chpasswd|usermod|userdel|deluser|useradd|adduser|groupadd|groupdel|visudo|reboot|poweroff|shutdown|halt|init|telinit|insmod|rmmod|modprobe|kexec|cryptsetup|lvremove|vgremove|pvremove|lvreduce|vgreduce)$`)
	firewallCmds = map[string]bool{"iptables": true, "ip6tables": true, "nft": true, "ufw": true, "firewall-cmd": true, "iptables-restore": true, "ip6tables-restore": true}
	sensitivePat = regexp.MustCompile(`(?i)(/etc/shadow|/etc/gshadow|/etc/sudoers|/\.ssh/|/\.gnupg|/etc/ssl/private|\.pem$|\.key$|\.env$|id_rsa|id_ed25519|/proc/[0-9]+/environ|^/root(/|$)|\.kdbx|secret|credential|token)`)
	systemTop    = map[string]bool{"/": true, "/etc": true, "/usr": true, "/bin": true, "/sbin": true, "/lib": true, "/lib32": true, "/lib64": true, "/boot": true, "/var": true, "/dev": true, "/proc": true, "/sys": true, "/root": true, "/home": true, "/opt": true, "/srv": true, "/run": true}
	// Lesende Befehle: ändern nichts (Stufe 1). Was hier fehlt, ist Stufe 2.
	readCmds = map[string]bool{
		"df": true, "du": true, "free": true, "uptime": true, "uname": true, "hostname": true, "whoami": true, "id": true, "date": true, "ps": true,
		"lsblk": true, "findmnt": true, "lscpu": true, "lsmod": true, "lsof": true, "ls": true, "stat": true, "wc": true, "head": true, "tail": true,
		"cat": true, "grep": true, "ss": true, "getent": true, "dig": true, "host": true, "nslookup": true, "ping": true, "w": true, "who": true,
		"last": true, "nproc": true, "pgrep": true, "file": true, "sort": true, "uniq": true, "ldd": true, "readlink": true, "realpath": true,
	}
	// Lesende Unterbefehle bestimmter Programme.
	readSub = map[string]map[string]bool{
		"systemctl":  {"status": true, "is-active": true, "is-enabled": true, "is-failed": true, "list-units": true, "list-timers": true, "list-unit-files": true, "show": true, "cat": true, "list-sockets": true, "list-dependencies": true},
		"ip":         {"a": true, "addr": true, "address": true, "route": true, "r": true, "link": true, "l": true, "neigh": true, "n": true, "rule": true, "-s": true, "-br": true, "-4": true, "-6": true, "-c": true, "-j": true, "-o": true},
		"apt":        {"list": true, "show": true, "policy": true, "search": true},
		"apt-cache":  {"policy": true, "show": true, "search": true, "depends": true, "rdepends": true, "madison": true},
		"dpkg":       {"-l": true, "-s": true, "-L": true, "-S": true, "--list": true, "--status": true, "--listfiles": true, "--search": true},
		"docker":     {"ps": true, "logs": true, "inspect": true, "images": true, "stats": true, "top": true, "version": true, "info": true, "port": true},
		"journalctl": nil, // eigene Prüfung
	}
	ipWrite       = map[string]bool{"add": true, "del": true, "delete": true, "set": true, "flush": true, "change": true, "replace": true, "append": true, "up": true, "down": true}
	journalForbid = []string{"--vacuum", "--rotate", "--flush", "--sync", "--setup-keys", "--update-catalog", "--relinquish", "--smart-relinquish", "--sign"}
)

func isFlag(s string) bool { return strings.HasPrefix(s, "-") && len(s) > 1 }

func protectedTarget(p string) bool {
	clean := path.Clean(strings.TrimSuffix(strings.TrimSuffix(p, "/*"), "/"))
	if p == "/" || p == "/*" || clean == "/" {
		return true
	}
	return systemTop[clean]
}

func recursiveFlag(args []string) bool {
	for _, s := range args {
		if s == "--recursive" || (strings.HasPrefix(s, "-") && !strings.HasPrefix(s, "--") && strings.ContainsAny(s, "rR")) {
			return true
		}
	}
	return false
}

// Muster für Shell-Skripte (Stufe 3). Das ist eine Annäherung: jedes Skript ist ohnehin mindestens Stufe 2 und wird wörtlich gezeigt.
var scriptDeny = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(^|[\s;&|(` + "`" + `])(mkfs(\.\w+)?|mke2fs|mkswap|wipefs|fdisk|sfdisk|parted|sgdisk|shred|blkdiscard|reboot|poweroff|shutdown|halt|telinit|passwd|chpasswd|usermod|userdel|deluser|useradd|adduser|visudo|insmod|rmmod|modprobe|cryptsetup|kexec)([\s;&|)]|$)`),
	regexp.MustCompile(`(?i)\bdd\b[^\n;|&]*\bof=/dev/`),
	regexp.MustCompile(`--no-preserve-root`),
	regexp.MustCompile(`(?i)\brm\b[^\n;|&]*\s-[a-zA-Z]*[rR][^\n;|&]*\s/(etc|usr|bin|sbin|lib|lib32|lib64|boot|var|dev|proc|sys|root|home|opt|srv|run)?(/\*?)?(\s|$|;|&|\|)`),
	regexp.MustCompile(`(?i)\b(chmod|chown|chgrp)\b[^\n;|&]*\s-[a-zA-Z]*R[^\n;|&]*\s/(etc|usr|bin|sbin|lib|boot|var|dev|root|home|opt)?(/\*?)?(\s|$|;|&|\|)`),
	regexp.MustCompile(`(?i)\b(iptables|ip6tables|nft|ufw)\b[^\n;|&]*(\s-F\b|\s-X\b|--flush|flush\s+ruleset|\breset\b|\bdisable\b)`),
	regexp.MustCompile(`\|\s*(ba|z|da|k)?sh\b`),
	regexp.MustCompile(`:\(\)\s*\{`),
	regexp.MustCompile(`>\s*/dev/(sd|nvme|vd|hd|xvd|mapper|disk)`),
	regexp.MustCompile(`(authorized_keys|/etc/shadow|/etc/gshadow|/etc/sudoers)`),
}

func scriptClass(script string) (int, string) {
	for _, re := range scriptDeny {
		if re.MatchString(script) {
			return 3, "Das Skript enthält Anweisungen, die Daten zerstören, Benutzer oder Anmeldung verändern oder den Server abschalten könnten."
		}
	}
	return 2, "Ein Shell-Skript kann beliebig viel tun. Prüfe den Wortlaut genau."
}

// argvClass stuft einen Befehl mit Argumentliste ein.
func argvClass(argv []string) (int, string) {
	base := path.Base(argv[0])
	rest := argv[1:]
	if destructive.MatchString(base) {
		return 3, fmt.Sprintf("%s kann Datenträger, Benutzer oder den Betrieb des Servers zerstören.", base)
	}
	for _, s := range argv {
		if s == "--no-preserve-root" {
			return 3, "Schutz des Wurzelverzeichnisses abgeschaltet."
		}
	}
	switch base {
	case "dd":
		for _, s := range rest {
			if strings.HasPrefix(s, "of=/dev/") {
				return 3, "dd würde direkt auf einen Datenträger schreiben."
			}
		}
		return 2, "dd schreibt Rohdaten."
	case "rm":
		if recursiveFlag(rest) {
			for _, s := range rest {
				if !isFlag(s) && protectedTarget(s) {
					return 3, "Löschen eines Systemverzeichnisses."
				}
			}
			return 2, "Rekursives Löschen."
		}
		return 2, "Löscht Dateien."
	case "chmod", "chown", "chgrp":
		if recursiveFlag(rest) {
			for _, s := range rest {
				if !isFlag(s) && protectedTarget(s) {
					return 3, "Rechte eines Systemverzeichnisses rekursiv ändern."
				}
			}
		}
		return 2, "Ändert Rechte oder Besitzer."
	case "kill", "pkill", "killall":
		for _, s := range rest {
			if s == "1" || s == "-1" {
				return 3, "Prozess 1 oder alle Prozesse zu beenden würde den Server stoppen."
			}
		}
		return 2, "Beendet Prozesse."
	case "systemctl":
		for _, s := range rest {
			switch s {
			case "reboot", "poweroff", "halt", "kexec", "suspend", "hibernate", "rescue", "emergency", "isolate":
				return 3, "Würde den Server abschalten oder neu starten."
			}
		}
		sub := ""
		for _, s := range rest {
			if !isFlag(s) {
				sub = s
				break
			}
		}
		if readSub["systemctl"][sub] {
			return 1, "Lesender Befehl."
		}
		if sub == "stop" || sub == "disable" || sub == "mask" || sub == "kill" {
			for _, s := range rest {
				if !isFlag(s) && s != sub {
					if b := unitBase(s); matchesUnit(b, neverUnits) || matchesUnit(b, lockoutUnits) {
						return 3, "Aussperrgefahr: dieser Dienst darf nicht gestoppt oder deaktiviert werden."
					}
				}
			}
		}
		return 2, "Ändert den Zustand von Diensten."
	}
	if firewallCmds[base] {
		for _, s := range rest {
			switch s {
			case "-F", "-X", "--flush", "flush", "reset", "disable", "-Z":
				return 3, "Firewall-Regeln würden geleert oder abgeschaltet (Aussperrgefahr)."
			}
		}
		return 2, "Ändert oder liest Firewall-Regeln."
	}
	if shellNames[base] {
		for i, s := range rest {
			if s == "-c" && i+1 < len(rest) {
				return scriptClass(rest[i+1])
			}
		}
		return 2, "Eine Shell kann beliebig viel tun."
	}
	// lesende Befehle
	if readCmds[base] {
		for _, s := range rest {
			if sensitivePat.MatchString(s) {
				return 2, "Greift auf möglicherweise vertrauliche Dateien zu."
			}
		}
		return 1, "Lesender Befehl: verändert nichts."
	}
	switch base {
	case "ip":
		for _, s := range rest {
			if ipWrite[s] {
				return 2, "Ändert die Netzwerkeinstellungen."
			}
		}
		return 1, "Lesender Befehl: verändert nichts."
	case "journalctl":
		for _, s := range rest {
			for _, bad := range journalForbid {
				if strings.HasPrefix(s, bad) {
					return 2, "Ändert das Journal."
				}
			}
		}
		return 1, "Lesender Befehl: verändert nichts."
	case "apt", "apt-cache", "dpkg", "docker":
		sub := ""
		for _, s := range rest {
			if !isFlag(s) || (base == "dpkg" && readSub["dpkg"][s]) {
				sub = s
				break
			}
		}
		if readSub[base][sub] {
			return 1, "Lesender Befehl: verändert nichts."
		}
		return 2, "Ändert Pakete oder Container."
	}
	return 2, "Unbekannter Befehl: er kann Änderungen vornehmen, die sich nicht einstufen lassen."
}

func classifyRun(args Args) (Action, error) {
	argv, err := args.list("argv", 64, 4096)
	if err != nil {
		return Action{}, err
	}
	script := args.text("script")
	if (len(argv) == 0) == (script == "") {
		return Action{}, errors.New("gib entweder argv (Programm und Argumente als Liste) oder script an, nicht beides")
	}
	root := args.flag("root")
	timeout, err := args.seconds("timeout_s", 60, 1, 600)
	if err != nil {
		return Action{}, err
	}
	a := Action{Tool: ToolRun, Root: root, Timeout: time.Duration(timeout) * time.Second}
	norm := Args{"root": root, "timeout_s": float64(timeout)}
	if script != "" {
		if len(script) > 4000 || strings.ContainsRune(script, 0) {
			return Action{}, errors.New("script ist zu lang (höchstens 4000 Zeichen) oder ungültig")
		}
		a.Class, a.Reason = scriptClass(script)
		a.Argv = []string{"/bin/sh", "-c", script}
		a.Command = "/bin/sh -c " + shellQuote(script)
		a.Summary = "Shell-Skript ausführen"
		norm["script"] = script
	} else {
		if !argv0Re.MatchString(argv[0]) {
			return Action{}, errors.New("argv[0] muss ein Programmname sein (ohne Leerzeichen, Argumente als weitere Listeneinträge)")
		}
		a.Class, a.Reason = argvClass(argv)
		a.Argv = argv
		quoted := make([]string, len(argv))
		for i, s := range argv {
			quoted[i] = shellQuote(s)
		}
		a.Command = strings.Join(quoted, " ")
		a.Summary = "Befehl ausführen: " + trimTo(a.Command, 90)
		norm["argv"] = toAny(argv)
	}
	if root && a.Class < 2 {
		a.Class, a.Reason = 2, "Der Befehl läuft als root. "+a.Reason
	}
	if a.Class == 1 {
		a.Undo = "Nicht nötig: der Befehl verändert nichts."
	} else {
		a.Undo = "Nicht automatisch umkehrbar."
	}
	a.Args = norm
	return a, nil
}

func trimTo(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}

var shellSafe = regexp.MustCompile(`^[A-Za-z0-9_@%+=:,./-]+$`)

// shellQuote zeigt ein Argument so, wie man es in eine Shell tippen würde (nur Anzeige, ausgeführt wird ohne Shell).
func shellQuote(s string) string {
	if s != "" && shellSafe.MatchString(s) {
		return s
	}
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}
