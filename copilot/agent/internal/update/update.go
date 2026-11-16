// Package update ist die Selbstaktualisierung des Agenten. Der Hub bietet eine Fassung an (Version, Prüfsumme, optional Signatur);
// der Agent lädt sie über seine gesicherte Verbindung, prüft sie und übergibt sie dem Root-Helfer, der sie installiert.
//
// Vertrauensmodell: Wer den Hub kontrolliert, kann dem Agenten eine neue Programmdatei anbieten, die dann als root läuft. Dagegen
// schützen drei Dinge, alle auf dem Server selbst: (1) die lokale Richtlinie (“update=off|manual|auto“), (2) nur neuere
// Fassungen werden genommen (kein Zurückdrehen auf eine verwundbare), (3) mit “update_key“ in der Richtlinie wird nur
// installiert, was mit dem zugehörigen privaten Schlüssel signiert ist, den der Hub nicht besitzt.
package update

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// MaxSize ist die größte Programmdatei, die angenommen wird.
const MaxSize = 64 << 20

// Offer ist, was der Hub anbietet.
type Offer struct {
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
	Size    int64  `json:"size"`
	Sig     string `json:"sig,omitempty"` // Base64, ed25519 über SigMessage
}

// Valid prüft die Form eines Angebots.
func (o Offer) Valid() bool {
	if _, ok := Parse(o.Version); !ok || o.Size <= 0 || o.Size > MaxSize || len(o.SHA256) != 64 {
		return false
	}
	_, err := hex.DecodeString(o.SHA256)
	return err == nil
}

// Parse liest „1.2.3“ (auch mit führendem v). Alles andere (etwa „dev“) ist keine Fassung.
func Parse(v string) ([3]int, bool) {
	var out [3]int
	parts := strings.Split(strings.TrimPrefix(strings.TrimSpace(v), "v"), ".")
	if len(parts) != 3 {
		return out, false
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 || n > 1_000_000 || strconv.Itoa(n) != p {
			return out, false
		}
		out[i] = n
	}
	return out, true
}

// Newer sagt, ob offered neuer ist als current. Ist eine der beiden keine Fassung (Entwicklungsstand), ist die Antwort nein.
func Newer(offered, current string) bool {
	a, ok1 := Parse(offered)
	b, ok2 := Parse(current)
	if !ok1 || !ok2 {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return a[i] > b[i]
		}
	}
	return false
}

// SigMessage ist der Text, über den signiert wird (bindet Fassung, Architektur und Prüfsumme).
func SigMessage(version, arch, sha string) []byte {
	return []byte("ha-copilot-agent\n" + version + "\n" + arch + "\n" + sha + "\n")
}

// VerifySig prüft die Signatur eines Angebots gegen den öffentlichen Schlüssel aus der Richtlinie (Base64).
func VerifySig(pubB64, version, arch, sha, sigB64 string) error {
	pub, err := base64.StdEncoding.DecodeString(strings.TrimSpace(pubB64))
	if err != nil || len(pub) != ed25519.PublicKeySize {
		return errors.New("update_key in the policy is not a valid ed25519 public key")
	}
	sig, err := base64.StdEncoding.DecodeString(strings.TrimSpace(sigB64))
	if err != nil || len(sig) != ed25519.SignatureSize {
		return errors.New("the offered update has no valid signature (the policy requires one)")
	}
	if !ed25519.Verify(ed25519.PublicKey(pub), SigMessage(version, arch, sha), sig) {
		return errors.New("the signature of the offered update does not match update_key")
	}
	return nil
}

// Download lädt die Datei in dst (0700, Besitzer ist der aufrufende Benutzer) und prüft Größe und Prüfsumme.
func Download(ctx context.Context, client *http.Client, url, dst string, offer Offer) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("download failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("the hub answered %d to the download", resp.StatusCode)
	}
	_ = os.Remove(dst)
	f, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o700)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		f.Close()
		if !ok {
			_ = os.Remove(dst)
		}
	}()
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(f, h), io.LimitReader(resp.Body, offer.Size+1))
	if err != nil {
		return fmt.Errorf("download failed: %w", err)
	}
	if n != offer.Size {
		return fmt.Errorf("the downloaded file has %d bytes, expected %d", n, offer.Size)
	}
	if hex.EncodeToString(h.Sum(nil)) != offer.SHA256 {
		return errors.New("the checksum of the downloaded file does not match the offer")
	}
	if err := f.Sync(); err != nil {
		return err
	}
	ok = true
	return nil
}

// SelfTest führt die Datei mit „version“ aus und prüft, dass sie die angebotene Fassung meldet (läuft, passt zur Architektur).
func SelfTest(ctx context.Context, path, want string) error {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, "version")
	cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "HOME=/nonexistent"}
	cmd.Dir = "/"
	out, err := cmd.Output()
	if err != nil {
		return fmt.Errorf("the new program does not start: %v", err)
	}
	if got := strings.TrimSpace(string(out)); got != want {
		return fmt.Errorf("the new program reports version %q, expected %q", got, want)
	}
	return nil
}
