// Package signing signiert und prüft die Programmdateien des Agenten (ed25519). Es gehört zum Release-Werkzeug copilot-sign und
// nicht zum Agenten selbst; geprüft wird auf dem Server von internal/update (gleiche Nachricht, gleiches Format).
package signing

import (
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/dominikramachers/ha-copilot/agent/internal/update"
)

// PrivateKeyFromPEM liest einen privaten ed25519-Schlüssel im Format PKCS#8 (“openssl genpkey -algorithm ed25519“).
func PrivateKeyFromPEM(data []byte) (ed25519.PrivateKey, error) {
	block, _ := pem.Decode(data)
	if block == nil {
		return nil, errors.New("the signing key is not PEM encoded")
	}
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("the signing key cannot be read: %v", err)
	}
	priv, ok := key.(ed25519.PrivateKey)
	if !ok {
		return nil, errors.New("the signing key is not an ed25519 key")
	}
	return priv, nil
}

// PublicBase64 ist der öffentliche Schlüssel im Format der Richtlinie (update_key): die 32 Rohbytes, Base64.
func PublicBase64(priv ed25519.PrivateKey) string {
	return base64.StdEncoding.EncodeToString(priv.Public().(ed25519.PublicKey))
}

// FileSHA256 liefert die Prüfsumme einer Datei als Hex-Text.
func FileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// Sign signiert Fassung, Architektur und Prüfsumme (Base64).
func Sign(priv ed25519.PrivateKey, version, arch, sha string) string {
	return base64.StdEncoding.EncodeToString(ed25519.Sign(priv, update.SigMessage(version, arch, sha)))
}

// Verify prüft genau so, wie der Agent es tut.
func Verify(pubB64, version, arch, sha, sigB64 string) error {
	return update.VerifySig(strings.TrimSpace(pubB64), version, arch, sha, strings.TrimSpace(sigB64))
}
