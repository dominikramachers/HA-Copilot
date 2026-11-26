// Package policy liest die lokale Richtlinie des Servers (/etc/copilot-agent/policy). Sie gehört root und wird nur auf dem Server
// geändert: der Hub kann diese Grenzen nie erweitern. Fehlt die Datei, darf die KI auf diesem Server nur lesen.
package policy

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// DefaultPath ist der Ort der Richtlinie.
const DefaultPath = "/etc/copilot-agent/policy"

// Update-Modi: was der Agent mit neuen Fassungen vom Hub macht.
const (
	UpdateOff    = "off"    // nie aktualisieren
	UpdateManual = "manual" // nur auf Anstoß aus der Übersicht
	UpdateAuto   = "auto"   // sobald der Hub eine neuere Fassung anbietet
)

// DefaultWritePaths sind die Verzeichnisse, in denen die KI (nach Freigabe) Dateien schreiben darf, wenn die Richtlinie nichts anderes sagt.
var DefaultWritePaths = []string{"/etc", "/opt", "/srv", "/var/www", "/home", "/usr/local/etc"}

// Policy sind die lokalen Grenzen.
type Policy struct {
	// Operate: Änderungen (Dienste, Pakete, Befehle) sind nach Freigabe in der App erlaubt (ki_access=operate).
	Operate bool
	// MaxClass ist die höchste Risikostufe, die ausgeführt wird (1 = umkehrbar, 2 = weitreichend). Stufe 3 gibt es nie.
	MaxClass int
	// RunCommand: freie Befehle (run_command) sind erlaubt.
	RunCommand bool
	// Root: Befehle dürfen über den Helfer als root laufen. Dienste und Pakete brauchen es immer.
	Root bool
	// WritePaths: Verzeichnisse, in denen Dateien geschrieben werden dürfen (file_write). Leer = nirgends.
	WritePaths []string
	// Update: off, manual oder auto (siehe oben). Ohne Angabe gilt manual.
	Update string
	// AutoUpdateDeny: die automatische Aktualisierung des Hubs (Systempakete, Sicherheitspatches) ist auf diesem Server gesperrt
	// (auto_update=deny). Ohne Angabe darf der Hub sie nach Schalter in der App einrichten.
	AutoUpdateDeny bool
	// UpdateKey: öffentlicher ed25519-Schlüssel (Base64). Ist er gesetzt, werden nur Agenten-Dateien mit passender Signatur installiert.
	UpdateKey string
}

// Default gilt ohne Datei: nur lesen.
func Default() Policy {
	return Policy{Operate: false, MaxClass: 2, RunCommand: true, Root: true, WritePaths: append([]string(nil), DefaultWritePaths...), Update: UpdateManual}
}

// cleanPaths macht aus „/etc, /opt/app“ eine Liste sauberer, absoluter Pfade (ohne „/“ selbst).
func cleanPaths(value string) []string {
	var out []string
	for _, item := range strings.Split(value, ",") {
		item = strings.TrimSpace(item)
		if item == "" || !filepath.IsAbs(item) {
			continue
		}
		item = filepath.Clean(item)
		if item == "/" {
			continue
		}
		out = append(out, item)
	}
	return out
}

// Parse liest den Inhalt einer Richtlinie (Zeilen „schlüssel=wert“, # beginnt einen Kommentar). Unbekannte Schlüssel und
// ungültige Werte werden ignoriert und lassen die vorsichtige Vorgabe stehen.
func Parse(content string) Policy {
	p := Default()
	sc := bufio.NewScanner(strings.NewReader(content))
	for sc.Scan() {
		line := sc.Text()
		if i := strings.Index(line, "#"); i >= 0 {
			line = line[:i]
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key, raw := strings.ToLower(strings.TrimSpace(key)), strings.TrimSpace(value)
		value = strings.ToLower(raw)
		switch key {
		case "ki_access":
			p.Operate = value == "operate"
		case "max_class":
			if n, err := strconv.Atoi(value); err == nil && n >= 1 && n <= 2 {
				p.MaxClass = n
			}
		case "run_command":
			p.RunCommand = value != "off"
		case "root":
			p.Root = value != "off"
		case "write_paths":
			p.WritePaths = cleanPaths(raw)
		case "update":
			if value == UpdateOff || value == UpdateManual || value == UpdateAuto {
				p.Update = value
			}
		case "auto_update":
			p.AutoUpdateDeny = value == "deny" || value == "off"
		case "update_key":
			p.UpdateKey = raw
		}
	}
	return p
}

// Load liest die Datei; fehlt sie oder ist sie nicht lesbar, gilt Default (nur lesen).
func Load(path string) Policy {
	data, err := os.ReadFile(path)
	if err != nil {
		return Default()
	}
	return Parse(string(data))
}

// WriteAllowed sagt, ob ein (bereits aufgelöster, absoluter) Pfad unter einem erlaubten Verzeichnis liegt.
func (p Policy) WriteAllowed(path string) bool {
	for _, dir := range p.WritePaths {
		if path == dir || strings.HasPrefix(path, dir+"/") {
			return true
		}
	}
	return false
}
