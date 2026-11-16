package hub

import (
	"crypto/ecdsa"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/config"
	"github.com/dominikramachers/ha-copilot/agent/internal/tlsutil"
)

const (
	// DefaultRenewBefore: so lange vor dem Ablauf beginnt der Agent, sein Zertifikat zu erneuern.
	DefaultRenewBefore = 120 * 24 * time.Hour
	// renewRetry: so lange wartet der Agent nach einem Versuch, bevor er es erneut versucht.
	renewRetry = 30 * time.Minute
)

// errRenewed beendet die Verbindung nach einer Erneuerung, damit sich der Agent mit dem neuen Zertifikat neu anmeldet.
var errRenewed = errors.New("certificate renewed, reconnecting")

// CertExpiry liest das Ablaufdatum des Zertifikats des Agenten.
func CertExpiry(dir config.Dir) (time.Time, error) {
	data, err := os.ReadFile(dir.CertPath())
	if err != nil {
		return time.Time{}, err
	}
	block, _ := pem.Decode(data)
	if block == nil {
		return time.Time{}, errors.New("agent.crt is not a certificate")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return time.Time{}, err
	}
	return cert.NotAfter, nil
}

// renewal ist eine laufende Erneuerung innerhalb einer Verbindung: der neue Schlüssel wartet auf das Zertifikat.
type renewal struct {
	mu  sync.Mutex
	key *ecdsa.PrivateKey
}

// lastRenewAsk merkt sich über Verbindungen hinweg, wann zuletzt ein Zertifikat angefragt wurde. Ohne das würde ein Agent, dessen
// frisch erneuertes Zertifikat (wegen einer kurzen Laufzeit) schon wieder fällig ist, bei jeder neuen Verbindung neu anfragen.
var (
	lastRenewMu  sync.Mutex
	lastRenewAsk time.Time
)

// start schickt eine Zertifikatsanfrage, wenn es fällig ist (oder erzwungen wird) und nicht gerade eine offen ist.
func (r *renewal) start(a *Agent, send func(any) error, force bool) {
	before := a.RenewBefore
	if before == 0 {
		before = DefaultRenewBefore
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	lastRenewMu.Lock()
	recent := !lastRenewAsk.IsZero() && time.Since(lastRenewAsk) < renewRetry
	lastRenewMu.Unlock()
	if recent && !force {
		return
	}
	if !force {
		expires, err := CertExpiry(a.Dir)
		if err != nil || time.Until(expires) > before {
			return
		}
	}
	key, err := tlsutil.NewKey()
	if err != nil {
		return
	}
	host, _ := os.Hostname()
	csr, err := tlsutil.CSRPEM(key, host)
	if err != nil {
		return
	}
	if err := send(map[string]string{"t": "renew", "csr": csr}); err != nil {
		return
	}
	r.key = key
	lastRenewMu.Lock()
	lastRenewAsk = time.Now()
	lastRenewMu.Unlock()
	slog.Info("requesting a new certificate from the hub")
}

// finish nimmt das neue Zertifikat entgegen: prüfen (gehört zum neuen Schlüssel, von der angehefteten CA), ablegen, aktivieren.
func (r *renewal) finish(a *Agent, state config.State, m message) error {
	r.mu.Lock()
	key := r.key
	r.key = nil
	r.mu.Unlock()
	if key == nil {
		return errors.New("a certificate arrived without a request")
	}
	reply := message{Cert: m.Cert, CA: state.CAPEM}
	if err := checkIssued(reply, state.CAFingerprint, &key.PublicKey); err != nil {
		return fmt.Errorf("the renewed certificate was rejected: %w", err)
	}
	block, _ := pem.Decode([]byte(m.Cert))
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil || !cert.NotAfter.After(time.Now().Add(24*time.Hour)) {
		return errors.New("the renewed certificate is already (almost) expired")
	}
	if err := a.Dir.StageRenewal(key, m.Cert); err != nil {
		return err
	}
	if err := a.Dir.PromoteRenewal(); err != nil {
		return err
	}
	slog.Info("certificate renewed", "valid_until", cert.NotAfter.UTC().Format(time.RFC3339))
	return errRenewed
}
