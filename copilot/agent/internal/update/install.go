package update

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"context"

	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
)

const (
	// ConfirmWindow: so lange hat die neue Fassung Zeit, sich beim Hub zu melden, sonst wird zurückgesetzt.
	ConfirmWindow = 5 * time.Minute
	pendingName   = "update-pending"
	failedName    = "update-failed"
	prevSuffix    = ".prev"
	newSuffix     = ".new"
)

// Installer ist der Root-Teil (läuft im Helfer). Alle Pfade und Außenwirkungen sind austauschbar, damit er sich testen lässt.
type Installer struct {
	Bin      string // installierte Programmdatei
	Dir      string // Verzeichnis für Marken (Richtlinienverzeichnis, nur root schreibt)
	StateDir string // Zustandsverzeichnis des Agenten (dort liegt die heruntergeladene Datei)
	AgentUID int
	Current  string // Fassung des laufenden Helfers
	Arch     string
	// Restart startet Agent und Helfer neu (nach der Antwort). Watchdog plant einen unabhängigen Rücksetzer; CancelWatchdog nimmt ihn zurück.
	Restart        func()
	Watchdog       func(after time.Duration, version string)
	CancelWatchdog func()
	Now            func() time.Time

	mu sync.Mutex
}

// Request ist die Anfrage des Agenten.
type Request struct {
	Offer
	Auto bool `json:"auto"` // vom Agenten selbst (Richtlinie auto) ausgelöst, nicht vom Hub angestoßen
}

type pending struct {
	From     string `json:"from"`
	To       string `json:"to"`
	Deadline int64  `json:"deadline"`
}

// Failure ist die Notiz zu einem zurückgesetzten Update.
type Failure struct {
	Version string `json:"version"`
	At      int64  `json:"at"`
	Reason  string `json:"reason"`
}

func (in *Installer) now() time.Time {
	if in.Now != nil {
		return in.Now()
	}
	return time.Now()
}

func (in *Installer) staged() string {
	return filepath.Join(in.StateDir, "update", "copilot-agent.new")
}

// StagedPath ist der Ort, an den der Agent die geprüfte Datei legt.
func StagedPath(stateDir string) string {
	return filepath.Join(stateDir, "update", "copilot-agent.new")
}

// Install prüft Richtlinie und Datei noch einmal und ersetzt das Programm. Die neue Fassung läuft erst nach dem Neustart.
func (in *Installer) Install(pol policy.Policy, req Request) (string, error) {
	in.mu.Lock()
	defer in.mu.Unlock()
	switch {
	case pol.Update == policy.UpdateOff:
		return "", errors.New("updates are switched off locally on this server (update=off)")
	case req.Auto && pol.Update != policy.UpdateAuto:
		return "", errors.New("automatic updates are not enabled locally on this server (update=auto)")
	case !req.Valid():
		return "", errors.New("the update offer is invalid")
	case !Newer(req.Version, in.Current):
		return "", fmt.Errorf("version %s is not newer than the installed %s", req.Version, in.Current)
	}
	if f := in.LastFailure(); f != nil && f.Version == req.Version {
		return "", fmt.Errorf("version %s was installed before and had to be rolled back; it is not tried again", req.Version)
	}
	if _, err := os.Stat(filepath.Join(in.Dir, pendingName)); err == nil {
		return "", errors.New("a previous update is still waiting for confirmation")
	}
	if pol.UpdateKey != "" {
		if err := VerifySig(pol.UpdateKey, req.Version, in.Arch, req.SHA256, req.Sig); err != nil {
			return "", err
		}
	}
	// Die Datei wird über den geöffneten Dateideskriptor gelesen (keine Lücke zwischen Prüfen und Verwenden) und in eine Datei
	// kopiert, die nur root beschreiben kann.
	src, err := os.OpenFile(in.staged(), os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return "", fmt.Errorf("the downloaded file is not there: %v", err)
	}
	defer src.Close()
	info, err := src.Stat()
	if err != nil {
		return "", err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !info.Mode().IsRegular() || !ok || (int(st.Uid) != in.AgentUID && st.Uid != 0) || info.Size() != req.Size {
		return "", errors.New("the downloaded file does not look as expected")
	}
	tmp := in.Bin + newSuffix
	_ = os.Remove(tmp)
	dst, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o755)
	if err != nil {
		return "", err
	}
	h := sha256.New()
	_, err = io.Copy(io.MultiWriter(dst, h), io.LimitReader(src, MaxSize))
	if cerr := dst.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		_ = os.Remove(tmp)
		return "", err
	}
	if hex.EncodeToString(h.Sum(nil)) != req.SHA256 {
		_ = os.Remove(tmp)
		return "", errors.New("the checksum of the staged file does not match the offer")
	}
	_ = os.Chmod(tmp, 0o755)
	if err := SelfTest(context.Background(), tmp, req.Version); err != nil {
		_ = os.Remove(tmp)
		return "", err
	}
	prev := in.Bin + prevSuffix
	_ = os.Remove(prev)
	if err := os.Rename(in.Bin, prev); err != nil {
		_ = os.Remove(tmp)
		return "", err
	}
	if err := os.Rename(tmp, in.Bin); err != nil {
		_ = os.Rename(prev, in.Bin)
		return "", err
	}
	deadline := in.now().Add(ConfirmWindow)
	raw, _ := json.Marshal(pending{From: in.Current, To: req.Version, Deadline: deadline.Unix()})
	if err := os.WriteFile(filepath.Join(in.Dir, pendingName), raw, 0o644); err != nil {
		_ = os.Rename(prev, in.Bin)
		return "", err
	}
	_ = os.Remove(filepath.Join(in.Dir, failedName))
	_ = os.Remove(in.staged())
	if in.Watchdog != nil {
		in.Watchdog(ConfirmWindow+30*time.Second, req.Version)
	}
	if in.Restart != nil {
		in.Restart()
	}
	return fmt.Sprintf("Installed version %s (was %s). The agent restarts now; the previous version is kept as %s.", req.Version, in.Current, prev), nil
}

