package tools

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"sync"
)

// Paketverwaltungen, die der Agent kennt.
const (
	PkgApt = "apt" // Debian, Ubuntu
	PkgDnf = "dnf" // Red Hat, Rocky, Alma, Fedora
)

var (
	pkgOnce sync.Once
	pkgName string
)

// PackageManager nennt die Paketverwaltung dieses Servers („apt“, „dnf“ oder leer, wenn keine bekannt ist). Das Ergebnis wird
// gemerkt; Tests ersetzen die Funktion.
var PackageManager = func() string {
	pkgOnce.Do(func() {
		if _, err := LookPath("apt-get"); err == nil {
			pkgName = PkgApt
		} else if _, err := LookPath("dnf"); err == nil {
			pkgName = PkgDnf
		}
	})
	return pkgName
}

var (
	debPackageRe = regexp.MustCompile(`^[a-z0-9][a-z0-9+.\-]{0,99}(:[a-z0-9]{2,10})?$`)
	rpmPackageRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9+._\-]{0,99}$`)
)

// ValidPackageName prüft einen Paketnamen (ohne Version, ohne Platzhalter und Gruppen) für die Paketverwaltung.
func ValidPackageName(manager, name string) bool {
	if manager == PkgDnf {
		return rpmPackageRe.MatchString(name)
	}
	return debPackageRe.MatchString(name)
}

// PackageNameHint beschreibt die erlaubten Namen für Fehlermeldungen.
func PackageNameHint(manager string) string {
	if manager == PkgDnf {
		return "letters, digits and + . _ - are allowed, without a version, wildcard or group"
	}
	return "lower-case names without a version are allowed"
}

// ParseDnfUpdates liest die Ausgabe von „dnf check-update“: eine Zeile je Paket „Name.Architektur Version Quelle“. Hinweise und der
// Abschnitt „Obsoleting Packages“ zählen nicht.
func ParseDnfUpdates(output string) []string {
	var found []string
	for _, line := range strings.Split(output, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "Obsoleting Packages") {
			break
		}
		f := strings.Fields(trimmed)
		if len(f) != 3 || !strings.Contains(f[0], ".") || strings.HasSuffix(f[0], ":") || !strings.ContainsAny(f[1], "0123456789") {
			continue
		}
		found = append(found, strings.Join(f, " "))
	}
	return found
}

// DnfUpdates fragt über den Root-Helfer nach den ausstehenden Aktualisierungen (dnf braucht dafür Schreibrechte für seinen
// Zwischenspeicher, die der Agent bewusst nicht hat). Ohne Helfer ist die Zahl unbekannt.
func DnfUpdates(ctx context.Context) ([]string, error) {
	if RootRead == nil {
		return nil, errors.New("the root helper is not available, so dnf cannot be asked for updates")
	}
	out, err := RootRead(ctx, "pkg_check", nil)
	if err != nil {
		return nil, err
	}
	return ParseDnfUpdates(out), nil
}

// DnfRebootRequired vergleicht den laufenden Kernel mit dem zuletzt installierten (nur rpm, ohne Rechte). Unbekannt gilt als „nein“.
func DnfRebootRequired(ctx context.Context) bool {
	running, err := Run(ctx, "uname", "-r")
	if err != nil {
		return false
	}
	running = strings.TrimSpace(running)
	out, code, err := RunWith(ctx, Opts{}, "rpm", "-q", "--last", "kernel-core")
	if err != nil || code != 0 {
		out, code, err = RunWith(ctx, Opts{}, "rpm", "-q", "--last", "kernel")
		if err != nil || code != 0 {
			return false
		}
	}
	f := strings.Fields(strings.SplitN(strings.TrimSpace(out), "\n", 2)[0])
	if len(f) == 0 || running == "" {
		return false
	}
	newest := f[0]
	for _, prefix := range []string{"kernel-core-", "kernel-"} {
		if strings.HasPrefix(newest, prefix) {
			return strings.TrimPrefix(newest, prefix) != running
		}
	}
	return false
}

// dnfUpdatesText ist die Ausgabe des Lesewerkzeugs „updates“ für dnf.
func dnfUpdatesText(ctx context.Context) (string, error) {
	lines, err := DnfUpdates(ctx)
	if err != nil {
		return "", err
	}
	var b strings.Builder
	fmt.Fprintf(&b, "Available updates: %d\n", len(lines))
	for i, line := range lines {
		if i >= 60 {
			fmt.Fprintf(&b, "... and %d more\n", len(lines)-60)
			break
		}
		b.WriteString(line + "\n")
	}
	if DnfRebootRequired(ctx) {
		b.WriteString("Reboot required: yes (a newer kernel is installed than the one running)\n")
	}
	return b.String(), nil
}

// dnfPackageInfo zeigt Zustand und Herkunft eines Pakets (nur rpm, nur lesend).
func dnfPackageInfo(ctx context.Context, name string) (string, error) {
	var b strings.Builder
	out, code, err := RunWith(ctx, Opts{}, "rpm", "-qi", name)
	if err != nil {
		return "", err
	}
	if code != 0 {
		b.WriteString("Not installed.\n(Only installed packages are shown here; the repositories of dnf are not asked.)\n")
		return b.String(), nil
	}
	b.WriteString(out)
	if cfg, code, err := RunWith(ctx, Opts{}, "rpm", "-qc", name); err == nil && code == 0 {
		var picked []string
		for _, l := range strings.Split(strings.TrimSpace(cfg), "\n") {
			if strings.HasPrefix(l, "/etc/") {
				picked = append(picked, l)
				if len(picked) >= 15 {
					break
				}
			}
		}
		if len(picked) > 0 {
			b.WriteString("\n-- configuration files below /etc from this package --\n" + strings.Join(picked, "\n") + "\n")
		}
	}
	return b.String(), nil
}
