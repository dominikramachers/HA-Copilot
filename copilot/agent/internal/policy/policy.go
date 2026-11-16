// Package policy liest die lokale Richtlinie des Servers (/etc/copilot-agent/policy). Sie gehört root und wird nur auf dem Server
// geändert: der Hub kann diese Grenzen nie erweitern. Fehlt die Datei, darf die KI auf diesem Server nur lesen.
package policy

import (
	"bufio"
	"errors"
	"os"
	"strconv"
	"strings"
)

// DefaultPath ist der Ort der Richtlinie.
const DefaultPath = "/etc/copilot-agent/policy"

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
}

// Default gilt ohne Datei: nur lesen.
func Default() Policy { return Policy{Operate: false, MaxClass: 2, RunCommand: true, Root: true} }

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
		key, value = strings.ToLower(strings.TrimSpace(key)), strings.ToLower(strings.TrimSpace(value))
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
		}
	}
	return p
}

// Load liest die Datei; fehlt sie oder ist sie nicht lesbar, gilt Default (nur lesen).
func Load(path string) Policy {
	data, err := os.ReadFile(path)
	if err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			return Default()
		}
		return Default()
	}
	return Parse(string(data))
}
