package signing

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/x509"
	"encoding/base64"
	"encoding/pem"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func newKey(t *testing.T) (ed25519.PrivateKey, []byte) {
	t.Helper()
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	der, err := x509.MarshalPKCS8PrivateKey(priv)
	if err != nil {
		t.Fatal(err)
	}
	return priv, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der})
}

func TestSignAndVerifyRoundTrip(t *testing.T) {
	priv, pemData := newKey(t)
	parsed, err := PrivateKeyFromPEM(pemData)
	if err != nil || !priv.Equal(parsed) {
		t.Fatalf("PEM round trip failed: %v", err)
	}
	pub := PublicBase64(parsed)
	file := filepath.Join(t.TempDir(), "agent")
	if err := os.WriteFile(file, []byte("binary"), 0o700); err != nil {
		t.Fatal(err)
	}
	sha, err := FileSHA256(file)
	if err != nil {
		t.Fatal(err)
	}
	sig := Sign(parsed, "0.61.0", "amd64", sha)
	if err := Verify(pub, "0.61.0", "amd64", sha, sig+"\n"); err != nil {
		t.Fatalf("valid signature rejected: %v", err)
	}
	// every part of the message is bound: version, architecture, content
	for name, args := range map[string][3]string{
		"version": {"0.61.1", "amd64", sha},
		"arch":    {"0.61.0", "arm64", sha},
		"sha":     {"0.61.0", "amd64", strings.Repeat("0", 64)},
	} {
		if err := Verify(pub, args[0], args[1], args[2], sig); err == nil {
			t.Errorf("a changed %s must not verify", name)
		}
	}
	// a foreign key does not verify
	other, _ := newKey(t)
	if err := Verify(PublicBase64(other), "0.61.0", "amd64", sha, sig); err == nil {
		t.Error("a signature from another key must not verify")
	}
}

func TestPrivateKeyFromPEMRefusesOtherInput(t *testing.T) {
	for name, data := range map[string]string{"empty": "", "text": "not a key", "garbage": "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"} {
		if _, err := PrivateKeyFromPEM([]byte(data)); err == nil {
			t.Errorf("%s must be refused", name)
		}
	}
}

func TestPublicKeyFormatMatchesThePolicy(t *testing.T) {
	priv, _ := newKey(t)
	raw, err := base64.StdEncoding.DecodeString(PublicBase64(priv))
	if err != nil || len(raw) != ed25519.PublicKeySize {
		t.Fatalf("update_key must be the 32 raw bytes in base64, got %d bytes (%v)", len(raw), err)
	}
}
