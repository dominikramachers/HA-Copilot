// Package testpki erzeugt in Tests eine kleine private CA, wie sie das Add-on betreibt.
package testpki

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"time"
)

// CA ist eine Zertifizierungsstelle.
type CA struct {
	Cert *x509.Certificate
	Key  *ecdsa.PrivateKey
	DER  []byte
}

// NewCA erzeugt eine CA.
func NewCA() *CA {
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "Test-CA"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(24 * time.Hour),
		IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign,
	}
	der, _ := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	cert, _ := x509.ParseCertificate(der)
	return &CA{Cert: cert, Key: key, DER: der}
}

// Options verändern ein ausgestelltes Zertifikat (für Negativtests).
type Options struct {
	NotAfter time.Time
	Usage    x509.ExtKeyUsage
}

// Issue stellt ein Zertifikat für einen öffentlichen Schlüssel aus.
func (c *CA) Issue(pub *ecdsa.PublicKey, cn string, opt Options) []byte {
	if opt.NotAfter.IsZero() {
		opt.NotAfter = time.Now().Add(12 * time.Hour)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: cn},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: opt.NotAfter,
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{opt.Usage},
		BasicConstraintsValid: true, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}, DNSNames: []string{"localhost"},
	}
	der, _ := x509.CreateCertificate(rand.Reader, tmpl, c.Cert, pub, c.Key)
	return der
}

// ServerChain gibt ein TLS-Zertifikat für einen Hub zurück: Zertifikat des Hubs, dann die CA (wie hub.pem des Add-ons).
func (c *CA) ServerChain(opt Options) tls.Certificate {
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	opt.Usage = x509.ExtKeyUsageServerAuth
	leaf := c.Issue(&key.PublicKey, "Hub", opt)
	return tls.Certificate{Certificate: [][]byte{leaf, c.DER}, PrivateKey: key}
}

// PEM kodiert DER-Bytes.
func PEM(kind string, der []byte) string {
	return string(pem.EncodeToMemory(&pem.Block{Type: kind, Bytes: der}))
}
