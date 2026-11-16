package tools

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
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

// searchPath ist der feste Suchpfad für Programme (nicht der Pfad des Agentenprozesses).
const searchPath = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

// LookPath findet ein Programm ausschließlich im festen Suchpfad. Ein Name mit „/“ ist nur erlaubt, wenn er in einem dieser
// Verzeichnisse liegt (etwa /sbin/shutdown); gelöst wird dann über den reinen Dateinamen. Relative Pfade, „..“ und Programme
// außerhalb der Systemverzeichnisse (/tmp, /home, /opt …) werden nie gestartet: ein Auftrag kann so keine abgelegte Datei ausführen.
func LookPath(name string) (string, error) {
	name = strings.TrimSpace(name)
	missing := fmt.Errorf("%s ist auf diesem Server nicht installiert", name)
	if name == "" || strings.ContainsRune(name, 0) || strings.Contains(name, "\\") {
		return "", missing
	}
	base := name
	if strings.Contains(name, "/") {
		clean := filepath.Clean(name)
		if !filepath.IsAbs(clean) {
			return "", missing
		}
		if !inSearchPath(filepath.Dir(clean)) {
			return "", fmt.Errorf("%s liegt nicht in einem Systemverzeichnis (erlaubt: %s)", name, searchPath)
		}
		base = filepath.Base(clean)
	}
	if base == "." || base == ".." || base == "/" {
		return "", missing
	}
	for _, dir := range strings.Split(searchPath, ":") {
		path := dir + "/" + base
		if info, err := os.Stat(path); err == nil && !info.IsDir() && info.Mode()&0o111 != 0 {
			return path, nil
		}
	}
	return "", missing
}

func inSearchPath(dir string) bool {
	for _, d := range strings.Split(searchPath, ":") {
		if d == dir {
			return true
		}
	}
	return false
}

// Opts steuert RunWith.
type Opts struct {
	Timeout time.Duration // 0 = cmdTimeout
	Env     []string      // zusätzlich zum festen Umfeld
	Dir     string        // Arbeitsverzeichnis, Vorgabe „/“
}

// RunWith führt ein Programm ohne Shell aus: Argumentliste, Zeitlimit, begrenzte Ausgabe, festes Umfeld. Bei Zeitüberschreitung wird die
// ganze Prozessgruppe beendet. Gibt die Ausgabe (Standard- und Fehlerausgabe zusammen), den Exit-Code (-1 = nicht gestartet oder
// abgebrochen) und einen Fehler nur zurück, wenn das Programm nicht laufen konnte oder die Zeit abgelaufen ist.
func RunWith(ctx context.Context, opts Opts, name string, args ...string) (string, int, error) {
	path, err := LookPath(name)
	if err != nil {
		return "", -1, err
	}
	timeout := opts.Timeout
	if timeout <= 0 {
		timeout = cmdTimeout
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, args...)
	cmd.Env = append([]string{
		"PATH=" + searchPath, "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "SYSTEMD_PAGER=", "SYSTEMD_COLORS=0", "TERM=dumb", "HOME=/nonexistent",
	}, opts.Env...)
	cmd.Dir = "/"
	if opts.Dir != "" {
		cmd.Dir = opts.Dir
	}
	cmd.Stdin = nil
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	cmd.WaitDelay = 5 * time.Second
	out := &limitedBuffer{}
	cmd.Stdout = out
	cmd.Stderr = out
	runErr := cmd.Run()
	text := out.buf.String()
	if out.truncated {
		text += "\n[… Ausgabe gekürzt]"
	}
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return text, -1, fmt.Errorf("%s hat nicht innerhalb von %d Sekunden geantwortet", name, int(timeout.Seconds()))
	}
	var exit *exec.ExitError
	if errors.As(runErr, &exit) {
		return text, exit.ExitCode(), nil
	}
	if runErr != nil {
		return text, -1, runErr
	}
	return text, 0, nil
}

// Run führt ein lesendes Programm ohne Shell aus (feste Argumentliste), mit Zeitlimit, begrenzter Ausgabe und festem Umfeld.
// Ein Exit-Code ungleich 0 ist kein Fehler: viele Befehle (systemctl status) melden damit nur einen Zustand.
func Run(ctx context.Context, name string, args ...string) (string, error) {
	text, code, err := RunWith(ctx, Opts{}, name, args...)
	if err != nil {
		return text, err
	}
	if code != 0 {
		return fmt.Sprintf("%s\n[Exit-Code %d]", strings.TrimRight(text, "\n"), code), nil
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
