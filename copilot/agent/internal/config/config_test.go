package config

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"os"
	"testing"

	"github.com/dominikramachers/ha-copilot/agent/internal/testpki"
)

func newPair(t *testing.T, ca *testpki.CA) (*ecdsa.PrivateKey, string) {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	der := ca.Issue(&key.PublicKey, "agent", testpki.Options{Usage: x509.ExtKeyUsageClientAuth})
	return key, testpki.PEM("CERTIFICATE", der)
}

func fingerprint(t *testing.T, d Dir) string {
	t.Helper()
	cert, err := d.LoadKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	return string(cert.Certificate[0])
}

func TestRenewalStageAndPromote(t *testing.T) {
	ca := testpki.NewCA()
	d := Dir(t.TempDir())
	oldKey, oldCert := newPair(t, ca)
	if err := d.SaveKey(oldKey); err != nil {
		t.Fatal(err)
	}
	if err := d.SaveCert(oldCert); err != nil {
		t.Fatal(err)
	}
	before := fingerprint(t, d)
	newKey, newCert := newPair(t, ca)
	if err := d.StageRenewal(newKey, newCert); err != nil {
		t.Fatal(err)
	}
	// staged but not promoted: the old pair is still in effect
	if got := fingerprint(t, d); got != before {
		// LoadKeyPair prefers the intact main pair
		t.Fatal("the staged renewal must not take effect before promotion")
	}
	if err := d.PromoteRenewal(); err != nil {
		t.Fatal(err)
	}
	if fingerprint(t, d) == before {
		t.Fatal("after promotion the new certificate must be used")
	}
	for _, name := range []string{fileKey + newSuffix, fileCert + newSuffix} {
		if _, err := os.Stat(d.path(name)); err == nil {
			t.Errorf("%s must be gone after promotion", name)
		}
	}
}

// An interrupted promotion (key replaced, certificate not yet) must heal itself on the next load.
func TestLoadKeyPairHealsInterruptedPromotion(t *testing.T) {
	ca := testpki.NewCA()
	d := Dir(t.TempDir())
	oldKey, oldCert := newPair(t, ca)
	_ = d.SaveKey(oldKey)
	_ = d.SaveCert(oldCert)
	newKey, newCert := newPair(t, ca)
	_ = d.StageRenewal(newKey, newCert)
	// only the key was moved
	if err := os.Rename(d.path(fileKey+newSuffix), d.path(fileKey)); err != nil {
		t.Fatal(err)
	}
	cert, err := d.LoadKeyPair()
	if err != nil {
		t.Fatalf("the mixed state must still load: %v", err)
	}
	block, _ := pem.Decode([]byte(newCert))
	if string(cert.Certificate[0]) != string(block.Bytes) {
		t.Error("the new certificate must be chosen")
	}
	if _, err := os.Stat(d.path(fileCert + newSuffix)); err == nil {
		t.Error("the leftover files must be cleaned up")
	}
	if _, err := d.LoadKeyPair(); err != nil {
		t.Errorf("second load: %v", err)
	}
}

func TestLoadKeyPairWithoutFiles(t *testing.T) {
	if _, err := Dir(t.TempDir()).LoadKeyPair(); err == nil {
		t.Error("an empty directory must fail")
	}
}
