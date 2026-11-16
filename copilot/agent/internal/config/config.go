// Package config verwaltet das Zustandsverzeichnis des Agenten (Schlüssel, Zertifikat, Hub-Adresse).
package config

import (
	"crypto/ecdsa"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

const (
	fileState = "agent.json"
	fileKey   = "agent.key"
	fileCert  = "agent.crt"
)

// State ist, was nach der Anmeldung dauerhaft gespeichert wird.
type State struct {
	Hub           string `json:"hub"`            // host:port
	CAFingerprint string `json:"ca_fingerprint"` // sha256:<hex> des CA-Zertifikats des Hubs
	ServerID      string `json:"server_id"`
	CAPEM         string `json:"ca_pem"`
}

// Dir ist das Zustandsverzeichnis.
type Dir string

func (d Dir) path(name string) string { return filepath.Join(string(d), name) }

// Ensure legt das Verzeichnis an (nur für den Agenten-Benutzer lesbar).
func (d Dir) Ensure() error {
	if err := os.MkdirAll(string(d), 0o700); err != nil {
		return err
	}
	return os.Chmod(string(d), 0o700)
}

func writePrivate(path string, data []byte) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// SaveKey speichert den privaten Schlüssel (0600).
func (d Dir) SaveKey(key *ecdsa.PrivateKey) error {
	der, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return err
	}
	return writePrivate(d.path(fileKey), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))
}

// KeyPath und CertPath werden von TLS zum Laden benutzt.
func (d Dir) KeyPath() string  { return d.path(fileKey) }
func (d Dir) CertPath() string { return d.path(fileCert) }

// SaveCert speichert das vom Hub ausgestellte Zertifikat.
func (d Dir) SaveCert(certPEM string) error { return writePrivate(d.path(fileCert), []byte(certPEM)) }

// Save schreibt den Zustand.
func (d Dir) Save(s State) error {
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	return writePrivate(d.path(fileState), data)
}

// Load liest den Zustand; fehlt er, wird ein verständlicher Fehler zurückgegeben.
func (d Dir) Load() (State, error) {
	var s State
	data, err := os.ReadFile(d.path(fileState))
	if errors.Is(err, os.ErrNotExist) {
		return s, fmt.Errorf("this agent is not enrolled yet (run \"copilot-agent enroll\" first)")
	}
	if err != nil {
		return s, err
	}
	if err := json.Unmarshal(data, &s); err != nil {
		return s, fmt.Errorf("agent.json is damaged: %w", err)
	}
	if s.Hub == "" || s.CAFingerprint == "" {
		return s, fmt.Errorf("agent.json is incomplete")
	}
	return s, nil
}

// Enrolled sagt, ob schon Schlüssel, Zertifikat und Zustand vorhanden sind.
func (d Dir) Enrolled() bool {
	for _, name := range []string{fileState, fileKey, fileCert} {
		if _, err := os.Stat(d.path(name)); err != nil {
			return false
		}
	}
	return true
}

// Erneuerung: Das neue Schlüsselpaar wird zuerst als „.new“ abgelegt und dann über das alte gelegt. Reißt der Vorgang zwischen den
// beiden Umbenennungen ab, passen Schlüssel und Zertifikat nicht zusammen; LoadKeyPair probiert deshalb alle Kombinationen und
// schließt eine unterbrochene Erneuerung ab.
const newSuffix = ".new"

// StageRenewal legt Schlüssel und Zertifikat der Erneuerung als „.new“ ab (noch ohne Wirkung).
func (d Dir) StageRenewal(key *ecdsa.PrivateKey, certPEM string) error {
	der, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return err
	}
	if err := writePrivate(d.path(fileKey+newSuffix), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der})); err != nil {
		return err
	}
	return writePrivate(d.path(fileCert+newSuffix), []byte(certPEM))
}

// PromoteRenewal macht das abgelegte Paar zum gültigen (Schlüssel zuerst, dann Zertifikat).
func (d Dir) PromoteRenewal() error {
	for _, name := range []string{fileKey, fileCert} {
		if _, err := os.Stat(d.path(name + newSuffix)); err != nil {
			continue
		}
		if err := os.Rename(d.path(name+newSuffix), d.path(name)); err != nil {
			return err
		}
	}
	return nil
}

// LoadKeyPair lädt Schlüssel und Zertifikat; passt das Paar nicht zusammen, werden die Dateien einer unterbrochenen Erneuerung
// einbezogen.
func (d Dir) LoadKeyPair() (*tls.Certificate, error) {
	type pair struct{ cert, key string }
	candidates := []pair{
		{fileCert, fileKey}, {fileCert + newSuffix, fileKey + newSuffix}, {fileCert + newSuffix, fileKey}, {fileCert, fileKey + newSuffix},
	}
	var first error
	for i, c := range candidates {
		cert, err := tls.LoadX509KeyPair(d.path(c.cert), d.path(c.key))
		if err != nil {
			if i == 0 {
				first = err
			}
			continue
		}
		if i > 0 {
			_ = d.PromoteRenewal()
		}
		return &cert, nil
	}
	return nil, first
}
