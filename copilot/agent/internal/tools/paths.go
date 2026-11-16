package tools

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// sensitivePat erkennt Pfade, die vertrauliche Inhalte vermuten lassen (Schlüssel, Kennwörter, Token, Geheimnisse).
var sensitivePat = regexp.MustCompile(`(?i)(/etc/shadow|/etc/gshadow|/etc/sudoers|/\.ssh/|/\.gnupg|/etc/ssl/private|\.pem$|\.key$|\.env$|id_rsa|id_ed25519|/proc/[0-9]+/environ|^/root(/|$)|\.kdbx|secret|credential|token|/etc/copilot-agent|/var/lib/copilot-agent|authorized_keys|\.p12$|\.pfx$|\.keystore$|/\.netrc|/\.pgpass|\.htpasswd)`)

// SensitivePath sagt, ob ein Pfad vertrauliche Inhalte vermuten lässt.
func SensitivePath(p string) bool { return sensitivePat.MatchString(p) }

const maxSymlinks = 8

// ResolveExisting löst einen absoluten Pfad auf, indem es Verzeichnis für Verzeichnis durchläuft. Eingesetzt werden nur Namen, die
// das Dateisystem selbst geliefert hat, nie der eingegebene Text. Symbolische Links werden aufgelöst (höchstens 8). Das Ergebnis
// ist ein sauberer, absoluter Pfad ohne Links.
func ResolveExisting(p string) (string, error) {
	if !filepath.IsAbs(p) || strings.ContainsRune(p, 0) || len(p) > 400 {
		return "", errors.New("the path must be absolute (starting with /)")
	}
	rest := strings.Split(strings.Trim(filepath.Clean(p), "/"), "/")
	if len(rest) == 1 && rest[0] == "" {
		return "/", nil
	}
	cur := "/"
	links := 0
	for len(rest) > 0 {
		name := rest[0]
		rest = rest[1:]
		if name == "" || name == "." {
			continue
		}
		if name == ".." {
			cur = filepath.Dir(cur)
			continue
		}
		entries, err := os.ReadDir(cur)
		if err != nil {
			return "", fmt.Errorf("cannot read the directory %s: %v", cur, errText(err))
		}
		var found os.DirEntry
		for _, e := range entries {
			if e.Name() == name {
				found = e
				break
			}
		}
		if found == nil {
			return "", fmt.Errorf("no such file or directory: %s", filepath.Join(cur, name))
		}
		next := filepath.Join(cur, found.Name())
		if found.Type()&os.ModeSymlink != 0 {
			links++
			if links > maxSymlinks {
				return "", errors.New("too many symbolic links")
			}
			target, err := os.Readlink(next)
			if err != nil {
				return "", err
			}
			if !filepath.IsAbs(target) {
				target = filepath.Join(cur, target)
			}
			rest = append(strings.Split(strings.Trim(filepath.Clean(target), "/"), "/"), rest...)
			cur = "/"
			continue
		}
		cur = next
	}
	return cur, nil
}

var lastNameRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+@=,~-]{0,199}$`)

// ResolveParent löst das Verzeichnis eines (womöglich noch nicht vorhandenen) Pfades auf. Der letzte Name muss schlicht sein.
// Gibt den aufgelösten Pfad zurück und ob die Datei schon existiert. Ist der letzte Name ein symbolischer Link, ist das ein Fehler.
func ResolveParent(p string) (string, bool, error) {
	if !filepath.IsAbs(p) || strings.ContainsRune(p, 0) || len(p) > 400 || filepath.Clean(p) != p || strings.HasSuffix(p, "/") {
		return "", false, errors.New("the path must be absolute, normalized (no .. or //) and name a file")
	}
	dir, name := filepath.Split(p)
	if !lastNameRe.MatchString(name) {
		return "", false, errors.New("the file name contains characters that are not allowed")
	}
	realDir, err := ResolveExisting(dir)
	if err != nil {
		return "", false, err
	}
	entries, err := os.ReadDir(realDir)
	if err != nil {
		return "", false, fmt.Errorf("cannot read the directory %s: %v", realDir, errText(err))
	}
	for _, e := range entries {
		if e.Name() == name {
			if e.Type()&os.ModeSymlink != 0 {
				return "", true, errors.New("the path is a symbolic link; name the real file instead")
			}
			return filepath.Join(realDir, e.Name()), true, nil
		}
	}
	return filepath.Join(realDir, name), false, nil
}

func errText(err error) string {
	var pe *os.PathError
	if errors.As(err, &pe) {
		return pe.Err.Error()
	}
	return err.Error()
}
