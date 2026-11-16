// Package tlsutil enthält die TLS-Bausteine des Agenten: Schlüssel und Zertifikatsanfrage (CSR) sowie die Prüfung des Hubs
// gegen den angehefteten Fingerabdruck seiner privaten CA.
package tlsutil

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"fmt"
	"strings"
	"time"
)

// NewKey erzeugt einen EC-Schlüssel (P-256); der Hub nimmt nur diese Art an.
func NewKey() (*ecdsa.PrivateKey, error) {
	return ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
}

// CSRPEM erzeugt eine Zertifikatsanfrage. Der Hub übernimmt daraus nur den öffentlichen Schlüssel.
func CSRPEM(key *ecdsa.PrivateKey, hostname string) (string, error) {
	der, err := x509.CreateCertificateRequest(rand.Reader, &x509.CertificateRequest{
		Subject: pkix.Name{CommonName: hostname},
	}, key)
	if err != nil {
		return "", err
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: der})), nil
}

// Fingerprint ist „sha256:<hex>“ über die DER-Bytes eines Zertifikats.
func Fingerprint(der []byte) string {
	sum := sha256.Sum256(der)
	return "sha256:" + hex.EncodeToString(sum[:])
}

// NormalizeFingerprint akzeptiert „sha256:ab…“ oder nur Hex (auch mit Doppelpunkten) und gibt „sha256:<hex klein>“ zurück.
func NormalizeFingerprint(s string) (string, error) {
	s = strings.ToLower(strings.TrimSpace(s))
	s = strings.TrimPrefix(s, "sha256:")
	s = strings.ReplaceAll(s, ":", "")
	if len(s) != 64 {
		return "", errors.New("invalid fingerprint (expected: sha256: and 64 hex characters)")
	}
	if _, err := hex.DecodeString(s); err != nil {
		return "", errors.New("invalid fingerprint (not hex)")
	}
	return "sha256:" + s, nil
}

// verifyAgainstPinnedCA prüft die vom Hub gesendete Kette: Sie muss das CA-Zertifikat mit dem angehefteten Fingerabdruck enthalten
// und das erste Zertifikat muss von dieser CA als Serverzertifikat ausgestellt sein und gelten. Der Name wird nicht geprüft –
// die Adresse des Hubs kann je nach Netz (NAT, VPN) abweichen; die Identität ergibt sich aus der privaten CA.
func verifyAgainstPinnedCA(fingerprint string, rawCerts [][]byte, now time.Time) error {
	if len(rawCerts) == 0 {
		return errors.New("the hub sent no certificate")
	}
	var root *x509.Certificate
	for _, raw := range rawCerts {
		if Fingerprint(raw) == fingerprint {
			cert, err := x509.ParseCertificate(raw)
			if err != nil {
				return err
			}
			root = cert
			break
		}
	}
	if root == nil {
		return errors.New("the certificate of the hub does not belong to the expected CA (fingerprint mismatch)")
	}
	leaf, err := x509.ParseCertificate(rawCerts[0])
	if err != nil {
		return err
	}
	if leaf.Equal(root) {
		return errors.New("the hub must not use a CA certificate as its server certificate")
	}
	pool := x509.NewCertPool()
	pool.AddCert(root)
	_, err = leaf.Verify(x509.VerifyOptions{Roots: pool, CurrentTime: now, KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}})
	return err
}

// Config baut die TLS-Einstellungen des Agenten: nur TLS 1.3, Prüfung des Hubs gegen den Fingerabdruck der CA, optional mit
// Client-Zertifikat (für den Betrieb; bei der Anmeldung gibt es noch keines).
func Config(fingerprint string, clientCert *tls.Certificate) *tls.Config {
	cfg := &tls.Config{
		MinVersion:         tls.VersionTLS13,
		InsecureSkipVerify: true, // ersetzt durch VerifyPeerCertificate: die eigene Prüfung gegen die angeheftete CA
		VerifyPeerCertificate: func(rawCerts [][]byte, _ [][]*x509.Certificate) error {
			if err := verifyAgainstPinnedCA(fingerprint, rawCerts, time.Now()); err != nil {
				return fmt.Errorf("hub not trusted: %w", err)
			}
			return nil
		},
	}
	if clientCert != nil {
		cfg.Certificates = []tls.Certificate{*clientCert}
	}
	return cfg
}

// LoadClientCert lädt Zertifikat und Schlüssel des Agenten.
func LoadClientCert(certPath, keyPath string) (*tls.Certificate, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, err
	}
	return &cert, nil
}
