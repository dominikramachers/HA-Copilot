package tools

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	// MaxOutput ist die größte Antwort an den Hub (der Hub kürzt zusätzlich auf 60 000 Zeichen).
	MaxOutput = 50000
	// maxCapture begrenzt, wie viel ein Prozess überhaupt in den Speicher schreiben darf.
	maxCapture = 400 * 1024
	cmdTimeout = 20 * time.Second
)

// limitedBuffer nimmt höchstens maxCapture Bytes an und verwirft den Rest (der Prozess läuft weiter, bis er endet oder die Zeit abläuft).
type limitedBuffer struct {
	buf       bytes.Buffer
	truncated bool
}

func (l *limitedBuffer) Write(p []byte) (int, error) {
	room := maxCapture - l.buf.Len()
	if room <= 0 {
		l.truncated = true
		return len(p), nil
	}
	if len(p) > room {
		l.buf.Write(p[:room])
		l.truncated = true
		return len(p), nil
	}
	return l.buf.Write(p)
}

// Run führt ein Programm ohne Shell aus (feste Argumentliste), mit Zeitlimit, begrenzter Ausgabe und festem Umfeld.
// Ein Exit-Code ungleich 0 ist kein Fehler: viele Befehle (systemctl status) melden damit nur einen Zustand.
func Run(ctx context.Context, name string, args ...string) (string, error) {
	path, err := exec.LookPath(name)
	if err != nil {
		return "", fmt.Errorf("%s ist auf diesem Server nicht installiert", name)
	}
	ctx, cancel := context.WithTimeout(ctx, cmdTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, args...)
	cmd.Env = []string{
		"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
		"LANG=C.UTF-8", "LC_ALL=C.UTF-8", "SYSTEMD_PAGER=", "SYSTEMD_COLORS=0", "TERM=dumb",
	}
	cmd.Stdin = nil
	out := &limitedBuffer{}
	cmd.Stdout = out
	cmd.Stderr = out
	runErr := cmd.Run()
	text := out.buf.String()
	if out.truncated {
		text += "\n[… Ausgabe gekürzt]"
	}
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return text, fmt.Errorf("%s hat nicht innerhalb von %d Sekunden geantwortet", name, int(cmdTimeout.Seconds()))
	}
	var exit *exec.ExitError
	if errors.As(runErr, &exit) {
		return fmt.Sprintf("%s\n[Exit-Code %d]", strings.TrimRight(text, "\n"), exit.ExitCode()), nil
	}
	if runErr != nil {
		return text, runErr
	}
	return text, nil
}

var (
	privateKeyBlock = regexp.MustCompile(`(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)`)
	secretAssign    = regexp.MustCompile(`(?i)\b(password|passwd|passphrase|secret|token|api[_-]?key|access[_-]?key|authorization|bearer)(["']?\s*[:=]\s*["']?|\s+)([^\s"',;]{3,})`)
	authScheme      = regexp.MustCompile(`(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}`)
	credentialURL   = regexp.MustCompile(`(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+):[^\s@/]+@`)
)

// Redact entfernt offensichtliche Geheimnisse aus einer Ausgabe (Schlüsselblöcke, „password=…“, Zugangsdaten in Adressen).
// Das ist ein zusätzlicher Schutz, kein Ersatz dafür, dass die Werkzeuge ohnehin keine Dateien ausgeben.
func Redact(s string) string {
	s = privateKeyBlock.ReplaceAllString(s, "[privater Schlüssel entfernt]")
	s = credentialURL.ReplaceAllString(s, "$1:***@")
	s = authScheme.ReplaceAllString(s, "$1 ***")
	return secretAssign.ReplaceAllString(s, "$1$2***")
}

// Clean macht eine Ausgabe sendefertig: gültiges UTF-8, keine Steuerzeichen außer Zeilenumbruch und Tabulator, begrenzte Länge.
func Clean(s string) string {
	s = strings.ToValidUTF8(s, "?")
	var b strings.Builder
	for _, r := range s {
		if r == '\n' || r == '\t' || (r >= 0x20 && r != 0x7f) {
			b.WriteRune(r)
		}
	}
	out := b.String()
	if len(out) > MaxOutput {
		cut := out[:MaxOutput]
		for !utf8.ValidString(cut) && len(cut) > 0 {
			cut = cut[:len(cut)-1]
		}
		out = cut + "\n[… Ausgabe gekürzt]"
	}
	return strings.TrimRight(out, "\n") + "\n"
}