// Confirm wird vom neuen Agenten aufgerufen, sobald er den Hub erreicht hat: das Update gilt als gelungen.
func (in *Installer) Confirm() {
	in.mu.Lock()
	defer in.mu.Unlock()
	if err := os.Remove(filepath.Join(in.Dir, pendingName)); err == nil && in.CancelWatchdog != nil {
		in.CancelWatchdog()
	}
}

// Rollback setzt auf die vorherige Fassung zurück und merkt sich die Gründe.
func (in *Installer) rollback(reason string) {
	prev := in.Bin + prevSuffix
	var p pending
	if raw, err := os.ReadFile(filepath.Join(in.Dir, pendingName)); err == nil {
		_ = json.Unmarshal(raw, &p)
	}
	if _, err := os.Stat(prev); err == nil {
		_ = os.Rename(prev, in.Bin)
	}
	raw, _ := json.Marshal(Failure{Version: p.To, At: in.now().Unix(), Reason: reason})
	_ = os.WriteFile(filepath.Join(in.Dir, failedName), raw, 0o644)
	_ = os.Remove(filepath.Join(in.Dir, pendingName))
	if in.CancelWatchdog != nil {
		in.CancelWatchdog()
	}
	if in.Restart != nil {
		in.Restart()
	}
}

// Recover wird beim Start des Helfers aufgerufen: Wartet ein Update noch auf seine Bestätigung, läuft die Frist weiter; ist sie
// abgelaufen, wird sofort zurückgesetzt.
func (in *Installer) Recover() {
	raw, err := os.ReadFile(filepath.Join(in.Dir, pendingName))
	if err != nil {
		return
	}
	var p pending
	if json.Unmarshal(raw, &p) != nil {
		_ = os.Remove(filepath.Join(in.Dir, pendingName))
		return
	}
	wait := time.Until(time.Unix(p.Deadline, 0))
	go func() {
		if wait > 0 {
			time.Sleep(wait)
		}
		in.mu.Lock()
		defer in.mu.Unlock()
		if _, err := os.Stat(filepath.Join(in.Dir, pendingName)); err == nil {
			in.rollback("the new version did not reach the hub in time")
		}
	}()
}

// LastFailure liest die Notiz zu einem zurückgesetzten Update (nil = keine).
func (in *Installer) LastFailure() *Failure { return ReadFailure(in.Dir) }

// ReadFailure liest die Notiz aus dem Richtlinienverzeichnis (auch der Agent darf sie lesen).
func ReadFailure(dir string) *Failure {
	raw, err := os.ReadFile(filepath.Join(dir, failedName))
	if err != nil {
		return nil
	}
	var f Failure
	if json.Unmarshal(raw, &f) != nil || f.Version == "" {
		return nil
	}
	return &f
}
